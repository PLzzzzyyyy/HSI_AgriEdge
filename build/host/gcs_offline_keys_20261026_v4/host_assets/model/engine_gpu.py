"""整数引擎（engine_ref.py）的 GPU 批量版：与 Engine.forward(Engine.entry_b(win)) 逐位相同，用来在官方 Test 全集上算整数引擎的 OA。

整数量一律 int64；乘加走浮点矩阵乘但保证精确：int8 投影（积与部分和 ≤ 54·127·128 < 2^24）用 float32，其余 float64（< 2^53）。
每个 token / patch 一次的 float32 sqrt 与除法是 IEEE 正确舍入，与 numpy / C 逐位（verify 核对）。

  verify：三景回归像素 4,700 个——i16 对 data/regress/engine_ref_<景>_kbfp.npz、i8 对 build/host/int8_ref/engine_ref_i8_<景>.npz 全量比，
          mix 每景抽 64 个现算 engine_ref；另加 n6_engine / n6_engine_i8 黄金的入口 B 与 batch_hanchuan。logits、类别、置信度全等才 PASS。
  test：三景官方 Test100 全部像素，i16（s0 权重，int16 版）/ i8（QAT 权重，契约 §3.7）/ mix（QAT 权重，方案 C）的 OA / AA / Kappa，
        追加 report/accuracy_int8_pc.md；逐像素类别与置信度存 build/host/int8_ref/test_<景>_<版>.npz。

用法：D:/pytorch/python.exe model/engine_gpu.py verify
      D:/pytorch/python.exe model/engine_gpu.py test [--scenes longkou honghu hanchuan] [--modes i16 i8 mix] [--batch 512] [--limit N]
"""
import argparse
import sys
import time
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import engine_ref as ER  # noqa: E402

N, D, W, J, LAYERS, PATCH_N = ER.N, ER.D, ER.W, ER.J, ER.LAYERS, ER.PATCH_N
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
torch.backends.cuda.matmul.allow_tf32 = False
MODES = {'i16': dict(num=16), 'i8': dict(num=8), 'mix': dict(num=8, mix=True)}
T_HI = torch.tensor(ER.T_HI, device=DEV)
T_LO = torch.tensor(ER.T_LO, device=DEV)
GMAXF = torch.tensor(np.float32(ER.GMAX), device=DEV)          # 与 entry_b 同：float32(2^25 − 1) 的截断上限
BFP_GC = torch.tensor(ER.BFP_GC, device=DEV)


def sat(v, bits):
    lim = 1 << (bits - 1)
    return v.clamp(-lim, lim - 1)


def rnd(v, s):
    """engine_ref.rshift_rnd：(v + 2^(s-1)) >> s，算术右移 = floor；s ≤ 0 左移。"""
    return (v + (1 << (s - 1))) >> s if s > 0 else v << (-s)


def exp_q24(d):
    u = d.clamp(max=ER.EXP_CUT) * ER.LOG2E_Q24
    e = ((T_HI[((u >> 32) & 0xFFFF) >> 8] * T_LO[(u >> 32) & 255] + (1 << 23)) >> 24) >> (u >> 48)
    return torch.where(d >= ER.EXP_CUT, torch.zeros_like(e), e)


