"""把 LongKou 数据集和预测结果画成图片：model/data/vis/
  lk_rgb.png      假彩色（取 3 个波段近似 R/G/B，2% 分位拉伸）
  lk_gt.png       真值 9 类
  lk_pred_*.png   仓库自带的两个模型预测图（过滤前）
  lk_golden.png   假彩色 + 黄金 patch 像素 (224,158) 的位置和 7×7 窗
用法：D:/pytorch/python.exe visualize.py
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle
import preprocess

OUT = Path(__file__).resolve().parent / 'data' / 'vis'
UP = 'D:/FPGAlearn/Tensor-Transformer-for-HSIC-master/Tensor-Transformer-for-HSIC-master/'
CLASSES = ['unlabeled', 'Corn', 'Cotton', 'Sesame', 'Broad-leaf soybean', 'Narrow-leaf soybean',
           'Rice', 'Water', 'Roads and houses', 'Mixed weed']
COLORS = ['#000000', '#ff0000', '#ee9a00', '#ffff00', '#00ff00', '#00ffcf',
          '#00a0ff', '#0000ff', '#b000ff', '#ffb6c1']
CMAP = ListedColormap(COLORS)


def false_color(cube):
    # 270 波段 400~1000nm，约 2.22 nm/波段：R≈650nm→112，G≈550nm→67，B≈470nm→31
    rgb = np.stack([cube[:, :, b] for b in (112, 67, 31)], -1).astype(np.float64)
    lo, hi = np.percentile(rgb, 2), np.percentile(rgb, 98)
    return np.clip((rgb - lo) / (hi - lo), 0, 1)


def save_label(arr, path, title):
    fig, ax = plt.subplots(figsize=(5, 6.5))
    ax.imshow(arr, cmap=CMAP, vmin=0, vmax=9, interpolation='nearest')
    ax.set_title(title); ax.axis('off')
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[i]) for i in range(1, 10)]
    ax.legend(handles, CLASSES[1:], loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize=7, frameon=False)
    fig.savefig(path, dpi=150, bbox_inches='tight'); plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cube = preprocess.load_mat(preprocess.DATA)
    gt = preprocess.load_mat(preprocess.GT).astype(np.int64)
    rgb = false_color(cube)
    plt.imsave(OUT / 'lk_rgb.png', rgb)
    save_label(gt, OUT / 'lk_gt.png', 'WHU-Hi-LongKou ground truth (550x400, 9 classes)')
    for name in ('unoverlapping', 'overlapping'):
        pred = preprocess.load_mat(UP + f'TensorTransformerHSI_{name}_LK_predict_result.mat').astype(np.int64)
        oa = np.mean(pred[gt > 0] == gt[gt > 0])
        save_label(pred, OUT / f'lk_pred_{name}.png', f'TT {name} prediction (OA {oa:.1%}, from upstream .mat)')
    # 黄金 patch 位置
    i, j = 20, 20
    fig, ax = plt.subplots(figsize=(5, 6.5))
    ax.imshow(rgb); ax.add_patch(Rectangle((j - 3.5, i - 3.5), 7, 7, fill=False, color='yellow', lw=1.5))
    ax.plot(j, i, 'r+', ms=12, mew=1.5)
    ax.set_title(f'golden patch: pixel ({i},{j}), gt={gt[i, j]} {CLASSES[gt[i, j]]}'); ax.axis('off')
    fig.savefig(OUT / 'lk_golden.png', dpi=150, bbox_inches='tight'); plt.close(fig)
    # 放大局部 41×41
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.imshow(rgb[i - 20:i + 21, j - 20:j + 21], interpolation='nearest')
    ax.add_patch(Rectangle((20 - 3.5, 20 - 3.5), 7, 7, fill=False, color='yellow', lw=2))
    ax.set_title('golden patch 7x7 window (zoom)'); ax.axis('off')
    fig.savefig(OUT / 'lk_golden_zoom.png', dpi=150, bbox_inches='tight'); plt.close(fig)
    print('written to', OUT); print(sorted(p.name for p in OUT.iterdir()))


if __name__ == '__main__':
    main()
