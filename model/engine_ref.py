"""整网引擎（tt_engine，M3）的整数参考：docs/engine_arch.md §3 数值契约的唯一 Python 定义（PLAN §17 D3）。

全部 numpy int64 精确整数；只有每个 token / patch 一次 float32 sqrt + 除法（IEEE 正确舍入，与 C / HLS 逐位）。
sim/host/engine_ref.cpp 与本文件逐位一致；HLS csim / cosim / 板上对它逐位。

  入口 A（M3a）：int16 Q3.12 的 x_embed 块（PS float embed 后量化，同 v1.4 的 in），内存序 (p, n)
  入口 B（M3b）：int16 立方体（cube_i16.bin）→ 取 7×7 窗 → patch 归一化（§3.6）→ embed（EMB 表）
  12 层：归一化（§3.2）→ Q/K/V 投影（§3.1）→ 注意力（§3.4）→ 残差（§3.3）→ 归一化 → MLP 投影 → 残差
  分类头（§3.6）：token 1 × 逐类 2 幂 int16 权重 → logits Q.16、类别、置信度 Q0.16

两个版本：num=16（W16A18：激活 18 位 Q5.12、mid Q3.14/18、因子 Q1.14）；num=8（W8A8：激活 / mid Q3.4、因子逐矩阵 2 幂 int8）。
块布局一律 (D, N) int64 数组：blk[p, n] = 元素 (p, n)，与 DDR 内存序 p*N + n 相同（.reshape(-1) 即 DDR 字节序）。

前端（契约 v3，09-24）：立方体 bfp，窗内 49 条光谱按最小指数右移舍入对齐，然后
  g = trunc(min(GC / sqrtf((float)V), GMAX))，GC = float32(sqrt((n-1)/n) · 2^S)，GMAX = 2^25 − 1，S = BFP_S = 48
  xn(Q.24) = (d · g) >> (S − 24)
  （FRONT_S = 43 是 v2 整景 k 的常数，只在 --cube-rule max/sat 对照时用）

用法（回归与黄金向量）：
  D:/pytorch/python.exe model/engine_ref.py regress [--scenes longkou honghu hanchuan] [--workers 12]
  D:/pytorch/python.exe model/engine_ref.py regress --num 8 [--workers 4] [--limit 16]   # int8：QAT 权重对 torch 假量化前向，逐部件分解
  D:/pytorch/python.exe model/engine_ref.py report8        # 由 build/host/int8_ref/engine_ref_i8_<景>.npz 重算分解表，追加 report/accuracy_int8_pc.md
  D:/pytorch/python.exe model/engine_ref.py golden         # sim/golden/n6_engine/
  D:/pytorch/python.exe model/engine_ref.py golden --num 8 # sim/golden/n6_engine_i8/（--out 另写目录，核对用）
  D:/pytorch/python.exe model/engine_ref.py scan-front     # 前端 g 位宽统计
  D:/pytorch/python.exe model/engine_ref.py int8-selftest  # --num 8 结构自测（PTQ 逐矩阵 2 幂权重）
"""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
from quant import W, J, D  # noqa: E402

N = 6
LAYERS = 12
NCLS_MAX = 24
PATCH_N = 7 * 7 * 270                    # 13230
CUBE_BANDS = 272
LOGIT_FRAC = 16

# ---- 注意力 / 置信度共用的定点 exp（§3.4）
LOG2E_Q24 = 24204406                     # round(log2(e) · 2^24)
T_HI = np.array([int(round(2.0 ** (-a / 256) * (1 << 24))) for a in range(256)], np.int64)
T_LO = np.array([int(round(2.0 ** (-b / 65536) * (1 << 24))) for b in range(256)], np.int64)
EXP_CUT = 25 << 24                       # d ≥ 25（自然对数单位）时 e = 0

# ---- 前端（§3.6），scan_front 统计后定死
FRONT_S = 43                             # 三景全部像素 sqrt(V) ∈ [3.83e5, 6.33e7] → g ∈ [2^17.1, 2^24.45]，25 位内留 1.46 倍余量
FRONT_T = FRONT_S - 24
GMAX = (1 << 25) - 1
GC = np.float32(np.sqrt((PATCH_N - 1) / PATCH_N) * 2.0 ** FRONT_S)

# ---- 前端 bfp（契约 v3，09-24 用户定）：立方体每条光谱一个 2 幂指数 e（存填充波段 270），窗内对齐到最小指数
BFP_EMAX = 15
BFP_S = 48                               # 对齐后 sqrt(V) 范围窄：三景回归像素 g(S=43) ∈ [2^15.2, 2^19.3] → S=48 得 [2^20.2, 2^24.3]
BFP_T = BFP_S - 24
BFP_GC = np.float32(np.sqrt((PATCH_N - 1) / PATCH_N) * 2.0 ** BFP_S)

class Cfg:
    """num=16：W16A18；num=8：W8A8；num=8 + mix：方案 C（09-26 实测中，未进契约）——投影核 W8A8（入口 / 模 1、2 / 出口 Q3.4），
    残差流、注意力输出、前端、分类头同 int16 版 Q5.12/18。PF / PB 为投影入口与出口格式，非 mix 时等于 DF / DB。"""

    def __init__(self, num=16, mix=False):
        self.num, self.mix = num, mix
        if num == 16:
            self.DF, self.DB, self.MF, self.MB, self.WF = 12, 18, 14, 18, 14
        elif num == 8:
            self.DF, self.DB, self.MF, self.MB, self.WF = 4, 8, 4, 8, None   # 因子逐矩阵 2 幂
        else:
            raise ValueError(num)
        self.PF, self.PB = self.DF, self.DB
        if mix:
            assert num == 8
            self.DF, self.DB = 12, 18
        self.INV_C = np.float32(np.sqrt(D * (D - 1)) * 2.0 ** self.DF)    # num16: 10835968.0f（同 v1.4）


def sat(v, bits):
    lim = 1 << (bits - 1)
    return np.clip(v, -lim, lim - 1)


def rshift_rnd(v, s):
    """(v + 2^(s-1)) >> s，算术右移 = floor（AP_RND）。"""
    return (v + (1 << (s - 1))) >> s if s > 0 else v << (-s)


def tdiv(a, b):
    """C 语义的整数除法（向零截断）。"""
    q = np.abs(a) // b
    return np.where(a < 0, -q, q)


