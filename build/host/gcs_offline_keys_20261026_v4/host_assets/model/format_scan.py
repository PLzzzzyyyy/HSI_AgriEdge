"""data_t 格式扫描（PLAN §17 D1 的数值格式决策依据）：在 fixed_regression.py 抽过的同一批像素上，
把 PL 定点投影路径换成候选格式重跑，比标签一致率与 logits 误差；并按"浮点路径是否出现 |xn|>8"把像素分成饱和 / 未饱和两组。

候选：Q3.12/16（现状，直接读 npz）、Q4.11/16、Q5.10/16、Q5.12/18（mid Q3.14/18）、Q5.12/18（mid Q5.14/20）。
结果追加 report/format_scan_pc.md，逐格式 logits 存 data/regress/format_scan_<scene>.npz（不入库）。

用法：D:/pytorch/python.exe model/format_scan.py [--workers 12] [--scenes longkou honghu hanchuan]
"""
import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import preprocess

SCENES = {'longkou': (9, (556, 406, 270)), 'honghu': (22, (946, 481, 270)), 'hanchuan': (16, (1223, 309, 270))}
FORMAT_SETS = {
    'width': [  # (标签, Fmt 参数)：data_t 位宽 / 范围候选
        ('Q4.11/16 mid Q3.14/18', dict(DF=11, WF=14, MF=14, DB=16, WB=16, MB=18)),
        ('Q5.10/16 mid Q3.14/18', dict(DF=10, WF=14, MF=14, DB=16, WB=16, MB=18)),
        ('Q5.12/18 mid Q3.14/18', dict(DF=12, WF=14, MF=14, DB=18, WB=16, MB=18)),
        ('Q5.12/18 mid Q5.14/20', dict(DF=12, WF=14, MF=14, DB=18, WB=16, MB=20)),
    ],
    'int8': [  # int8 候选（训练后直接量化，无重训）；'pm' = 因子逐矩阵 2 的幂缩放（每个 M1/M2/M3 自己的小数位，使 max|w| 落在 [64,127]）
        ('w8 Q0.7, act Q5.12/18, mid Q3.14/18', dict(DF=12, WF=7, MF=14, DB=18, WB=8, MB=18)),
        ('w8 pm, act Q5.12/18, mid Q3.14/18', dict(DF=12, WF='pm', MF=14, DB=18, WB=8, MB=18)),
        ('act8 Q3.4, w Q1.14/16, mid Q3.14/18', dict(DF=4, WF=14, MF=14, DB=8, WB=16, MB=18)),
        ('act8 Q4.3, w Q1.14/16, mid Q3.14/18', dict(DF=3, WF=14, MF=14, DB=8, WB=16, MB=18)),
        ('all8: act Q3.4, w Q0.7, mid Q3.4/8', dict(DF=4, WF=7, MF=4, DB=8, WB=8, MB=8)),
        ('all8 pm: act Q3.4, w pm, mid Q3.4/8', dict(DF=4, WF='pm', MF=4, DB=8, WB=8, MB=8)),
        ('all8 pm: act Q4.3, w pm, mid Q4.3/8', dict(DF=3, WF='pm', MF=3, DB=8, WB=8, MB=8)),
    ],
}
FORMATS = FORMAT_SETS['width']
LIM = 8.0
_nets = _cube = None


def make_net(f, ckpt, ncls):
    """WF='pm'：因子逐矩阵 2 的幂缩放；其余同 fixed_point_sim.Net。"""
    from fixed_point_sim import Net
    from quant import Fmt, quant, rnd_sat, dequant, W, J
    if f['WF'] != 'pm':
        return Net('unoverlapping', Fmt(**f), ckpt=ckpt, classes=ncls)
    fmt = Fmt(**dict(f, WF=0))

    class NetPM(Net):
        def __init__(self):
            super().__init__('unoverlapping', fmt, ckpt=ckpt, classes=ncls)
            lim = (1 << (fmt.WB - 1)) - 1
            for L in self.layers:
                for nm in ('query', 'key', 'value', 'mlp'):
                    wf = [int(np.floor(np.log2(lim / np.abs(m).max()))) for m in L[nm]['f']]
                    L[nm]['wf'] = wf
                    L[nm]['q'] = [quant(m, s, fmt.WB) for m, s in zip(L[nm]['f'], wf)]

        def proj(self, x, L, nm, fixed):
            if not fixed:
                return super().proj(x, L, nm, fixed)
            xq = quant(x, fmt.DF, fmt.DB)
            m1, m2, m3 = L[nm]['q']; w1, w2, w3 = L[nm]['wf']
            t1 = rnd_sat(np.einsum('ai,nibj->nabj', m1, xq), fmt.DF + w1 - fmt.MF, fmt.MB)
            t2 = rnd_sat(np.einsum('bi,naij->nabj', m2, t1), w2, fmt.MB)
            y = rnd_sat(np.einsum('cj,nabj->nabc', m3, t2), fmt.MF + w3 - fmt.DF, fmt.DB)
            return dequant(y, fmt.DF)
    return NetPM()


