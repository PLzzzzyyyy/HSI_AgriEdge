"""定点仿真回归（PLAN §17 B2）：一景一个 checkpoint，在官方 Test 划分上抽样，比 PL 定点路径与全浮点路径。

输入与板上一致：从 data/scenes/<scene>/cube_f32.bin 取窗（没有就现算 preprocess.Scene）。
每类最多抽 --per-class 个测试像素（seed 固定），两条路径各算一次 logits：
  OA/AA/Kappa（float、fixed 各一份）、标签一致率、max|dlogit|、mean|dlogit|。
结果追加 report/accuracy_fixed_pc.md；逐像素坐标与两路 logits 存 data/regress/<tag>.npz，板上跑同一批像素时直接比对。

用法：D:/pytorch/python.exe model/fixed_regression.py --scene honghu --ckpt data/ckpt/honghu_unoverlapping_s0.pth
      [--per-class 100] [--seed 0] [--workers 12]
"""
import argparse
import hashlib
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess
import scenes

ROOT = scenes.ROOT
PAD = preprocess.HALF
FMT_ARGS = dict(DF=12, WF=14, MF=14)

_net = None
_cube = None


def _init(model, ckpt, ncls, cube_path, shape_or_array):
    """cube_path 给了就 memmap 板上立方体；否则 shape_or_array 直接是算好的 padded 数组。"""
    global _net, _cube
    import torch
    torch.set_num_threads(1)
    from fixed_point_sim import Net
    from quant import Fmt
    _net = Net(model, Fmt(**FMT_ARGS), ckpt=ckpt, classes=ncls)
    _cube = np.memmap(cube_path, dtype='<f4', mode='r', shape=shape_or_array) if cube_path else shape_or_array


def _one(rc):
    r, c = rc
    patch = preprocess.patch_tensor(_cube, r, c).astype(np.float64)
    return _net.forward(patch, fixed=True), _net.forward(patch, fixed=False)


def sample(test_mask, per_class, seed):
    rng = np.random.default_rng(seed)
    out = []
    for c in range(1, int(test_mask.max()) + 1):
        pts = np.argwhere(test_mask == c)
        rng.shuffle(pts)
        out.append(pts[:per_class])
    return np.concatenate(out)


def metrics(pred, gt, ncls):
    cm = np.zeros((ncls, ncls), np.int64)
    np.add.at(cm, (gt - 1, pred - 1), 1)
    oa = np.trace(cm) / cm.sum()
    per = np.diag(cm) / np.maximum(cm.sum(1), 1)
    pe = (cm.sum(0) * cm.sum(1)).sum() / cm.sum() ** 2
    return float(oa), float(per.mean()), float((oa - pe) / (1 - pe))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', required=True, choices=list(scenes.SCENES))
    ap.add_argument('--model', default='unoverlapping')
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--per-class', type=int, default=100)
    ap.add_argument('--test-per-class', type=int, default=100, help='官方划分 Test<N>.mat 的 N')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--workers', type=int, default=12)
    args = ap.parse_args()
    spec = scenes.SCENES[args.scene]
    ncls = len(spec['classes'])
    ckpt = Path(args.ckpt)
    if not ckpt.exists():
        ap.error(f'checkpoint not found: {ckpt}')
    _, test_p = scenes.split_paths(args.scene, args.test_per_class)
    test_mask = preprocess.load_mat(test_p).astype(np.int64)
    H, W = test_mask.shape
    shape = (H + 2 * PAD, W + 2 * PAD, 270)

    cube_path = ROOT / 'data' / 'scenes' / args.scene / 'cube_f32.bin'
    if cube_path.exists() and cube_path.stat().st_size == int(np.prod(shape)) * 4:
        src = f'data/scenes/{args.scene}/cube_f32.bin'
        init = (args.model, str(ckpt), ncls, str(cube_path), shape)
    else:
        cube_p, gt_p = scenes.raw_paths(args.scene)
        padded = preprocess.Scene(cube_p, gt_p, spec['band_drop']).padded.astype(np.float32)
        assert padded.shape == shape
        src = 'preprocess.Scene (cube_f32.bin absent)'
        init = (args.model, str(ckpt), ncls, None, padded)

    coords = sample(test_mask, args.per_class, args.seed)
    gt = test_mask[coords[:, 0], coords[:, 1]]
    n = len(coords)
    print(f'{args.scene}: {n} test pixels ({args.per_class}/class, seed {args.seed}), cube from {src}')
    t0 = time.time()
    fx = np.zeros((n, ncls)); fl = np.zeros((n, ncls))
    with Pool(args.workers, initializer=_init, initargs=init) as pool:
        for i, (a, b) in enumerate(pool.imap(_one, [tuple(x) for x in coords], chunksize=16)):
            fx[i], fl[i] = a, b
            if i % 500 == 499:
                print(f'  {i + 1}/{n}  {time.time() - t0:.0f}s', flush=True)
    pf, pq = fl.argmax(1) + 1, fx.argmax(1) + 1
    d = np.abs(fx - fl)
    oa_f, aa_f, k_f = metrics(pf, gt, ncls)
    oa_q, aa_q, k_q = metrics(pq, gt, ncls)
    agree = float(np.mean(pf == pq))
    res = dict(scene=args.scene, model=args.model, classes=ncls, pixels=n, per_class=args.per_class, seed=args.seed,
               official_test=test_p.name, cube=src, fmt=FMT_ARGS, ckpt=str(ckpt),
               ckpt_sha256=hashlib.sha256(ckpt.read_bytes()).hexdigest(),
               float=dict(OA=oa_f, AA=aa_f, Kappa=k_f), fixed=dict(OA=oa_q, AA=aa_q, Kappa=k_q),
               label_agree=agree, mismatches=int(np.sum(pf != pq)),
               max_dlogit=float(d.max()), mean_dlogit=float(d.mean()), seconds=int(time.time() - t0))
    tag = f'{args.scene}_{args.model}_{ckpt.stem}'
    out = ROOT / 'data' / 'regress'; out.mkdir(parents=True, exist_ok=True)
    np.savez(out / f'{tag}.npz', coords=coords.astype(np.int32), gt=gt.astype(np.uint8),
             logits_float=fl.astype(np.float32), logits_fixed=fx.astype(np.float32))
    (out / f'{tag}.json').write_text(json.dumps(res, indent=1), encoding='utf-8')

    rep = ROOT / 'report' / 'accuracy_fixed_pc.md'
    if not rep.exists():
        rep.write_text('# PC 定点仿真回归（官方 WHU-Hi Test 划分抽样；D12/W14/M14；输入取板上 float32 立方体）\n\n'
                       '由 model/fixed_regression.py 追加，勿手改。float = 全浮点路径，fixed = PL 定点投影路径，同一 checkpoint。\n\n'
                       '| 日期 | 景 | 类别 | 抽样像素 | OA float | OA fixed | AA fixed | Kappa fixed | 标签一致率 | 不一致数 | max\\|dlogit\\| | mean\\|dlogit\\| | ckpt sha256[:12] |\n'
                       '|---|---|---|---|---|---|---|---|---|---|---|---|---|\n', encoding='utf-8')
    with rep.open('a', encoding='utf-8') as f:
        f.write(f"| {time.strftime('%Y-%m-%d')} | {args.scene} | {ncls} | {n} | {oa_f:.4f} | {oa_q:.4f} | {aa_q:.4f} | {k_q:.4f} | "
                f"{agree:.4f} | {res['mismatches']} | {d.max():.4f} | {d.mean():.5f} | {res['ckpt_sha256'][:12]} |\n")
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