# ------------------------------------------------------------------ 算子
def normalize(x, cfg, fmt=None):
    """§3.2：x (D,N) int64 → q (D,N)、mean_q24 (N,)、inv_q24 (N,)。num16 与 tt_ref_int.h::normalize 同算法，输出饱和到 DB 位。
    fmt = (F, B) 为输出格式，默认 (DF, DB)；mix 的投影入口取 (PF, PB)，与 Q5.12 输出出自同一乘积、各舍入一次。"""
    F, B = fmt or (cfg.DF, cfg.DB)
    sh = 24 - cfg.DF
    s1 = x.sum(0)
    sxx = (x * x).sum(0)
    var = D * sxx - s1 * s1
    mean = tdiv(s1 << sh, D)
    with np.errstate(divide='ignore'):
        inv = cfg.INV_C / np.sqrt(var.astype(np.float32))
    inv = np.where(inv <= np.float32(127.0), inv, np.float32(127.0)).astype(np.float32)
    inv_q24 = (inv * np.float32(16777216.0)).astype(np.int64)
    d = (x << sh) - mean
    q = sat(rshift_rnd(d * inv_q24, 48 - F), B)
    return q, mean, inv_q24


def proj(xq, wq, cfg):
    """§3.1：xq (D,N) → (D,N)。wq = (m1, m2, m3, (e1, e2, e3))，因子为 int64 整数矩阵。舍入位置同 v1.4。入口 / 出口格式 PF / PB。"""
    m1, m2, m3, (e1, e2, e3) = wq
    x = xq.T.reshape(N, W, W, J)
    t1 = sat(rshift_rnd(np.einsum('ai,nibj->nabj', m1, x), cfg.PF + e1 - cfg.MF), cfg.MB)
    t2 = sat(rshift_rnd(np.einsum('bi,naij->nabj', m2, t1), e2), cfg.MB)
    y = sat(rshift_rnd(np.einsum('cj,nabj->nabc', m3, t2), cfg.MF + e3 - cfg.PF), cfg.PB)
    return y.reshape(N, D).T.copy()


def exp_q24(d):
    """定点 exp(−d)：d ≥ 0 为 Q.24（int64 数组），返回 Q0.24（≤ 2^24）。"""
    u = np.minimum(d, EXP_CUT) * LOG2E_Q24              # Q.48（log2 单位）；先截到 EXP_CUT 防溢出，截到的项下面置 0
    i = u >> 48
    f = (u >> 32) & 0xFFFF
    e = ((T_HI[f >> 8] * T_LO[f & 255] + (1 << 23)) >> 24) >> i
    return np.where(d >= EXP_CUT, 0, e)


def attention(q, k, v, cfg):
    """§3.4：返回 ctx_q (D,N)、s (N,N)、attn (N,N) Q0.24。V 按内存序切块（原模型语义）。q/k/v 为投影出口格式 PF，ctx_q 为 DF。"""
    s = q.T @ k                                         # Q.(2PF)，精确
    d = (s.max(1, keepdims=True) - s) << (24 - 2 * cfg.PF)
    e = exp_q24(d)
    S = e.sum(1, keepdims=True)
    r = (1 << 47) // S
    attn = (e * r + (1 << 22)) >> 23
    vb = v.reshape(-1).reshape(N, D)                    # 内存序切块
    ctx = (attn @ vb).reshape(D, N)                     # Q.(24+PF)，再按内存序解释回 (p, n)
    return sat(rshift_rnd(ctx, 24 + cfg.PF - cfg.DF), cfg.DB), s, attn


