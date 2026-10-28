"""D3 注意力 / 分类头 HLS 单元的边界用例（PLAN §17 D3，docs/engine_arch.md §3.4、§3.6）。oracle = model/engine_ref.py。

输出 sim/attn/vectors/（tb_attn.cpp 读；每个文件 = 8 字节用例数 + 定长记录，小端）：
  exp_cases.bin          d (i64) → exp_q24(d) (i64)：截断阈值两侧、i = u >> 48 的进位、T_HI / T_LO 全部表项、随机
  softmax_cases.bin      s[6][6] (i64) → attn[6][6] (i32)：全相等（S = 6·2^24）、单峰（S = 2^24）、d 在 EXP_CUT 两侧、
                         S 略大于 2^24、e·r 恰在舍入半点及其下 1、随机
  scores_cases.bin       q、k 生成描述 → s[6][6] (i64)：±2^17 极值、随机
  ctx_cases.bin          attn[6][6] (i64)、v、xn 生成描述 → S1[6]、Sxx[6] (i64)、x_mid (15876 × i32)：
                         ctx 正负饱和、x_mid 正负饱和、ctx 舍入半点、attn 取满 25 位
  head_cases.bin         ncls、x 生成描述、24 类 × (W 生成描述、e_c、b_c) → logits[32] (i32)、类别字 (u32 + 4 B 0)：
                         logit 并列（取小下标）、conf 饱和到 0xFFFF 与 0xFFFF/0xFFFE 分界、E 截断阈值、r = 1 与 63、ncls = 1..24
  head_hanchuan_x1.bin   sim/golden/n6_engine/batch_hanchuan 32 像素的终块 token 1（2646 × i32）；期望值即该目录的 expect_*.bin
生成描述 (mode, a, b, seed) 各 i64：mode 0 = 常数 a；mode 1 = [a, b] 均匀，第 i 个元素 = a + splitmix64(seed + (i+1)·γ) mod (b − a + 1)，
块按 (p, n) 内存序生成（tb 同式）。先对黄金向量与 engine_ref.attention 自检，确认这里照抄的 softmax / ctx 段与 engine_ref 逐位一致。
用法：D:/pytorch/python.exe sim/attn/gen_vectors.py
"""
import struct
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'model'))
import engine_ref as ER  # noqa: E402

N, D = ER.N, ER.D
DN = D * N
CFG = ER.Cfg(16)
GOLD = ROOT / 'sim/golden/n6_engine'
OUT = ROOT / 'sim/attn/vectors'
A18 = (-(1 << 17), (1 << 17) - 1)
SLIM = (1 << 46) - 1                    # |s| < 2^46（§3.4）


def gen(desc, n):
    mode, a, b, seed = desc
    if mode == 0:
        return np.full(n, a, np.int64)
    i = np.arange(1, n + 1, dtype=np.uint64)
    z = np.uint64(seed) + i * np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    z = z ^ (z >> np.uint64(31))
    return a + (z % np.uint64(b - a + 1)).astype(np.int64)


def rnd(seed, lo, hi):
    return (1, lo, hi, seed)


def const(v):
    return (0, v, 0, 0)


# ------------------------------------------------------------------ oracle
def scores_ref(q, k):
    return ER.attention(q, k, np.zeros_like(q), CFG)[1]


def softmax_ref(s):
    """engine_ref.attention 里 s → attn 的四行（照抄；self_check 核对与 attention 一致）。"""
    d = (s.max(1, keepdims=True) - s) << (24 - 2 * CFG.DF)
    e = ER.exp_q24(d)
    S = e.sum(1, keepdims=True)
    r = (1 << 47) // S
    return (e * r + (1 << 22)) >> 23


def ctx_ref(attn, v, xn):
    """engine_ref.attention 的 ctx 段 + Engine.forward 的残差 x_mid = sat(xn + ctx)。"""
    vb = v.reshape(-1).reshape(N, D)
    ctx = ER.sat(ER.rshift_rnd((attn @ vb).reshape(D, N), 24), CFG.DB)
    return ER.sat(xn + ctx, CFG.DB)


