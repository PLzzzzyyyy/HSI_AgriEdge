"""int8 QAT 评测（PLAN §17 B5）：一景一个 checkpoint，结果追加 report/accuracy_int8_pc.md。

三组数：
  1. 回归像素（fixed_regression 同批，data/regress/<scene>_unoverlapping_<scene>_unoverlapping_s0.npz 的坐标）：
     int8 定点路径（format_scan 的 "all8 pm"，numpy 逐位）对同一 checkpoint 浮点路径的标签一致率、max/mean|dlogit|；
  2. 同批像素：torch 假量化前向（qat.py）对 int8 定点路径的一致率（核对假量化 = 定点语义）；
  3. 官方 Test100 全部像素：浮点 OA、假量化 OA（int8 路径的代理，第 2 组证明二者一致）。
--ckpt 给 s0 浮点 checkpoint 就是 PTQ 对照行。

用法：D:/pytorch/python.exe model/qat_eval.py --scene longkou --ckpt data/ckpt/longkou_qat8_s0.pth [--workers 12] [--limit N]
"""
import argparse
import hashlib
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess
import qat
import scenes
import tt_model
from train_scene import Windows, metrics

ROOT = scenes.ROOT
ALL8 = dict(DF=4, WF='pm', MF=4, DB=8, WB=8, MB=8)
_net = _cube = None


def _init(scene, ckpt, ncls, shape):
    global _net, _cube
    torch.set_num_threads(1)
    from format_scan import make_net
    _net = make_net(ALL8, ckpt, ncls)
    _cube = np.memmap(ROOT / 'data' / 'scenes' / scene / 'cube_f32.bin', dtype='<f4', mode='r', shape=shape)


def _one(rc):
    patch = preprocess.patch_tensor(_cube, *rc).astype(np.float64)
    return _net.forward(patch, fixed=True), _net.forward(patch, fixed=False)


@torch.no_grad()
def logits(model, batches):
    return np.concatenate([model(b.double()).cpu().numpy() for b in batches])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', required=True, choices=list(scenes.SCENES))
    ap.add_argument('--ckpt', required=True)
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--limit', type=int, default=0, help='只取前 N 个回归像素、跳过全 Test（自检用）')
    ap.add_argument('--note', default='')
    args = ap.parse_args()
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    spec = scenes.SCENES[args.scene]
    ncls = len(spec['classes'])
    ckpt = Path(args.ckpt)
    t0 = time.time()
    z = np.load(ROOT / 'data' / 'regress' / f'{args.scene}_unoverlapping_{args.scene}_unoverlapping_s0.npz')
    coords, gt = z['coords'].astype(np.int64), z['gt'].astype(np.int64)
    if args.limit:
        coords, gt = coords[:args.limit], gt[:args.limit]
    _, test_p = scenes.split_paths(args.scene, 100)
    test_mask = preprocess.load_mat(test_p).astype(np.int64)
    H, W = test_mask.shape
    shape = (H + 2 * preprocess.HALF, W + 2 * preprocess.HALF, 270)

    with Pool(args.workers, initializer=_init, initargs=(args.scene, str(ckpt), ncls, shape)) as p:
        res = p.map(_one, [tuple(c) for c in coords], chunksize=8)
    fx = np.stack([r[0] for r in res]); fl = np.stack([r[1] for r in res])
    agree = float(np.mean(fx.argmax(1) == fl.argmax(1)))
    d = np.abs(fx - fl)

    model = tt_model.MODELS['unoverlapping'](ncls).to(device)
    model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True), strict=True)
    model.double().eval()      # float64：float32 的舍入点在 8 位格式下会翻，fp64 与定点路径差 1e-13
    cube = np.memmap(ROOT / 'data' / 'scenes' / args.scene / 'cube_f32.bin', dtype='<f4', mode='r', shape=shape)
    win = Windows(np.asarray(cube))
    bs = 1024
    reg_batches = lambda: (win.batch(coords[i:i + bs], device) for i in range(0, len(coords), bs))
    qat.enable(model)
    tq = logits(model, reg_batches())
    fq_agree = float(np.mean(tq.argmax(1) == fx.argmax(1)))
    fq_dmax = float(np.abs(tq - fx).max())

    row = dict(scene=args.scene, ckpt=ckpt.name, sha=hashlib.sha256(ckpt.read_bytes()).hexdigest()[:12], pixels=len(coords),
               agree=agree, mism=int(np.sum(fx.argmax(1) != fl.argmax(1))), max_d=float(d.max()), mean_d=float(d.mean()),
               oa_fixed_reg=float(np.mean(fx.argmax(1) + 1 == gt)), fq_agree=fq_agree, fq_dmax=fq_dmax)
    if not args.limit:
        tc = np.argwhere(test_mask > 0)
        ty = test_mask[tc[:, 0], tc[:, 1]]
        tb = lambda: (win.batch(tc[i:i + bs], device) for i in range(0, len(tc), bs))
        pq = logits(model, tb()).argmax(1) + 1
        qat.disable(model)
        pf = logits(model, tb()).argmax(1) + 1
        row.update(test_pixels=int(len(tc)), oa_float=metrics(pf, ty, ncls)['OA'], oa_int8=metrics(pq, ty, ncls)['OA'],
                   aa_int8=metrics(pq, ty, ncls)['AA'])
    row['seconds'] = int(time.time() - t0)
    print(json.dumps(row, indent=1), flush=True)
    if args.limit:
        return
    rep = ROOT / 'report' / 'accuracy_int8_pc.md'
    if not rep.exists():
        rep.write_text('# int8 版（W8A8，all8 pm：act Q3.4、mid Q3.4、权重逐矩阵 2 幂 int8）PC 精度\n\n'
                       '由 model/qat_eval.py 追加，勿手改。回归像素 = fixed_regression 同批（每类 ≤100）；一致率 / dlogit 是 int8 定点路径对**同一 checkpoint** 浮点路径；'
                       '假量化核对 = torch 假量化前向（qat.py）对 int8 定点路径；Test OA 在官方 Test100 全部像素上，int8 列用假量化前向（核对列证明与定点一致）。'
                       's0 ckpt 行即 PTQ 对照。\n\n'
                       '| 日期 | 景 | ckpt | sha256[:12] | 回归像素 | 标签一致率 | 不一致数 | max\\|dlogit\\| | mean\\|dlogit\\| | 假量化核对一致率 / max\\|d\\| | Test 像素 | OA float | OA int8 | AA int8 | 备注 |\n'
                       '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n', encoding='utf-8')
    with rep.open('a', encoding='utf-8') as f:
        f.write(f"| {time.strftime('%Y-%m-%d')} | {args.scene} | {row['ckpt']} | {row['sha']} | {row['pixels']} | {row['agree']:.4f} | {row['mism']} | "
                f"{row['max_d']:.4f} | {row['mean_d']:.5f} | {row['fq_agree']:.4f} / {row['fq_dmax']:.4f} | {row['test_pixels']} | "
                f"{row['oa_float']:.4f} | {row['oa_int8']:.4f} | {row['aa_int8']:.4f} | {args.note} |\n")


if __name__ == '__main__':
    main()