class GEngine:
    """E = engine_ref.Engine（权重与格式的唯一来源）。块布局 (B, D, N)，同 engine_ref 的 (D, N)。"""

    def __init__(self, E):
        self.cfg = c = E.cfg
        self.fdt = torch.float32 if c.PB == 8 else torch.float64
        self.wp = [[tuple(torch.tensor(m, dtype=self.fdt, device=DEV) for m in w[:3]) + (w[3],) for w in row] for row in E.wp]
        self.emb = torch.tensor(E.emb, device=DEV)
        wq, e, b = E.hw
        self.hw = torch.tensor(wq, dtype=torch.float64, device=DEV)
        self.hr = torch.tensor(c.DF + e - 16, device=DEV)
        assert (self.hr >= 1).all()
        self.hb = torch.tensor(b, device=DEV)
        self.inv_c = torch.tensor(c.INV_C, device=DEV)

    def front(self, win):
        """win (B,7,7,272) int16 → x (B,D,N)：entry_b（bfp）。"""
        c = self.cfg
        w = win.long()
        e = w[..., 270]
        sh = (e - e.amin((1, 2), keepdim=True)).unsqueeze(-1)
        v = w[..., :270]
        half = torch.bitwise_left_shift(torch.ones_like(sh), (sh - 1).clamp(min=0))
        q = torch.where(sh > 0, torch.bitwise_right_shift(v + half, sh), v).permute(0, 3, 1, 2).reshape(len(w), -1)
        s1 = q.sum(1)
        V = PATCH_N * (q * q).sum(1) - s1 * s1
        gf = BFP_GC / torch.sqrt(V.to(torch.float32))
        g = torch.where(gf <= GMAXF, gf, GMAXF).to(torch.int64)
        xn = ((PATCH_N * q - s1[:, None]) * g[:, None]) >> ER.BFP_T            # Q.24，e = 5p + (n − 1)
        x = torch.empty(len(w), D, N, dtype=torch.int64, device=DEV)
        x[:, :, 0] = self.emb[:, 0]
        x[:, :, 1:] = xn.reshape(-1, D, N - 1) + self.emb[:, 1:]
        return sat(rnd(x, 24 - c.DF), c.DB)

    def norm(self, x, pf=False):
        """§3.2；pf 时另出投影入口格式 (PF, PB)，与 (DF, DB) 输出出自同一乘积。"""
        c = self.cfg
        sh = 24 - c.DF
        s1 = x.sum(1)
        var = D * (x * x).sum(1) - s1 * s1
        mean = torch.div(s1 << sh, D, rounding_mode='trunc')
        inv = self.inv_c / torch.sqrt(var.to(torch.float32))
        inv = torch.where(inv <= 127.0, inv, torch.full_like(inv, 127.0))
        prod = ((x << sh) - mean[:, None, :]) * (inv * 16777216.0).to(torch.int64)[:, None, :]
        q = sat(rnd(prod, 48 - c.DF), c.DB)
        return (q, sat(rnd(prod, 48 - c.PF), c.PB)) if pf else (q, q)

    def proj(self, xp, wq):
        c = self.cfg
        m1, m2, m3, (e1, e2, e3) = wq
        x = xp.transpose(1, 2).reshape(len(xp), N, W, W, J).to(self.fdt)
        t1 = sat(rnd(torch.einsum('ai,znibj->znabj', m1, x).long(), c.PF + e1 - c.MF), c.MB)
        t2 = sat(rnd(torch.einsum('bi,znaij->znabj', m2, t1.to(self.fdt)).long(), e2), c.MB)
        y = sat(rnd(torch.einsum('cj,znabj->znabc', m3, t2.to(self.fdt)).long(), c.MF + e3 - c.PF), c.PB)
        return y.reshape(len(xp), N, D).transpose(1, 2).contiguous()

    def attn(self, q, k, v):
        c = self.cfg
        s = torch.bmm(q.transpose(1, 2).double(), k.double()).long()           # (B,N,N) Q.(2PF)，精确
        e = exp_q24((s.amax(2, keepdim=True) - s) << (24 - 2 * c.PF))
        S = e.sum(2, keepdim=True)
        a = (e * torch.div(torch.full_like(S, 1 << 47), S, rounding_mode='floor') + (1 << 22)) >> 23
        ctx = torch.bmm(a.double(), v.reshape(len(v), N, D).double()).long().reshape(len(v), D, N)   # V 按内存序切块
        return sat(rnd(ctx, 24 + c.PF - c.DF), c.DB)

    def head(self, x):
        acc = (x[:, :, 1].double() @ self.hw.T).long()
        l = ((acc + torch.bitwise_left_shift(torch.ones_like(self.hr), self.hr - 1)) >> self.hr) + self.hb
        E = exp_q24((l.amax(1, keepdim=True) - l) << 8)
        conf = torch.div(torch.full_like(l[:, 0], 1 << 40), E.sum(1), rounding_mode='floor').clamp(max=0xFFFF)
        return l, l.argmax(1), conf

    @torch.no_grad()
    def forward(self, win):
        c = self.cfg
        x = self.front(win)
        for wl in self.wp:
            xn, xp = self.norm(x, c.mix)
            xm = sat(xn + self.attn(*(self.proj(xp, wl[j]) for j in range(3))), c.DB)
            xn2, xp2 = self.norm(xm, c.mix)
            x = sat(xn2 + (self.proj(xp2, wl[3]) << (c.DF - c.PF)), c.DB)
        return self.head(x)


def windows(cube, rc):
    """cube (Hp,Wp,272) int16（GPU），rc (B,2) 像素坐标 → (B,7,7,272)，同 engine_ref 的 c16[r:r+7, c:c+7]。"""
    ar = torch.arange(7, device=DEV)
    return cube[(rc[:, 0:1] + ar)[:, :, None], (rc[:, 1:2] + ar)[:, None, :]]