def gblk(ent, l, name):
    return np.fromfile(GOLD / ent / f'L{l}_{name}_i4.bin', '<i4').astype(np.int64).reshape(D, N)


def self_check():
    for ent in 'ab':
        for l in range(ER.LAYERS):
            q, k, v, xn, xm = (gblk(ent, l, nm) for nm in ('q', 'k', 'v', 'xn_q', 'x_mid'))
            s = np.fromfile(GOLD / ent / f'L{l}_s_i8.bin', '<i8').reshape(N, N)
            at = np.fromfile(GOLD / ent / f'L{l}_attn_i4.bin', '<i4').astype(np.int64).reshape(N, N)
            assert np.array_equal(scores_ref(q, k), s), (ent, l, 's')
            assert np.array_equal(softmax_ref(s), at), (ent, l, 'attn')
            assert np.array_equal(ctx_ref(at, v, xn), xm), (ent, l, 'x_mid')
    rng = np.random.default_rng(3)
    for sc in (1 << 17, 1 << 12, 1 << 9):
        q, k, v, xn = (rng.integers(-sc, sc, (D, N)) for _ in range(4))
        ctx, s, at = ER.attention(q, k, v, CFG)
        assert np.array_equal(softmax_ref(s), at)
        assert np.array_equal(ctx_ref(at, v, xn), ER.sat(xn + ctx, CFG.DB))
    print('self-check: golden 24 layers + random attention, softmax_ref / ctx_ref == engine_ref', flush=True)