def init(scene, ckpt, ncls, shape, formats):
    global _nets, _cube, FORMATS
    import torch
    torch.set_num_threads(1)
    FORMATS = formats
    _nets = [make_net(f, ckpt, ncls) for _, f in FORMATS]
    _cube = np.memmap(ROOT / 'data' / 'scenes' / scene / 'cube_f32.bin', dtype='<f4', mode='r', shape=shape)


def one(rc):
    patch = preprocess.patch_tensor(_cube, *rc).astype(np.float64)
    tr = []
    _nets[0].forward(patch, fixed=False, trace=tr)                      # 浮点路径同时给出饱和判据
    mx = max(max(np.abs(t['xn']).max(), np.abs(t['xn2']).max()) for t in tr)
    return mx, [n.forward(patch, fixed=True) for n in _nets]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--scenes', nargs='+', default=list(SCENES))
    ap.add_argument('--set', default='width', choices=list(FORMAT_SETS))
    args = ap.parse_args()
    formats = FORMAT_SETS[args.set]
    rep = ROOT / 'report' / 'format_scan_pc.md'
    if not rep.exists():
        rep.write_text('# data_t 格式扫描（PC 定点仿真，fixed_regression 同批像素；D1 数值格式决策依据）\n\n'
                       '由 model/format_scan.py 追加，勿手改。饱和像素 = 浮点路径某层 |xn| 或 |xn2| > 8 的像素；'
                       'max|dlogit| 按 全部 / 饱和 / 未饱和 三组分别给出；标签一致率与 OA 相对同一 checkpoint 的全浮点路径。\n\n'
                       '| 日期 | 景 | 像素 | 饱和像素 | 格式 | 标签一致率 | 不一致数 | OA fixed | max\\|dlogit\\| 全部 | 饱和 | 未饱和 | mean\\|dlogit\\| |\n'
                       '|---|---|---|---|---|---|---|---|---|---|---|---|\n', encoding='utf-8')
    for scene in args.scenes:
        ncls, shape = SCENES[scene]
        z = np.load(ROOT / 'data' / 'regress' / f'{scene}_unoverlapping_{scene}_unoverlapping_s0.npz')
        coords, gt = z['coords'], z['gt'].astype(np.int64)
        fl = z['logits_float'].astype(np.float64)
        ckpt = ROOT / 'data' / 'ckpt' / f'{scene}_unoverlapping_s0.pth'
        t0 = time.time()
        print(f'{scene}: {len(coords)} pixels, set {args.set}, {len(formats)} formats', flush=True)
        with Pool(args.workers, initializer=init, initargs=(scene, str(ckpt), ncls, shape, formats)) as p:
            res = p.map(one, [tuple(c) for c in coords], chunksize=16)
        mx = np.array([r[0] for r in res])
        sat = mx > LIM
        fixed = {'Q3.12/16 mid Q3.14/18': z['logits_fixed'].astype(np.float64)}
        for i, (name, _) in enumerate(formats):
            fixed[name] = np.stack([r[1][i] for r in res])
        pf = fl.argmax(1)
        rows = []
        for name, fx in fixed.items():
            pq = fx.argmax(1)
            d = np.abs(fx - fl).max(1)
            oa = float(np.mean(pq + 1 == gt))
            agree = float(np.mean(pq == pf))
            row = (time.strftime('%Y-%m-%d'), scene, len(coords), int(sat.sum()), name, agree, int(np.sum(pq != pf)), oa,
                   float(d.max()), float(d[sat].max()) if sat.any() else 0.0, float(d[~sat].max()), float(np.abs(fx - fl).mean()))
            rows.append(row)
            print(f'  {name:24s} agree {agree:.4f} ({row[6]} mism)  OA {oa:.4f}  max|dlogit| all/sat/unsat '
                  f'{row[8]:.4f}/{row[9]:.4f}/{row[10]:.4f}  mean {row[11]:.5f}', flush=True)
        with rep.open('a', encoding='utf-8') as f:
            for r in rows:
                f.write(f'| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]:.4f} | {r[6]} | {r[7]:.4f} | {r[8]:.4f} | {r[9]:.4f} | {r[10]:.4f} | {r[11]:.5f} |\n')
        np.savez(ROOT / 'data' / 'regress' / f'format_scan_{args.set}_{scene}.npz', coords=coords, max_abs_xn=mx.astype(np.float32),
                 **{k.replace('/', '_').replace(' ', '_').replace('.', 'p').replace('|', '').replace(':', ''): v.astype(np.float32)
                    for k, v in fixed.items()})
        print(f'  {scene} done in {time.time() - t0:.0f}s  (saturated {sat.sum()}/{len(coords)}, max|xn| {mx.max():.1f})', flush=True)
    (ROOT / 'build' / 'host' / f'format_scan_{args.set}_done.txt').write_text(json.dumps(dict(scenes=args.scenes, time=time.strftime('%F %T'))))


if __name__ == '__main__':
    main()