def ckpt_of(scene, mode):
    return str(ROOT / 'data/ckpt' / f'{scene}_unoverlapping_s0.pth') if mode == 'i16' else str(ER.qat8_ckpt(scene))


def engine(scene, mode):
    from scenes import SCENES
    return ER.Engine(ckpt_of(scene, mode), len(SCENES[scene]['classes']), **MODES[mode])


def run(G, cube, coords, bs):
    out = [[], [], []]
    rc = torch.as_tensor(np.asarray(coords, np.int64), device=DEV)
    for i in range(0, len(rc), bs):
        for o, t in zip(out, G.forward(windows(cube, rc[i:i + bs]))):
            o.append(t.cpu())
    return [torch.cat(o).numpy() for o in out]            # logits (P, ncls) Q.16、label 0 起、conf Q0.16


def scene_cube_gpu(scene):
    return torch.from_numpy(np.array(ER.scene_cube(scene)[1])).to(DEV)


# ------------------------------------------------------------------ 逐位核对
def verify(scenes_, bs):
    bad = 0

    def check(tag, got, lg, lb, cf):
        nonlocal bad
        l, b, c = got
        ok = np.array_equal(l, lg) and np.array_equal(b, lb) and np.array_equal(c, cf)
        bad += not ok
        print(f'{"PASS" if ok else "FAIL"} {tag}: {len(lb)} 像素' + ('' if ok else
              f'，logits 不同 {int((l != lg).any(1).sum())}、类别不同 {int((b != lb).sum())}、置信度不同 {int((c != cf).sum())}'), flush=True)

    q16 = lambda a: np.rint(np.asarray(a, np.float64) * 65536.0).astype(np.int64)
    for sc in scenes_:
        cube = scene_cube_gpu(sc)
        z8 = np.load(ROOT / 'build/host/int8_ref' / f'engine_ref_i8_{sc}.npz')
        z16 = np.load(ROOT / 'data/regress' / f'engine_ref_{sc}_kbfp.npz')
        assert np.array_equal(z8['coords'], z16['coords'])
        co = z8['coords']
        g = run(GEngine(engine(sc, 'i16')), cube, co, bs)
        check(f'{sc} i16 回归像素', g, q16(z16['logits_b']), q16(z16['logits_b']).argmax(1), z16['conf_b'])
        g = run(GEngine(engine(sc, 'i8')), cube, co, bs)
        check(f'{sc} i8 回归像素', g, q16(z8['logits_i8']), z8['label_i8'], z8['conf_i8'])
        idx = np.sort(np.random.default_rng(3).choice(len(co), 64, replace=False))
        E = engine(sc, 'mix')
        c16 = ER.scene_cube(sc)[1]
        ref = [E.forward(E.entry_b(np.asarray(c16[r:r + 7, cc:cc + 7]), None, True)) for r, cc in co[idx]]
        g = run(GEngine(E), cube, co[idx], bs)
        check(f'{sc} mix 抽样', g, np.stack([o['logits'] for o in ref]), np.array([o['label'] for o in ref]), np.array([o['conf'] for o in ref]))
        del cube
    for gdir, mode in (('n6_engine', 'i16'), ('n6_engine_i8', 'i8')):
        gd = ROOT / 'sim/golden' / gdir
        E = ER.Engine() if mode == 'i16' else ER.Engine(str(ER.qat8_ckpt('longkou')), 9, num=8)
        win = torch.from_numpy(np.fromfile(gd / 'cube_win_i16.bin', '<i2').reshape(1, 7, 7, 272)).to(DEV)
        l, b, c = (t.cpu().numpy() for t in GEngine(E).forward(win))
        cl = np.fromfile(gd / 'b/class_u32.bin', '<u4').astype(np.int64)
        check(f'{gdir} 入口 B', (l, b, c), np.fromfile(gd / 'b/logits_q16_i32.bin', '<i4')[None, :E.ncls].astype(np.int64), cl & 0xFFFF, cl >> 16)
        bd = gd / 'batch_hanchuan'
        wins = torch.from_numpy(np.fromfile(bd / 'wins_i16.bin', '<i2').reshape(-1, 7, 7, 272)).to(DEV)
        l, b, c = (t.cpu().numpy() for t in GEngine(engine('hanchuan', mode)).forward(wins))
        cl = np.fromfile(bd / 'expect_class_u32.bin', '<u4').astype(np.int64)
        check(f'{gdir}/batch_hanchuan', (l, b, c), np.fromfile(bd / 'expect_logits_i32.bin', '<i4').reshape(-1, 32)[:, :16].astype(np.int64),
              cl & 0xFFFF, cl >> 16)
    print('RESULT', 'FAIL' if bad else 'PASS', flush=True)
    return bad


