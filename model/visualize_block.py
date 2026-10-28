"""Render the exported block predictions on the PC; no board results are implied.

Run from the repository root: D:/pytorch/python.exe model/visualize_block.py
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
import numpy as np
from PIL import Image

import preprocess
from visualize import COLORS, CLASSES, CMAP

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--block', type=Path, default=ROOT / 'model/data/block')
    parser.add_argument('--out', type=Path, default=ROOT / 'board/7020/block_pc_preview')
    parser.add_argument('--host', type=Path, help='Directory containing validated C++ host block results')
    args = parser.parse_args()
    meta = dict(line.split('=', 1) for line in (args.block / 'meta.txt').read_text().splitlines() if '=' in line)
    size, row, col = (int(meta[key]) for key in ('size', 'row0', 'col0'))
    gt = np.fromfile(args.block / 'gt_u8.bin', dtype=np.uint8).reshape(size, size)
    pred = np.fromfile(args.block / 'ref_fixed_u8.bin', dtype=np.uint8).reshape(size, size)
    floating = np.fromfile(args.block / 'ref_float_u8.bin', dtype=np.uint8).reshape(size, size)
    logits = np.fromfile(args.block / 'ref_fixed_logits.bin', dtype='<f8').reshape(size, size, 9)
    if not np.isfinite(logits).all() or not np.array_equal(logits.argmax(axis=2) + 1, pred):
        raise ValueError('Exported labels do not match the finite fixed-point logits')
    reference = pred.copy()
    source = 'PC double glue + fixed-point projection simulation; not board output'
    title = 'PC fixed-point prediction'
    host_report = None
    if args.host:
        host_report = json.loads((args.host / 'host_report.json').read_text(encoding='utf-8'))
        if host_report.get('pixels') != size * size or host_report.get('origin') != [row, col]:
            raise ValueError('Host report refers to a different or incomplete block')
        for name, digest in host_report['source_sha256'].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f'Host validation is stale for {name}')
        pred = np.fromfile(args.host / 'host_labels_u8.bin', dtype=np.uint8).reshape(size, size)
        host_logits = np.fromfile(args.host / 'host_logits_f32.bin', dtype='<f4').reshape(size, size, 9)
        if not np.isfinite(host_logits).all() or not np.array_equal(host_logits.argmax(axis=2) + 1, pred):
            raise ValueError('Host labels disagree with finite host logits')
        source = 'PC C++ float32 glue + integer projection simulation; not board output'
        title = 'PC C++ prediction'
    full_gt = preprocess.load_mat(preprocess.GT).astype(np.uint8)
    if not np.array_equal(full_gt[row:row + size, col:col + size], gt):
        raise ValueError('Block coordinates do not match the original ground truth')
    args.out.mkdir(parents=True, exist_ok=True)
    palette = np.array([[int(color[k:k + 2], 16) for k in (1, 3, 5)] for color in COLORS], dtype=np.uint8)
    for name, labels in [('pc_prediction', pred), ('ground_truth', gt)]:
        picture = Image.fromarray(palette[labels])
        picture.save(args.out / f'{name}_{size}x{size}.png')
        enlarged = picture.resize((512, 512), Image.Resampling.NEAREST)
        enlarged.save(args.out / f'{name}_512.png')
        enlarged.save(args.out / f'{name}_512.bmp')

    valid = gt > 0
    correct, labeled = int(((pred == gt) & valid).sum()), int(valid.sum())
    oa = correct / labeled if labeled else None
    fig, axes = plt.subplots(1, 3, figsize=(12, 6), gridspec_kw={'width_ratios': [1, 1, 1]})
    axes[0].imshow(full_gt, cmap=CMAP, vmin=0, vmax=9, interpolation='nearest')
    for color, width in [('black', 4), ('white', 2)]:
        axes[0].add_patch(Rectangle((col - .5, row - .5), size, size, fill=False, edgecolor=color, lw=width))
    axes[0].set_title(f'Location on full ground truth\nrows {row}:{row + size - 1}, cols {col}:{col + size - 1}')
    axes[1].imshow(gt, cmap=CMAP, vmin=0, vmax=9, interpolation='nearest')
    axes[1].set_title(f'Ground truth: {size} x {size}\nblack = unlabeled')
    axes[2].imshow(pred, cmap=CMAP, vmin=0, vmax=9, interpolation='nearest')
    axes[2].set_title(f'{title}\n{correct}/{labeled} labeled pixels correct ({oa:.2%})')
    for axis in axes:
        axis.axis('off')
    fig.suptitle(f'LongKou {meta["model"]} | PC simulation, not board output', fontsize=13)
    fig.legend(handles=[Patch(color=COLORS[i], label=f'{i}: {CLASSES[i]}') for i in range(10)],
               loc='lower center', ncol=5, fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, .13, 1, .95))
    fig.savefig(args.out / 'block_pc_overview.png', dpi=150, facecolor='white')
    plt.close(fig)
    summary = {'source': source,
               'model': meta['model'], 'origin_zero_based': [row, col], 'size': size,
               'pixels': size * size, 'labeled_pixels': labeled, 'correct_labeled_pixels': correct,
               'labeled_accuracy': oa, 'prediction_vs_pc_float_equal_pixels': int((pred == floating).sum()),
               'prediction_vs_pc_fixed_equal_pixels': int((pred == reference).sum()),
               'predicted_label_counts': {CLASSES[i]: int((pred == i).sum()) for i in range(1, 10) if (pred == i).any()}}
    (args.out / 'metrics.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    if host_report:
        (args.out / 'host_validation.json').write_text(json.dumps(host_report, indent=2) + '\n', encoding='utf-8')
        pred.tofile(args.out / 'host_labels_u8.bin')
    print(json.dumps(summary, indent=2))
    print(f'Images written to {args.out}')


if __name__ == '__main__':
    main()