def head(xt, hw, cfg):
    """§3.6 分类头：xt 为 token 1 的 2646 个激活整数。返回 logits Q.16 (ncls,)、label、conf Q0.16。"""
    wq, e, b = hw
    acc = wq @ xt
    r = cfg.DF + e - 16
    assert (r >= 1).all(), f'head shift r < 1: {r}'
    l = np.array([rshift_rnd(int(a), int(s)) for a, s in zip(acc, r)], np.int64) + b
    label = int(np.argmax(l))
    E = exp_q24((l.max() - l) << 8)
    conf = min(0xFFFF, (1 << 40) // int(E.sum()))
    return l, label, conf


# ------------------------------------------------------------------ 权重
def head_int(cw, cb):
    """逐类 2 幂 int16：e_c = floor(log2(32767 / max|W_c|))，使 max|W_c|·2^e ∈ [2^14, 2^15)。偏置 Q.16。"""
    e = np.floor(np.log2(32767.0 / np.abs(cw).max(1))).astype(np.int64)
    wq = np.clip(np.floor(cw * np.exp2(e)[:, None] + 0.5), -32768, 32767).astype(np.int64)
    b = np.floor(cb * 65536.0 + 0.5).astype(np.int64)
    return wq, e, b


class Engine:
    """一个 checkpoint 的整数权重 + 前向。net = fixed_point_sim.Net（只取 float 参数）。"""

    def __init__(self, ckpt=None, ncls=None, num=16, name='unoverlapping', mix=False):
        from fixed_point_sim import Net
        from quant import Fmt, pack_factors
        self.cfg = cfg = Cfg(num, mix)
        self.net = net = Net(name, Fmt(DF=12, WF=14, MF=14), ckpt=ckpt, classes=ncls)
        self.ncls = net.cw.shape[0]
        self.wp = []                                    # [layer][proj] = (m1, m2, m3, (e1, e2, e3))
        self.wexp = []
        for L in net.layers:
            row = []
            for nm in ('query', 'key', 'value', 'mlp'):
                if num == 16:
                    q = pack_factors(*L[nm]['f']).astype(np.int64)
                    row.append((q[:49].reshape(W, W), q[49:98].reshape(W, W), q[98:].reshape(J, J), (14, 14, 14)))
                else:
                    ex = [int(np.floor(np.log2(127.0 / np.abs(m).max()))) for m in L[nm]['f']]
                    ms = [np.clip(np.floor(m * 2.0 ** s + 0.5), -127, 127).astype(np.int64) for m, s in zip(L[nm]['f'], ex)]
                    row.append((ms[0], ms[1], ms[2], tuple(ex)))
            self.wp.append(row)
        # EMB：int32 Q.24，(p, n)；n = 0 为 cls + pos，n ≥ 1 为 pos
        pos = net.pos.reshape(D, N).copy()
        pos[:, 0] += net.cls.reshape(D)
        self.emb = np.floor(pos * (1 << 24) + 0.5).astype(np.int64)
        assert np.abs(self.emb).max() < 2 ** 31
        self.hw = head_int(net.cw, net.cb)

    # ---- 入口
    def entry_a(self, x_in16):
        """int16 Q3.12 块 (D,N) → 片上激活。num16 / mix 符号扩展；num8 装载时舍入到 Q3.4。"""
        x = np.asarray(x_in16, np.int64)
        return sat(rshift_rnd(x, 12 - self.cfg.DF), self.cfg.DB)

    def entry_b(self, win, trace=None, bfp=None):
        """win：(7,7,272) int16 立方体窗（填充坐标 [r:r+7, c:c+7]）→ x_embed (D,N)。
        bfp=True：波段 270 为每条光谱的指数 e，元素先按 (e − min e) 右移舍入对齐，再走同一前端（常数 BFP_S）。"""
        cfg = self.cfg
        w = np.asarray(win, np.int64)
        if bfp is None:
            bfp = CUBE_RULE == 'bfp'
        if bfp:
            e = w[:, :, 270]
            sh = (e - e.min())[:, :, None]
            v = w[:, :, :270]
            w = np.where(sh > 0, (v + np.left_shift(1, np.maximum(sh - 1, 0))) >> sh, v)
            gc, gt = BFP_GC, BFP_T
        else:
            w = w[:, :, :270]
            gc, gt = GC, FRONT_T
        q = np.ascontiguousarray(w.transpose(2, 0, 1)).reshape(-1)   # e = c·49 + h·7 + w
        s1 = int(q.sum()); sxx = int((q * q).sum())
        V = PATCH_N * sxx - s1 * s1
        with np.errstate(divide='ignore'):
            gf = gc / np.sqrt(np.array(V, np.int64).astype(np.float32))    # int64 → float32 单次舍入（同 C 的 (float)V）
        gf = gf if gf <= np.float32(GMAX) else np.float32(GMAX)
        g = int(gf)
        d = PATCH_N * q - s1
        xn = (d * g) >> gt                               # Q.24
        sh = 24 - cfg.DF
        x = np.empty((D, N), np.int64)
        x[:, 0] = self.emb[:, 0]
        x[:, 1:] = xn.reshape(D, N - 1) + self.emb[:, 1:]      # e = 5p + (n−1)
        x = sat(rshift_rnd(x, sh), cfg.DB)
        if trace is not None:
            trace.update(S1=s1, Sxx=sxx, V=V, g=g, xn24=xn)
        return x

    # ---- 12 层 + 分类头
    def forward(self, x, trace=None):
        cfg = self.cfg
        pfmt = (cfg.PF, cfg.PB)
        for li in range(LAYERS):
            xn, m1, i1 = normalize(x, cfg)
            xp = normalize(x, cfg, pfmt)[0] if cfg.mix else xn
            qkv = [proj(xp, self.wp[li][j], cfg) for j in range(3)]
            ctx, s, attn = attention(*qkv, cfg)
            xm = sat(xn + ctx, cfg.DB)
            xn2, m2, i2 = normalize(xm, cfg)
            xp2 = normalize(xm, cfg, pfmt)[0] if cfg.mix else xn2
            m = proj(xp2, self.wp[li][3], cfg)
            x = sat(xn2 + (m << (cfg.DF - cfg.PF)), cfg.DB)
            if trace is not None:
                trace.append(dict(xn_q=xn, stats_qkv=np.stack([m1, i1], 1), q=qkv[0], k=qkv[1], v=qkv[2], s=s, attn=attn,
                                  x_mid=xm, xn2_q=xn2, stats_mlp=np.stack([m2, i2], 1), m=m, x_out=x))
        l, label, conf = head(x[:, 1], self.hw, cfg)
        return dict(logits=l, label=label, conf=conf, x=x)

    # ---- 分项误差用的浮点混合路径（其余部分全浮点，只把一个部件换成整数）
    def float_forward(self, patch, x0=None, attn_int=False, head_int_=False):
        from fixed_point_sim import normalize_np, attention_np
        from quant import tucker_proj_float
        cfg, net = self.cfg, self.net
        sc = float(1 << cfg.DF)
        x = net.embed(patch) if x0 is None else x0.T.reshape(N, W, W, J) / sc
        for L in net.layers:
            xn = normalize_np(x)
            q, k, v = (tucker_proj_float(xn, *L[nm]['f']) for nm in ('query', 'key', 'value'))
            if attn_int:
                qi, ki, vi = (sat(np.floor(t.reshape(N, D).T * sc + 0.5).astype(np.int64), cfg.DB) for t in (q, k, v))
                ctx = attention(qi, ki, vi, cfg)[0].T.reshape(N, W, W, J) / sc
            else:
                ctx = attention_np(q, k, v)
            xn2 = normalize_np(xn + ctx)
            x = xn2 + tucker_proj_float(xn2, *L['mlp']['f'])
        if head_int_:
            xt = sat(np.floor(x[1].reshape(-1) * sc + 0.5).astype(np.int64), cfg.DB)
            return head(xt, self.hw, cfg)[0] / 65536.0
        return net.cw @ x[1].reshape(-1) + net.cb

    # ---- int8 版误差分解（num=8）：torch 假量化前向（qat.py）的 numpy 版，parts 里的部件换成整数契约（§3.7）
    def fq_forward(self, patch, win=None, parts=''):
        """基准（parts=''）：只有投影入口、模 1/2/3 之后是 Q3.4，其余浮点，与 qat.enable 后的 torch 前向同义（投影部分逐位）。
        F 前端出 Q3.4（entry_b）；N 残差用归一化输出的 Q3.4 值（与投影入口同一个值）；A 整数注意力（ctx Q3.4）；
        R 残差和饱和到 Q3.4 范围；H 整数分类头。'FNARH' 与 forward 只差归一化的算术（float64 对整数）。"""
        from fixed_point_sim import normalize_np, attention_np
        cfg, net = self.cfg, self.net
        sc = float(1 << cfg.DF)
        lo, hi = -(1 << (cfg.DB - 1)) / sc, ((1 << (cfg.DB - 1)) - 1) / sc
        qz = lambda t: sat(np.floor(t * sc + 0.5).astype(np.int64), cfg.DB)
        blk = lambda t: t.reshape(N, D).T
        unb = lambda b: b.T.reshape(N, W, W, J)
        x = unb(self.entry_b(win, None, True)) / sc if 'F' in parts else net.embed(patch)
        for li in range(LAYERS):
            xn = normalize_np(x)
            xq = qz(xn)
            q, k, v = (proj(blk(xq), self.wp[li][j], cfg) for j in range(3))
            ctx = unb(attention(q, k, v, cfg)[0]) / sc if 'A' in parts else attention_np(unb(q) / sc, unb(k) / sc, unb(v) / sc)
            xm = (xq / sc if 'N' in parts else xn) + ctx
            if 'R' in parts:
                xm = np.clip(xm, lo, hi)
            xn2 = normalize_np(xm)
            x2q = qz(xn2)
            x = (x2q / sc if 'N' in parts else xn2) + unb(proj(blk(x2q), self.wp[li][3], cfg)) / sc
            if 'R' in parts:
                x = np.clip(x, lo, hi)
        if 'H' in parts:
            return head(qz(x[1]).reshape(-1), self.hw, cfg)[0] / 65536.0
        return net.cw @ x[1].reshape(-1) + net.cb


def ps_embed_q312(net, patch):
    """M3a 的块输入：与 tt_net.cpp::tt_embed 同义（float32 相加，乘 4096 后就近偶数舍入，饱和 int16）。返回 (D,N) int64 与饱和数。"""
    p32 = patch.astype(np.float32).reshape(D, N - 1)
    t = np.empty((D, N), np.float32)
    t[:, 0] = net.cls.reshape(D).astype(np.float32) + net.pos.reshape(D, N)[:, 0].astype(np.float32)
    t[:, 1:] = p32 + net.pos.reshape(D, N)[:, 1:].astype(np.float32)
    v = np.rint(t * np.float32(4096.0)).astype(np.int64)
    return np.clip(v, -32768, 32767), int(((v > 32767) | (v < -32768)).sum())


# ------------------------------------------------------------------ 立方体 int16
SAT_FRAC = 1e-5                          # 'sat' 规则允许的饱和元素比例


def cube_scale(cube32, rule='max'):
    """每景一个 2 的幂 k。'max'（契约 §3.6 原文）：k = floor(log2(32767 / max|x|))，不饱和；
    'sat'（D3 提议）：满足 |x|·2^k ≥ 32767.5 的元素比例 ≤ SAT_FRAC 的最大 k（离群亮点饱和，其余像素多几位精度）；
    'bfp'：没有整景 k，返回 None（每条光谱各自的指数，见 cube_to_i16）。"""
    if rule == 'bfp':
        return None
    Hp = cube32.shape[0]
    mx = 0.0
    for r0 in range(0, Hp, 64):
        mx = max(mx, float(np.abs(cube32[r0:r0 + 64]).max()))
    k0 = int(np.floor(np.log2(32767.0 / mx)))
    if rule == 'max':
        return k0
    cnt = np.zeros(8, np.int64)
    for r0 in range(0, Hp, 64):
        a = np.abs(cube32[r0:r0 + 64]).astype(np.float64)
        for j in range(8):
            cnt[j] += int((a * 2.0 ** (k0 + 1 + j) >= 32767.5).sum())
    tot = cube32.size
    k = k0
    for j in range(8):
        if cnt[j] / tot <= SAT_FRAC:
            k = k0 + 1 + j
        else:
            break
    return k


def cube_to_i16(cube32, k):
    """(Hp, Wp, 270) float32 → (Hp, Wp, 272) int16，q = sat16(floor(x·2^k + 0.5))，波段 270、271 为 0。
    k=None（bfp）：每条光谱 e = min(BFP_EMAX, floor(log2(32767 / max|x|)))（全零光谱 BFP_EMAX），q = floor(x·2^e + 0.5)，e 存波段 270。"""
    Hp, Wp, _ = cube32.shape
    out = np.zeros((Hp, Wp, CUBE_BANDS), '<i2')
    for r0 in range(0, Hp, 64):
        blk = cube32[r0:r0 + 64].astype(np.float64)
        if k is None:
            m = np.abs(blk).max(-1)
            with np.errstate(divide='ignore'):
                e = np.where(m > 0, np.floor(np.log2(32767.0 / np.where(m > 0, m, 1.0))), BFP_EMAX)
            e = np.minimum(e, BFP_EMAX)
            out[r0:r0 + 64, :, :270] = np.floor(blk * np.exp2(e)[..., None] + 0.5)
            out[r0:r0 + 64, :, 270] = e
        else:
            out[r0:r0 + 64, :, :270] = np.clip(np.floor(blk * 2.0 ** k + 0.5), -32768, 32767)
    return out


CUBE_RULE = 'bfp'                        # 契约 v3（09-24 用户定）；'max' / 'sat' 为 v2 整景 k，只留作对照（HanChuan 离群亮点使整景 k 不够用，见 sim/tolerance.md）


def scene_cube(scene, rule=None):
    """返回 (cube_f32 memmap, cube_i16, k, ncls)。cube_i16.bin 存在且 meta 的 cube_k 与本规则的 k 相同时直接 memmap，否则内存里现算。"""
    from scenes import SCENES
    from preprocess import HALF
    rule = rule or CUBE_RULE
    meta = dict(l.split('=', 1) for l in (ROOT / 'data/scenes' / scene / 'meta.txt').read_text(encoding='utf-8').split('\n') if '=' in l)
    H, Wd = int(meta['H']), int(meta['W'])
    shape = (H + 2 * HALF, Wd + 2 * HALF, 270)
    c32 = np.memmap(ROOT / 'data/scenes' / scene / 'cube_f32.bin', dtype='<f4', mode='r', shape=shape)
    i16p = ROOT / 'data/scenes' / scene / 'cube_i16.bin'
    k = cube_scale(c32, rule)
    kstr = 'bfp' if k is None else str(k)
    if i16p.exists() and meta.get('cube_k') == kstr and i16p.stat().st_size == shape[0] * shape[1] * CUBE_PIX_BYTES:
        c16 = np.memmap(i16p, dtype='<i2', mode='r', shape=(shape[0], shape[1], CUBE_BANDS))
    else:
        c16 = cube_to_i16(c32, k)
    return c32, c16, k, len(SCENES[scene]['classes'])


CUBE_PIX_BYTES = 544


# ------------------------------------------------------------------ 前端统计：定 FRONT_S / GMAX
def scan_front(scenes_):
    rows = []
    for sc in scenes_:
        c32, c16, k, _ = scene_cube(sc)
        Hp, Wp, _ = c16.shape
        b1 = np.zeros((Hp, Wp), np.int64); b2 = np.zeros((Hp, Wp), np.int64)
        for r0 in range(0, Hp, 64):
            blk = np.asarray(c16[r0:r0 + 64, :, :270], np.int64)
            b1[r0:r0 + 64] = blk.sum(2); b2[r0:r0 + 64] = (blk * blk).sum(2)

        def box(a):
            c = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
            return c[7:, 7:] - c[:-7, 7:] - c[7:, :-7] + c[:-7, :-7]
        S1, Sxx = box(b1), box(b2)
        V = PATCH_N * Sxx - S1 * S1
        sq = np.sqrt(V.astype(np.float64))
        g = np.sqrt((PATCH_N - 1) / PATCH_N) * 2.0 ** FRONT_S / sq
        dmax = PATCH_N * 32767 + np.abs(S1).max()
        rows.append(dict(scene=sc, k=k, pixels=int(V.size), maxabs_x=float(np.abs(c32).max()),
                         sqrtV_min=float(sq.min()), sqrtV_max=float(sq.max()),
                         g_max=float(g.max()), g_min=float(g.min()), g_bits=float(np.log2(g.max())),
                         g_min_bits=float(np.log2(g.min())), Sxx_bits=float(np.log2(Sxx.max())), V_bits=float(np.log2(V.max())),
                         dg_bits=float(np.log2(dmax * g.max()))))
        print(json.dumps(rows[-1]), flush=True)
    return rows


# ------------------------------------------------------------------ 回归（三景 fixed_regression 同批像素）
_E = _C16 = _C32 = None
_BFP = False


def _init(ckpt, ncls, scene, rule):
    global _E, _C16, _C32, _BFP
    import torch
    torch.set_num_threads(1)
    _E = Engine(ckpt, ncls)
    _C32, _C16, _, _ = scene_cube(scene, rule)
    _BFP = rule == 'bfp'


def _one(rc):
    import preprocess
    r, c = rc
    E = _E
    patch = preprocess.patch_tensor(_C32, r, c).astype(np.float64)
    tr = {}
    xb = E.entry_b(np.asarray(_C16[r:r + 7, c:c + 7]), tr, _BFP)
    ob = E.forward(xb)
    xa16, nsat = ps_embed_q312(E.net, patch)
    oa = E.forward(E.entry_a(xa16))
    lf_front = E.float_forward(patch, x0=xb)
    lf_attn = E.float_forward(patch, attn_int=True)
    lf_head = E.float_forward(patch, head_int_=True)
    return (ob['logits'] / 65536.0, ob['label'], ob['conf'], oa['logits'] / 65536.0, oa['label'], oa['conf'], nsat,
            lf_front, lf_attn, lf_head, tr['g'])


def regress(scenes_, workers, rule='max'):
    from multiprocessing import Pool
    rep = ROOT / 'report' / 'accuracy_fixed_pc.md'
    out = []
    for sc in scenes_:
        z = np.load(ROOT / 'data/regress' / f'{sc}_unoverlapping_{sc}_unoverlapping_s0.npz')
        coords, gt = z['coords'], z['gt'].astype(np.int64)
        lf = z['logits_float'].astype(np.float64)
        ckpt = ROOT / 'data/ckpt' / f'{sc}_unoverlapping_s0.pth'
        from scenes import SCENES
        ncls = len(SCENES[sc]['classes'])
        t0 = time.time()
        with Pool(workers, initializer=_init, initargs=(str(ckpt), ncls, sc, rule)) as p:
            res = p.map(_one, [tuple(x) for x in coords], chunksize=8)
        pf = lf.argmax(1)
        sm = np.exp(lf - lf.max(1, keepdims=True)); sm = sm.max(1) / sm.sum(1)

        def stat(lx, conf=None):
            d = np.abs(lx - lf)
            s = dict(agree=float(np.mean(lx.argmax(1) == pf)), mism=int(np.sum(lx.argmax(1) != pf)),
                     oa=float(np.mean(lx.argmax(1) + 1 == gt)), max=float(d.max()), mean=float(d.mean()))
            if conf is not None:
                s['conf_max_err'] = float(np.abs(conf / 65536.0 - sm).max())
            return s
        lb = np.stack([r[0] for r in res]); la = np.stack([r[3] for r in res])
        # 整数路径的 label 必须等于 logits 的 argmax（并列取小下标）
        assert all(r[1] == int(np.argmax(r[0])) for r in res)
        rows = {'M3b 入口 B（全整数）': stat(lb, np.array([r[2] for r in res])),
                'M3a 入口 A（全整数）': stat(la, np.array([r[5] for r in res])),
                '只前端整数': stat(np.stack([r[7] for r in res])),
                '只注意力整数': stat(np.stack([r[8] for r in res])),
                '只分类头整数': stat(np.stack([r[9] for r in res]))}
        g = np.array([r[10] for r in res])
        info = dict(scene=sc, pixels=len(coords), OA_float=float(np.mean(pf + 1 == gt)), rows=rows,
                    m3a_sat_pixels=int(sum(r[6] > 0 for r in res)), m3a_sat_elems=int(sum(r[6] for r in res)),
                    cube_k=scene_cube(sc, rule)[2], g_min=int(g.min()), g_max=int(g.max()), seconds=int(time.time() - t0))
        print(json.dumps(info, ensure_ascii=False), flush=True)
        out.append(info)
        np.savez(ROOT / 'data/regress' / f'engine_ref_{sc}_k{rule}.npz', coords=coords, logits_b=lb.astype(np.float32),
                 logits_a=la.astype(np.float32), conf_b=np.array([r[2] for r in res]), conf_a=np.array([r[5] for r in res]))
        with rep.open('a', encoding='utf-8') as f:
            if not any('参考版本' in l for l in rep.read_text(encoding='utf-8').splitlines()):
                pass
            f.write(_rep_rows(sc, ncls, info, 'v3 bfp（最终）' if rule == 'bfp' else f'v2 k={info["cube_k"]}（{rule}）'))
    return out


# ------------------------------------------------------------------ int8 回归：整数参考（QAT 权重）对 torch 假量化前向
PARTS8 = ('', 'F', 'N', 'A', 'R', 'H', 'FNARH')
_E16 = _Q = _QF = None


def qat8_ckpt(scene):
    return ROOT / 'data/ckpt' / f'{scene}_qat8_s0.pth'


def _init8(scene):
    global _E, _E16, _C16, _C32, _Q, _QF
    import torch
    import qat
    import tt_model
    from scenes import SCENES
    torch.set_num_threads(1)
    ncls = len(SCENES[scene]['classes'])
    _E = Engine(str(qat8_ckpt(scene)), ncls, num=8)
    _E16 = Engine(str(ROOT / 'data/ckpt' / f'{scene}_unoverlapping_s0.pth'), ncls)
    _C32, _C16, _, _ = scene_cube(scene)
    _Q = qat.enable(tt_model.load('unoverlapping', qat8_ckpt(scene), ncls).double())      # 假量化前向，float64（同 qat_eval）
    _QF = tt_model.load('unoverlapping', qat8_ckpt(scene), ncls).double()                  # QAT 模型自己的浮点路径


def _one8(rc):
    import preprocess
    import torch
    r, c = rc
    patch = preprocess.patch_tensor(_C32, r, c).astype(np.float64)
    win = np.asarray(_C16[r:r + 7, c:c + 7])
    o = _E.forward(_E.entry_b(win, None, True))
    o16 = _E16.forward(_E16.entry_b(win, None, True))
    with torch.no_grad():
        t = torch.from_numpy(patch)[None]
        lfq, lqf = _Q(t).numpy()[0], _QF(t).numpy()[0]
    hy = [_E.fq_forward(patch, win, p) for p in PARTS8]
    return o['logits'] / 65536.0, o['label'], o['conf'], o16['logits'] / 65536.0, lfq, lqf, hy


def regress8(scenes_, workers, limit=0):
    """三景回归像素（regress 同批）：int8 整数参考（入口 B，QAT 权重）对 torch 假量化前向；int16 整数参考对浮点模型作参照；
    PARTS8 逐部件换整数定位差异来源。并列 = 参考 logits 前两名差 < 0.01。结果 build/host/int8_ref/engine_ref_i8_<scene>.npz。"""
    from multiprocessing import Pool
    od = ROOT / 'build/host/int8_ref'
    od.mkdir(parents=True, exist_ok=True)
    out = []
    for sc in scenes_:
        z = np.load(ROOT / 'data/regress' / f'{sc}_unoverlapping_{sc}_unoverlapping_s0.npz')
        coords, gt = z['coords'], z['gt'].astype(np.int64)
        lf = z['logits_float'].astype(np.float64)
        if limit:
            coords, gt, lf = coords[:limit], gt[:limit], lf[:limit]
        t0 = time.time()
        with Pool(workers, initializer=_init8, initargs=(sc,)) as p:
            res = p.map(_one8, [tuple(x) for x in coords], chunksize=8)
        li8 = np.stack([r[0] for r in res]); l16 = np.stack([r[3] for r in res])
        lfq = np.stack([r[4] for r in res]); lqf = np.stack([r[5] for r in res])
        hy = np.stack([np.stack(r[6]) for r in res])                       # (pixels, parts, ncls)
        assert all(r[1] == int(np.argmax(r[0])) for r in res)

        def gap(l):
            s = np.sort(l, 1)
            return s[:, -1] - s[:, -2]

        def stat(lx, ref, tie):
            mis = lx.argmax(1) != ref.argmax(1)
            d = np.abs(lx - ref)
            return dict(agree=float(1 - mis.mean()), mism=int(mis.sum()), mism_tie=int((mis & tie).sum()),
                        max=float(d.max()), mean=float(d.mean()), oa=float(np.mean(lx.argmax(1) + 1 == gt)))
        tq, tf = gap(lfq) < 0.01, gap(lf) < 0.01
        sm = np.exp(lfq - lfq.max(1, keepdims=True)); sm = sm.max(1) / sm.sum(1)
        rows = {'int8 engine_ref 入口 B（全整数）': stat(li8, lfq, tq)}
        rows['int8 engine_ref 入口 B（全整数）']['conf_max_err'] = float(np.abs(np.array([r[2] for r in res]) / 65536.0 - sm).max())
        for i, pt in enumerate(PARTS8):
            rows[f'numpy 假量化 + {pt or "无"}'] = stat(hy[:, i], lfq, tq)
        rows['QAT 模型浮点路径'] = stat(lqf, lfq, tq)
        info = dict(scene=sc, pixels=len(coords), OA_fq=float(np.mean(lfq.argmax(1) + 1 == gt)), ties_fq=int(tq.sum()),
                    rows=rows, int16=stat(l16, lf, tf), ties_float=int(tf.sum()), OA_float_s0=float(np.mean(lf.argmax(1) + 1 == gt)),
                    seconds=int(time.time() - t0))
        print(json.dumps(info, ensure_ascii=False), flush=True)
        out.append(info)
        np.savez(od / f'engine_ref_i8_{sc}{"_lim%d" % limit if limit else ""}.npz', coords=coords, gt=gt, logits_i8=li8.astype(np.float32),
                 label_i8=np.array([r[1] for r in res]), conf_i8=np.array([r[2] for r in res]), logits_i16=l16.astype(np.float32),
                 logits_fq=lfq, logits_qatfloat=lqf, logits_float_s0=lf, hybrids=hy, parts=np.array(PARTS8))
    if not limit:
        report8(scenes_)
    return out


REP8_HEAD = ('\n## int8 整数参考对 torch 假量化前向：逐部件分解（model/engine_ref.py regress --num 8）\n\n'
             '由 engine_ref.py regress --num 8 追加（`report8` 可从 build/host/int8_ref/engine_ref_i8_<景>.npz 重算），勿手改。'
             '像素 = fixed_regression 同批回归像素（每类 ≤100，样本 OA 只看相对差）。对照 = 同一 QAT checkpoint 的 torch 假量化前向（qat.py，float64）；'
             '"假量化 + X" = numpy 复刻的假量化前向里只把部件 X 换成整数契约：F 前端输出 Q3.4、N 残差用量化后的 xn、A 整数注意力（ctx Q3.4）、'
             'R 残差和饱和到 Q3.4、H 整数分类头；FNARH 与整数引擎只差归一化的算术。并列 = 对照前两名 logit 差 < 0.01。'
             '每景末行是 int16 整数引擎对 s0 浮点模型（参照）。\n\n'
             '| 日期 | 景 | 像素 | 路径 | 标签一致率 | 不一致（其中并列） | max\\|dlogit\\| | mean\\|dlogit\\| | 样本 OA |\n'
             '|---|---|---|---|---|---|---|---|---|\n')


def report8(scenes_):
    rep = ROOT / 'report' / 'accuracy_int8_pc.md'
    s = '' if '逐部件分解' in rep.read_text(encoding='utf-8') else REP8_HEAD
    for sc in scenes_:
        z = np.load(ROOT / 'build/host/int8_ref' / f'engine_ref_i8_{sc}.npz')
        gt = z['gt']

        def row(name, lx, ref):
            srt = np.sort(ref, 1)
            mis = lx.argmax(1) != ref.argmax(1)
            d = np.abs(lx - ref)
            return (f"| {time.strftime('%Y-%m-%d')} | {sc} | {len(gt)} | {name} | {1 - mis.mean():.4f} | {int(mis.sum())}（"
                    f"{int((mis & (srt[:, -1] - srt[:, -2] < 0.01)).sum())}） | {d.max():.3f} | {d.mean():.4f} | {np.mean(lx.argmax(1) + 1 == gt):.4f} |\n")
        fq = z['logits_fq']
        s += row('torch 假量化前向（对照本身）', fq, fq)
        s += row('int8 整数引擎（入口 B，全整数）', z['logits_i8'].astype(np.float64), fq)
        for i, p in enumerate(z['parts']):
            s += row(f'假量化 + {p or "无（numpy 复刻）"}', z['hybrids'][:, i], fq)
        s += row('QAT 模型浮点路径', z['logits_qatfloat'], fq)
        s += row('int16 整数引擎 对 s0 浮点（参照）', z['logits_i16'].astype(np.float64), z['logits_float_s0'])
    with rep.open('a', encoding='utf-8') as f:
        f.write(s)


REP_HEAD = ('\n## engine_ref（M3 整数参考，docs/engine_arch.md §3；W16A18）\n\n'
            '由 model/engine_ref.py regress 追加，勿手改。同一批像素、同一 checkpoint，对全浮点路径比；'
            '"只 X 整数" = 其余部分全浮点、只把该部件换成整数定义，用来单列各部件误差。置信度误差 = |conf − 浮点 softmax 最大值|。\n\n'
            '| 日期 | 景 | 类别 | 抽样像素 | 参考版本 | OA float | OA 参考 | 标签一致率 | 不一致数 | max\\|dlogit\\| | mean\\|dlogit\\| | max 置信度误差 |\n'
            '|---|---|---|---|---|---|---|---|---|---|---|---|\n')


def _rep_rows(sc, ncls, info, tag):
    s = ''
    for name, r in info['rows'].items():
        s += (f"| {time.strftime('%Y-%m-%d')} | {sc} | {ncls} | {info['pixels']} | engine_ref {tag} {name} | {info['OA_float']:.4f} | "
              f"{r['oa']:.4f} | {r['agree']:.4f} | {r['mism']} | {r['max']:.4f} | {r['mean']:.5f} | "
              f"{r['conf_max_err']:.5f} |\n" if 'conf_max_err' in r else
              f"| {time.strftime('%Y-%m-%d')} | {sc} | {ncls} | {info['pixels']} | engine_ref {tag} {name} | {info['OA_float']:.4f} | "
              f"{r['oa']:.4f} | {r['agree']:.4f} | {r['mism']} | {r['max']:.4f} | {r['mean']:.5f} | — |\n")
    return s


# ------------------------------------------------------------------ 黄金向量 sim/golden/n6_engine/（int8：n6_engine_i8/）
def write_golden(num=16, out=None):
    import preprocess
    from export_scene import engine_package
    out = Path(out) if out else ROOT / 'sim/golden' / ('n6_engine' if num == 16 else 'n6_engine_i8')
    out.mkdir(parents=True, exist_ok=True)
    for f in out.rglob('*.bin'):
        f.unlink()
    # int16：LongKou 上游权重 = n6_real 同一套（model/data v1）；int8：LongKou QAT 权重（v2_int8，自训 s0 续训）
    E = Engine() if num == 16 else Engine(str(qat8_ckpt('longkou')), 9, num=8)
    r, c = 20, 20                                       # 与 model/data/golden/meta.txt 同一像素
    c32, c16, k, _ = scene_cube('longkou')
    patch = np.fromfile(ROOT / 'model/data/golden/patch_f32.bin', '<f4')
    assert np.array_equal(preprocess.patch_tensor(c32, r, c).reshape(-1), patch), 'golden pixel mismatch'
    engine_package(E).tofile(out / 'weights_engine.bin')
    xa16, _ = ps_embed_q312(E.net, patch.astype(np.float64))
    if num == 16:
        x_in = np.fromfile(ROOT / 'sim/golden/n6_real/x_embed_i16.bin', '<i2').astype(np.int64).reshape(D, N)
        assert np.array_equal(xa16, x_in), 'ps_embed_q312 != tt_embed (n6_real/x_embed_i16.bin)'
    else:
        x_in = xa16                                     # QAT 权重的 cls/pos 与 n6_real 不同，入口 A 的块按 tt_embed 同一定义现算
    win = np.asarray(c16[r:r + 7, c:c + 7]).astype('<i2')
    win.tofile(out / 'cube_win_i16.bin')
    summary = {}
    for ent in ('a', 'b'):
        d = out / ent
        d.mkdir(exist_ok=True)
        ftr = {}
        x0 = E.entry_a(x_in) if ent == 'a' else E.entry_b(win, ftr)
        if ent == 'a':
            x_in.astype('<i2').tofile(d / 'x_in_i16.bin')
        else:
            np.array([ftr['S1'], ftr['Sxx'], ftr['V'], ftr['g']], '<i8').tofile(d / 'front_s1_sxx_v_g_i64.bin')
            ftr['xn24'].astype('<i4').tofile(d / 'front_xn24_i32.bin')
        x0.astype('<i4').tofile(d / 'x_embed_i32.bin')
        tr = []
        o = E.forward(x0, tr)
        for l, t in enumerate(tr):
            for key, v in t.items():
                dt = '<i8' if key == 's' else '<i4'
                np.asarray(v).astype(dt).tofile(d / f'L{l}_{key}_{dt[1:]}.bin')
        logits = np.zeros(32, '<i4'); logits[:E.ncls] = o['logits']
        logits.tofile(d / 'logits_q16_i32.bin')
        np.array([(o['conf'] << 16) | o['label']], '<u4').tofile(d / 'class_u32.bin')
        summary[ent] = dict(label=o['label'], conf=o['conf'], logits=(o['logits'] / 65536.0).round(5).tolist())
    es = sorted(set(win[:, :, 270].reshape(-1).tolist()))
    if num == 16:
        lf = np.fromfile(ROOT / 'model/data/golden/logits_float.bin', '<f8')
        (out / 'meta.txt').write_text(
            f'pixel=20,20 (LongKou, 上游权重 v1，同 n6_real)\ncube=bfp（契约 v3，波段 270 = 光谱指数 e ∈ {es}）\n'
            f'num=16 DF=12 DB=18 MF=14 MB=18 WF=14\nFRONT_S={BFP_S} FRONT_T={BFP_T} GMAX={GMAX} GC={float(BFP_GC)!r}\n'
            f'a={json.dumps(summary["a"])}\nb={json.dumps(summary["b"])}\nfloat={json.dumps(lf.round(5).tolist())}\n'
            '文件：cube_win_i16.bin (7,7,272) int16；weights_engine.bin；a/ 入口 A，b/ 入口 B；'
            '每层 L<l>_<量>：块 (p,n) 内存序 int32，s 为 (6,6) int64，attn (6,6) int32 Q0.24，stats (6,2) {mean_q24, inv_q24}；'
            'logits_q16_i32.bin 32 槽；class_u32.bin {conf<<16 | label}\n', encoding='utf-8')
    else:
        import torch
        import qat
        import tt_model
        with torch.no_grad():
            t = torch.from_numpy(patch.astype(np.float64).reshape(270, 7, 7))[None]
            lfq = qat.enable(tt_model.load('unoverlapping', qat8_ckpt('longkou'), 9).double())(t).numpy()[0]
            lqf = tt_model.load('unoverlapping', qat8_ckpt('longkou'), 9).double()(t).numpy()[0]
        ex = np.array([x for row in E.wp for w in row for x in w[3]])
        (out / 'meta.txt').write_text(
            f'pixel=20,20 (LongKou, QAT 权重 data/ckpt/longkou_qat8_s0.pth = data/scenes/longkou/weights/v2_int8，由自训 s0 续训)\n'
            f'cube=bfp（契约 v3，波段 270 = 光谱指数 e ∈ {es}）\n'
            f'num=8 DF=4 DB=8 MF=4 MB=8 WF=逐矩阵 2 幂（48 投影 × {{e1,e2,e3}} ∈ [{ex.min()}, {ex.max()}]，权重包投影段末 144 B）\n'
            f'FRONT_S={BFP_S} FRONT_T={BFP_T} GMAX={GMAX} GC={float(BFP_GC)!r}（前端与 int16 版相同，x_embed 为 >> 20 的 Q3.4）\n'
            f'a={json.dumps(summary["a"])}\nb={json.dumps(summary["b"])}\n'
            f'fq={json.dumps(lfq.round(5).tolist())}（torch 假量化前向，qat.py，float64；只有投影是 Q3.4，其余浮点，不逐位）\n'
            f'qat_float={json.dumps(lqf.round(5).tolist())}（同一 QAT 模型的浮点路径）\n'
            '文件：结构与 sim/golden/n6_engine 相同。cube_win_i16.bin (7,7,272) int16；weights_engine.bin（int8 版 336,064 B）；'
            'a/ 入口 A（x_in_i16.bin 为 Q3.12 块，装载时舍入到 Q3.4），b/ 入口 B；'
            '每层 L<l>_<量>：块 (p,n) 内存序 int32（值为 Q3.4 整数），s 为 (6,6) int64（Q.8），attn (6,6) int32 Q0.24，stats (6,2) {mean_q24, inv_q24}；'
            'logits_q16_i32.bin 32 槽；class_u32.bin {conf<<16 | label}；batch_hanchuan/ 为 HanChuan QAT 权重（v1_int8）32 像素，像素同 n6_engine/batch_hanchuan\n',
            encoding='utf-8')
    print(json.dumps(summary))
    write_batch('hanchuan', 32, out, num)


def write_batch(scene, n, out=None, num=16):
    """批向量（C 参考 / csim 对整条链逐位用）：回归像素里随机取 n 个（HanChuan 含饱和像素），入口 B，只存 logits 与类别字。
    立方体窗按 v3 bfp 从 cube_f32 现算（与 cube_i16.bin 同义）。num=8 用该景 QAT 权重。"""
    from export_scene import engine_package
    from scenes import SCENES
    d = (Path(out) if out else ROOT / 'sim/golden/n6_engine') / f'batch_{scene}'
    d.mkdir(parents=True, exist_ok=True)
    ncls = len(SCENES[scene]['classes'])
    E = Engine(str(ROOT / 'data/ckpt' / f'{scene}_unoverlapping_s0.pth'), ncls) if num == 16 else Engine(str(qat8_ckpt(scene)), ncls, num=8)
    engine_package(E).tofile(d / 'weights_engine.bin')
    z = np.load(ROOT / 'data/regress' / f'{scene}_unoverlapping_{scene}_unoverlapping_s0.npz')
    idx = np.sort(np.random.default_rng(1).choice(len(z['coords']), n, replace=False))
    _, c16, _, _ = scene_cube(scene)
    wins = np.stack([np.asarray(c16[r:r + 7, c:c + 7]) for r, c in z['coords'][idx]]).astype('<i2')
    lg = np.zeros((n, 32), '<i4'); cl = np.zeros(n, '<u4')
    for i, w in enumerate(wins):
        o = E.forward(E.entry_b(w))
        lg[i, :E.ncls] = o['logits']; cl[i] = (o['conf'] << 16) | o['label']
    wins.tofile(d / 'wins_i16.bin'); lg.tofile(d / 'expect_logits_i32.bin'); cl.tofile(d / 'expect_class_u32.bin')
    np.savetxt(d / 'coords.txt', z['coords'][idx], fmt='%d')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['regress', 'golden', 'scan-front', 'int8-selftest', 'report8'])
    ap.add_argument('--scenes', nargs='+', default=['longkou', 'honghu', 'hanchuan'])
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--num', type=int, default=16)
    ap.add_argument('--cube-rule', default=CUBE_RULE, choices=['max', 'sat', 'bfp'])
    ap.add_argument('--limit', type=int, default=0, help='regress --num 8：每景只取前 N 个回归像素（自检）')
    ap.add_argument('--out', help='golden 输出目录（默认 sim/golden/n6_engine 或 n6_engine_i8）')
    a = ap.parse_args()
    if a.cmd == 'scan-front':
        scan_front(a.scenes)
    elif a.cmd == 'regress' and a.num == 8:
        regress8(a.scenes, a.workers, a.limit)
        (ROOT / 'build/host/int8_ref/regress8_done.txt').write_text(time.strftime('%F %T'))
    elif a.cmd == 'regress':
        rep = ROOT / 'report' / 'accuracy_fixed_pc.md'
        if 'engine_ref' not in rep.read_text(encoding='utf-8'):
            with rep.open('a', encoding='utf-8') as f:
                f.write(REP_HEAD)
        regress(a.scenes, a.workers, a.cube_rule)
        (ROOT / 'build/host/engine_ref_regress_done.txt').write_text(time.strftime('%F %T'))
    elif a.cmd == 'golden':
        write_golden(a.num, a.out)
    elif a.cmd == 'report8':
        report8(a.scenes)
    else:
        int8_selftest(a.scenes)


def int8_selftest(scenes_, n=100):
    """--num 8 结构自测：PTQ 逐矩阵 2 幂权重（QAT 权重出来后换 ckpt 即可），对浮点比一致率。"""
    import preprocess
    from scenes import SCENES
    for sc in scenes_:
        z = np.load(ROOT / 'data/regress' / f'{sc}_unoverlapping_{sc}_unoverlapping_s0.npz')
        E = Engine(str(ROOT / 'data/ckpt' / f'{sc}_unoverlapping_s0.pth'), len(SCENES[sc]['classes']), num=8)
        c32, c16, _, _ = scene_cube(sc)
        idx = np.random.default_rng(0).choice(len(z['coords']), n, replace=False)
        ag = 0; dm = 0.0
        for i in idx:
            r, c = z['coords'][i]
            o = E.forward(E.entry_b(np.asarray(c16[r:r + 7, c:c + 7])))
            lf = z['logits_float'][i]
            ag += o['label'] == int(np.argmax(lf)); dm = max(dm, float(np.abs(o['logits'] / 65536.0 - lf).max()))
        print(f'{sc} int8 PTQ entry B: agree {ag}/{n}, max|dlogit| {dm:.3f}', flush=True)


if __name__ == '__main__':
    main()