# ------------------------------------------------------------------ 官方 Test 全集
REP8 = ('\n## 整数引擎官方 Test OA（model/engine_gpu.py test；与 engine_ref.py 逐位，即板上应得结果）\n\n'
        '由 engine_gpu.py test 追加，勿手改。输入 cube_i16.bin（契约 v3 bfp），入口 B 全整数。i16 = s0 权重、W16A18（int16 版）；'
        'i8 = QAT 权重、契约 §3.7（全 8 位）；mix = QAT 权重、方案 C（投影核 8 位，残差 / ctx / 前端 / 分类头 18 位，未进契约）。'
        '末列为回归像素上与 torch 假量化前向的标签一致率（诊断，不是验收）。\n\n'
        '| 日期 | 景 | 版本 | ckpt | Test 像素 | OA | AA | Kappa | OA − i16 | 回归像素对假量化一致率 | 用时 s |\n'
        '|---|---|---|---|---|---|---|---|---|---|---|\n')


def test(scenes_, modes, bs, limit):
    import preprocess
    import scenes
    from train_scene import metrics
    od = ROOT / 'build/host/int8_ref'
    od.mkdir(parents=True, exist_ok=True)
    rep = ROOT / 'report' / 'accuracy_int8_pc.md'
    rows = []
    for sc in scenes_:
        ncls = len(scenes.SCENES[sc]['classes'])
        _, test_p = scenes.split_paths(sc, 100)
        m = preprocess.load_mat(test_p).astype(np.int64)
        tc = np.argwhere(m > 0)
        if limit:
            tc = tc[:limit]
        ty = m[tc[:, 0], tc[:, 1]]
        cube = scene_cube_gpu(sc)
        z8 = np.load(ROOT / 'build/host/int8_ref' / f'engine_ref_i8_{sc}.npz')
        oa16 = None
        for mode in modes:
            t0 = time.time()
            G = GEngine(engine(sc, mode))
            _, lab, conf = run(G, cube, tc, bs)
            mt = metrics(lab + 1, ty, ncls)
            fq_ag = '—'
            if mode != 'i16':
                _, lr, _ = run(G, cube, z8['coords'], bs)
                fq_ag = f"{np.mean(lr == z8['logits_fq'].argmax(1)):.4f}"
            oa16 = mt['OA'] if mode == 'i16' else oa16
            sec = int(time.time() - t0)
            np.savez(od / f'test_{sc}_{mode}{"_lim%d" % limit if limit else ""}.npz', coords=tc, gt=ty, label=lab.astype(np.int16), conf=conf.astype(np.int32))
            r = dict(scene=sc, mode=mode, ckpt=Path(ckpt_of(sc, mode)).name, pixels=len(tc), OA=mt['OA'], AA=mt['AA'], Kappa=mt['Kappa'],
                     dOA=None if oa16 is None or mode == 'i16' else mt['OA'] - oa16, fq_agree=fq_ag, seconds=sec)
            print(r, flush=True)
            rows.append(r)
        del cube
    if limit:
        return rows
    with rep.open('a', encoding='utf-8') as f:
        if '整数引擎官方 Test OA' not in rep.read_text(encoding='utf-8'):
            f.write(REP8)
        for r in rows:
            d = '—' if r['dOA'] is None else f"{100 * r['dOA']:+.2f} 点"
            f.write(f"| {time.strftime('%Y-%m-%d')} | {r['scene']} | {r['mode']} | {r['ckpt']} | {r['pixels']} | {r['OA']:.4f} | {r['AA']:.4f} | "
                    f"{r['Kappa']:.4f} | {d} | {r['fq_agree']} | {r['seconds']} |\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['verify', 'test'])
    ap.add_argument('--scenes', nargs='+', default=['longkou', 'honghu', 'hanchuan'])
    ap.add_argument('--modes', nargs='+', default=['i16', 'i8', 'mix'], choices=list(MODES))
    ap.add_argument('--batch', type=int, default=512)
    ap.add_argument('--limit', type=int, default=0, help='test：每景只取前 N 个 Test 像素、不写报告（自检）')
    a = ap.parse_args()
    if a.cmd == 'verify':
        sys.exit(1 if verify(a.scenes, a.batch) else 0)
    test(a.scenes, a.modes, a.batch, a.limit)
    (ROOT / 'build/host/int8_ref/test_done.txt').write_text(time.strftime('%F %T'))


if __name__ == '__main__':
    main()
