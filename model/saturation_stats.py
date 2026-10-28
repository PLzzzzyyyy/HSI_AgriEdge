"""统计 fixed_regression.py 抽的同一批像素里，浮点路径激活超出 data_t Q3.12（±8）的比例与幅度（B2 收尾，D1 定数值格式的依据）。

用法：D:/pytorch/python.exe model/saturation_stats.py   # 先跑过三景 fixed_regression
"""
import sys
from pathlib import Path
from multiprocessing import Pool
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import preprocess

LIM = 8.0
_net = _cube = None


def init(scene, ckpt, ncls, shape):
    global _net, _cube
    import torch; torch.set_num_threads(1)
    from fixed_point_sim import Net
    from quant import Fmt
    _net = Net('unoverlapping', Fmt(DF=12, WF=14, MF=14), ckpt=ckpt, classes=ncls)
    _cube = np.memmap(ROOT / 'data' / 'scenes' / scene / 'cube_f32.bin', dtype='<f4', mode='r', shape=shape)


def one(rc):
    tr = []
    _net.forward(preprocess.patch_tensor(_cube, *rc).astype(np.float64), fixed=False, trace=tr)
    m = max(max(np.abs(t['xn']).max(), np.abs(t['xn2']).max()) for t in tr)
    n = sum(int((np.abs(t['xn']) > LIM).sum() + (np.abs(t['xn2']) > LIM).sum()) for t in tr)
    return m, n


if __name__ == '__main__':
    for scene, ncls, shape in (('longkou', 9, (556, 406, 270)), ('honghu', 22, (946, 481, 270)), ('hanchuan', 16, (1223, 309, 270))):
        z = np.load(ROOT / 'data' / 'regress' / f'{scene}_unoverlapping_{scene}_unoverlapping_s0.npz')
        with Pool(12, initializer=init, initargs=(scene, str(ROOT / 'data' / 'ckpt' / f'{scene}_unoverlapping_s0.pth'), ncls, shape)) as p:
            r = np.array(p.map(one, [tuple(c) for c in z['coords']], chunksize=16))
        d = np.abs(z['logits_fixed'].astype(np.float64) - z['logits_float']).max(1)
        sat = r[:, 1] > 0
        print(f'{scene}: pixels {len(r)}  any-saturation {sat.mean():.3%} ({sat.sum()})  max|x| {r[:, 0].max():.1f}  '
              f'p99 max|x| {np.percentile(r[:, 0], 99):.1f}  max|dlogit| sat/unsat {d[sat].max() if sat.any() else 0:.3f}/{d[~sat].max():.3f}', flush=True)