# ------------------------------------------------------------------ exp
def i_edges():
    """u = d·LOG2E 跨过 k·2^48 的 d（k = 1..36）及其前一个。"""
    out = []
    for k in range(1, 37):
        dk = -(-(k << 48) // ER.LOG2E_Q24)
        out += [dk - 1, dk]
    return out


def exp_cases(rng):
    C = ER.EXP_CUT
    d = [0, 1, 2, 3, C - 2, C - 1, C, C + 1, (1 << 40), (1 << 47) - 2, 16 << 24, 17 << 24] + i_edges()
    perm = rng.permutation(256)
    for a in range(256):                                # T_HI、T_LO 全部表项：f = a·256 + perm[a]，i = a mod 25
        f = a * 256 + int(perm[a])
        d.append(-(-(((a % 25) << 48) + (f << 32)) // ER.LOG2E_Q24))
    for j in rng.integers(1, 36 * 256, 200):             # f 高 8 位进位（低 8 位 255 → 0）
        dj = -(-(int(j) << 40) // ER.LOG2E_Q24)
        d += [dj - 1, dj]
    d += rng.integers(0, 30 << 24, 3000).tolist() + rng.integers(0, 1 << 24, 1000).tolist()
    d = np.array(d, np.int64)
    e = ER.exp_q24(d)
    return [struct.pack('<qq', int(a), int(b)) for a, b in zip(d, e)]


# ------------------------------------------------------------------ softmax
def attn_round_rows(rng, want=16):
    """搜 e_c·r mod 2^23 恰为 2^22（半点，进位）或 2^22 − 1 的行：固定 4 个 d，扫第 5 个。"""
    rows = []
    for _ in range(60):
        dfix = rng.integers(0, 6 << 24, 4)
        efix = ER.exp_q24(dfix)
        start = int(rng.integers(0, 8 << 24))
        dsw = np.arange(start, start + (1 << 21), dtype=np.int64)
        esw = ER.exp_q24(dsw)
        r = (1 << 47) // ((1 << 24) + int(efix.sum()) + esw)
        es = [np.full_like(esw, int(x)) for x in efix] + [esw]
        for ci, ec in enumerate(es):
            res = (ec * r) & ((1 << 23) - 1)
            for tgt in (1 << 22, (1 << 22) - 1):
                key = (tgt, ci == 4)
                idx = np.flatnonzero(res == tgt)
                if len(idx) and sum(1 for k in rows if k[1] == key) < want // 4:
                    rows.append((np.concatenate([[0], dfix, [dsw[idx[0]]]]), key))
        if len(rows) >= want:
            break
    out = []
    for d6, _ in rows[:want]:
        out.append(-d6[rng.permutation(6)])
    return out


def softmax_rows(rng):
    C = ER.EXP_CUT
    rows = [[K] * 6 for K in (0, 1, -1, SLIM, -SLIM, 123456789012)]          # 全相等：S = 6·2^24
    rows.append([SLIM, -SLIM, -SLIM, -SLIM, -SLIM, -SLIM])                   # 单峰：S = 2^24，attn = 2^24
    rows.append([-SLIM, SLIM, -SLIM, SLIM, -SLIM, -SLIM])                    # 两个并列最大
    for m in (0, SLIM, -SLIM + 2 * C):                                       # d = EXP_CUT − 1 / EXP_CUT / EXP_CUT + 1
        rows.append([m, m - (C - 1), m - C, m - (C + 1), m - 1, m - 2])
    ie = i_edges()
    for j in range(0, len(ie), 5):                                           # i 进位边界
        ds = ie[j:j + 5] + [0] * (5 - len(ie[j:j + 5]))
        rows.append([0] + [-x for x in ds])
    d23 = -(-(23 << 48) // ER.LOG2E_Q24)
    d24 = -(-(24 << 48) // ER.LOG2E_Q24)
    d25 = -(-(25 << 48) // ER.LOG2E_Q24)
    rows.append([0, -d24, -d24, -d23, -(d23 + 1000), -(d25 - 1)])            # e ∈ {1, 2}：S 略大于 2^24
    rows.append([0, -(d24 - 1), -d24, -(d24 + 1), -(d25 - 2), -(d25 - 1)])
    rows += [list(r) for r in attn_round_rows(rng)]
    for _ in range(60):                                                      # 随机：d 混合量级，最大值位置随机
        sc = int(rng.choice([1 << 22, 1 << 24, 3 << 24, 30 << 24, 1 << 40]))
        d = rng.integers(0, sc, 6)
        d[rng.integers(0, 6)] = 0
        m = int(rng.integers(-SLIM + (1 << 41), SLIM))
        rows.append((m - d).tolist())
    for r in rows:
        assert all(abs(int(x)) <= SLIM for x in r) and len(r) == 6, r
    while len(rows) % 6:
        rows.append([0] * 6)
    recs = []
    for i in range(0, len(rows), 6):
        s = np.array(rows[i:i + 6], np.int64)
        a = softmax_ref(s)
        recs.append(s.astype('<i8').tobytes() + a.astype('<i4').tobytes())
    return recs


# ------------------------------------------------------------------ scores
def scores_cases():
    cs = [(const(-(1 << 17)), const(-(1 << 17))),                            # s = 2646·2^34（正向最大）
          (const((1 << 17) - 1), const(-(1 << 17))),                         # 负向最大
          (rnd(11, *A18), rnd(12, *A18)),
          (rnd(13, -100, 100), rnd(14, *A18)),
          (const(1), rnd(15, *A18))]
    recs = []
    for qd, kd in cs:
        q, k = gen(qd, DN).reshape(D, N), gen(kd, DN).reshape(D, N)
        s = scores_ref(q, k)
        assert np.abs(s).max() < 1 << 46
        recs.append(np.array(qd + kd, '<i8').tobytes() + s.astype('<i8').tobytes())
    return recs


# ------------------------------------------------------------------ ctx
def valid_attn(rng, spread):
    d = rng.integers(0, spread, (N, N))
    return softmax_ref(-d)


def ctx_cases(rng):
    full = np.full((N, N), 1 << 24, np.int64)
    diag = np.diag(np.full(N, 1 << 23, np.int64))
    cs = [(valid_attn(rng, 3 << 24), rnd(21, *A18), rnd(22, *A18)),
          (full, const((1 << 17) - 1), rnd(23, *A18)),                       # ctx 正饱和
          (full, const(-(1 << 17)), rnd(24, *A18)),                          # ctx 负饱和
          (diag, rnd(25, -9, 9), const(0)),                                  # ctx = 2^23·v：奇数 v 恰在舍入半点
          (np.full((N, N), (1 << 25) - 1, np.int64), rnd(26, *A18), rnd(27, *A18)),   # attn 取满 25 位
          (valid_attn(rng, 1 << 24), rnd(28, 0, (1 << 17) - 1), const((1 << 17) - 1)),  # x_mid 正饱和
          (valid_attn(rng, 1 << 24), rnd(29, -(1 << 17), 0), const(-(1 << 17)))]        # x_mid 负饱和
    recs = []
    for at, vd, xd in cs:
        v, xn = gen(vd, DN).reshape(D, N), gen(xd, DN).reshape(D, N)
        xm = ctx_ref(at, v, xn)
        s1, sxx = xm.sum(0), (xm * xm).sum(0)
        recs.append(at.astype('<i8').tobytes() + np.array(vd + xd, '<i8').tobytes() + s1.astype('<i8').tobytes()
                    + sxx.astype('<i8').tobytes() + xm.astype('<i4').tobytes())
    return recs


# ------------------------------------------------------------------ head
def head_rec(ncls, xd, cls):
    cls = list(cls) + [(const(0), 0, 0)] * (ER.NCLS_MAX - len(cls))
    assert len(cls) == ER.NCLS_MAX and 1 <= ncls <= ER.NCLS_MAX
    xt = gen(xd, D)
    wq = np.stack([gen(w, D) for w, _, _ in cls[:ncls]])
    assert wq.min() >= -32768 and wq.max() <= 32767
    e = np.array([c[1] for c in cls[:ncls]], np.int64)
    b = np.array([c[2] for c in cls[:ncls]], np.int64)
    l, label, conf = ER.head(xt, (wq, e, b), CFG)
    assert np.abs(l).max() < 1 << 31
    lg = np.zeros(32, np.int64)
    lg[:ncls] = l
    body = struct.pack('<q', ncls) + np.array(xd, '<i8').tobytes()
    for w, ec, bc in cls:
        body += np.array(list(w) + [ec, bc], '<i8').tobytes()
    return body + lg.astype('<i4').tobytes() + struct.pack('<II', (conf << 16) | label, 0), (label, conf)


def conf_edge_bias():
    """找 Δ（Q.16）使 E(Δ·256) = 256 与 257：ΣE = 2^24 + 256 → conf 0xFFFF，2^24 + 257 → 0xFFFE。"""
    d = np.arange(690000, 770000, dtype=np.int64)
    E = ER.exp_q24(d << 8)
    return int(d[np.flatnonzero(E == 256)[0]]), int(d[np.flatnonzero(E == 257)[0]])


def head_cases(rng):
    W16 = (-32768, 32767)
    z = (const(0), 19, 0)
    cs = []
    cs.append((24, rnd(31, *A18), [(rnd(100 + c, *W16), 14 + c % 9, int(rng.integers(-1 << 20, 1 << 20))) for c in range(24)]))
    cs.append((9, rnd(32, -40000, 40000), [(rnd(130 + c, -3000, 3000), 19, int(rng.integers(-3000, 3000))) for c in range(9)]))
    cs.append((16, rnd(33, *A18), [(rnd(150 + c, *W16), 18, int(rng.integers(-1 << 18, 1 << 18))) for c in range(16)]))
    cs.append((22, rnd(34, *A18), [(rnd(170 + c, *W16), 19 + c % 2, int(rng.integers(-1 << 18, 1 << 18))) for c in range(22)]))
    cs.append((1, rnd(35, *A18), [(rnd(200, *W16), 19, 12345)]))                         # 单类：label 0，conf 0xFFFF
    cs.append((4, const(-(1 << 17)), [(const(-32768), 18, 0), (const(32767), 18, 0),      # acc 两个方向的极值
                                     (rnd(201, *W16), 18, 0), (const(0), 18, 5)]))
    cs.append((7, const(0), [(const(0), 19, b * 65536) for b in (3, 7, 7, 1, 7, -2, 0)]))  # 三个并列最大 → label 1
    cs.append((24, rnd(36, *A18), [(const(0), 19, 100 * 65536 if c in (0, 23) else int(rng.integers(-1 << 22, 99 * 65536)))
                                   for c in range(24)]))                                 # 首末并列 → label 0
    cs.append((5, rnd(37, *A18), [(const(0), 19, 1 << 24)] + [z] * 4))                    # E = 0：ΣE = 2^24 → conf 0xFFFF
    d256, d257 = conf_edge_bias()
    cs.append((2, const(0), [(const(0), 19, d256), z]))                                  # ΣE = 2^24 + 256 → 0xFFFF
    cs.append((2, const(0), [(const(0), 19, d257), z]))                                  # ΣE = 2^24 + 257 → 0xFFFE
    for db in (1638399, 1638400, 1638401):                                               # (Δ << 8) 在 EXP_CUT 两侧
        cs.append((2, const(0), [(const(0), 19, db), z]))
    cs.append((3, rnd(38, -5, 5), [(rnd(202, -3, 3), 5, 7), (rnd(203, *W16), 67, -9),      # r = 1、63、26
                                   (rnd(204, *W16), 30, 0)]))
    cs.append((12, rnd(39, *A18), [(rnd(210 + c, *W16), 20, -(1 << 27) + c) for c in range(12)]))   # 全负 logits
    cs.append((3, const(0), [(const(0), 19, -5), (const(0), 19, -5), (const(0), 19, -5)]))  # 全部并列 → label 0，ΣE = 3·2^24
    recs, info = [], []
    for ncls, xd, cls in cs:
        r, li = head_rec(ncls, xd, cls)
        recs.append(r)
        info.append(li)
    return recs, info


# ------------------------------------------------------------------ HanChuan 批：由权重包重建 Engine（不需要 torch 与 checkpoint）
def engine_from_pkg(path):
    b = np.fromfile(path, np.uint8)
    hdr = b[:16].view('<u4')
    assert hdr[0] == 0x32455454 and hdr[3] == 16 and b.size == 480576
    ncls = int(hdr[2])
    E = ER.Engine.__new__(ER.Engine)
    E.cfg, E.ncls = CFG, ncls
    E.emb = b[64:64 + DN * 4].view('<i4').astype(np.int64).reshape(D, N)
    eh = b[32:32 + ncls].view(np.int8).astype(np.int64)
    hb = b[63616:63616 + 4 * ncls].view('<i4').astype(np.int64)
    hw = np.stack([b[63744 + c * 5312:63744 + c * 5312 + 2 * D].view('<i2') for c in range(ncls)]).astype(np.int64)
    E.hw = (hw, eh, hb)
    pj = b[191232:].view('<i2').astype(np.int64).reshape(ER.LAYERS, 4, 3014)
    E.wp = [[(p[:49].reshape(7, 7), p[49:98].reshape(7, 7), p[98:].reshape(54, 54), (14, 14, 14)) for p in row] for row in pj]
    return E


def hanchuan_x1():
    d = GOLD / 'batch_hanchuan'
    E = engine_from_pkg(d / 'weights_engine.bin')
    wins = np.fromfile(d / 'wins_i16.bin', '<i2').reshape(-1, 7, 7, 272)
    el = np.fromfile(d / 'expect_logits_i32.bin', '<i4').reshape(-1, 32)
    ec = np.fromfile(d / 'expect_class_u32.bin', '<u4')
    recs = []
    for i, w in enumerate(wins):
        o = E.forward(E.entry_b(w))
        assert np.array_equal(o['logits'], el[i, :E.ncls]) and ((o['conf'] << 16) | o['label']) == ec[i], f'hanchuan pixel {i}'
        recs.append(o['x'][:, 1].astype('<i4').tobytes())
    return recs


def write(name, recs):
    assert recs and len({len(r) for r in recs}) == 1
    (OUT / name).write_bytes(struct.pack('<q', len(recs)) + b''.join(recs))
    print(f'{name}: {len(recs)} records × {len(recs[0])} B', flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    self_check()
    rng = np.random.default_rng(2026)
    write('exp_cases.bin', exp_cases(rng))
    write('softmax_cases.bin', softmax_rows(rng))
    write('scores_cases.bin', scores_cases())
    write('ctx_cases.bin', ctx_cases(rng))
    recs, info = head_cases(rng)
    print('head cases (label, conf):', info, flush=True)
    write('head_cases.bin', recs)
    write('head_hanchuan_x1.bin', hanchuan_x1())


if __name__ == '__main__':
    main()
