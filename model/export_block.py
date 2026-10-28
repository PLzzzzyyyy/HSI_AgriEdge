"""导出 64×64 块推理所需的数据、PC 参考和 C 数组。

输出到 model/data/block/：
  region_f32.bin       (S+6, S+6, 270) float32，预处理（高斯、全图归一化、零填充）后的图块，HWC 内存序；
                       板上按 preprocess.patch_tensor 的语义自己取 7×7 窗、转 CHW、做 patch 级归一化
  gt_u8.bin            (S, S) uint8 真值（0 = 无标签）
  ref_fixed_u8.bin     (S, S) uint8 PC 定点仿真的 argmax+1（板上参考）
  ref_float_u8.bin     (S, S) uint8 PC 全浮点路径的 argmax+1
  ref_fixed_logits.bin (S*S, 9) float64
  meta.txt
以及 src/ps/tt_block_data.h / .c（真值与参考的 C 数组；图块用 .incbin 直接嵌进 elf，路径为绝对路径）。

用法：D:/pytorch/python.exe export_block.py [--size 64] [--origin r c] [--workers 12] [--model unoverlapping]
     D:/pytorch/python.exe model/export_block.py --c-only  # 校验已有 bin，只重生成 C，不重算参考
不给 --origin 时自动选：64×64 窗内出现类别数最多（每类至少 min_px 个像素），并列取有标签比例最高的。
"""
import argparse
import hashlib
import json
import time
from multiprocessing import Pool
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'model' / 'data' / 'block'
SRC = ROOT / 'src' / 'ps'
NCLS = 9
SCENE_SHAPE = (550, 400)  # WHU-Hi LongKou；当前板上入口固定为 unoverlapping / N=6


def validate_geometry(size, row, col, shape=SCENE_SHAPE):
    if size != 64:
        raise ValueError('the current board block entry supports only 64 x 64')
    if row < 0 or col < 0 or row + size > shape[0] or col + size > shape[1]:
        raise ValueError(f'block origin ({row}, {col}), size {size} is outside scene {shape}')


def read_existing():
    """Validate existing payloads before generating C; never modifies the saved references."""
    meta = dict(line.split('=', 1) for line in (OUT / 'meta.txt').read_text(encoding='utf-8').splitlines() if line)
    if meta.get('model') != 'unoverlapping':
        raise ValueError('the current board block entry supports only unoverlapping (N=6)')
    for name in ('size', 'row0', 'col0'):
        meta[name] = int(meta[name])
    size = meta['size']
    validate_geometry(size, meta['row0'], meta['col0'])
    spec = {
        'region_f32.bin': ('<f4', (size + 6, size + 6, 270)),
        'gt_u8.bin': ('u1', (size, size)),
        'ref_fixed_u8.bin': ('u1', (size, size)),
        'ref_float_u8.bin': ('u1', (size, size)),
        'ref_fixed_logits.bin': ('<f8', (size * size, NCLS)),
    }
    arrays, hashes = {}, {}
    for name, (dtype, shape) in spec.items():
        path = OUT / name
        raw = path.read_bytes()
        expected = int(np.prod(shape)) * np.dtype(dtype).itemsize
        if len(raw) != expected:
            raise ValueError(f'{name}: expected {expected} bytes, found {len(raw)}')
        value = np.frombuffer(raw, dtype=dtype).reshape(shape)
        if not np.isfinite(value).all():
            raise ValueError(f'{name}: non-finite values')
        if name.endswith('_u8.bin'):
            minimum = 0 if name == 'gt_u8.bin' else 1
            if np.any(value < minimum) or np.any(value > NCLS):
                raise ValueError(f'{name}: labels must be in {minimum}..{NCLS}')
        arrays[name] = value
        hashes[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if not np.array_equal(arrays['ref_fixed_logits.bin'].argmax(axis=1) + 1,
                          arrays['ref_fixed_u8.bin'].ravel()):
        raise ValueError('ref_fixed_u8.bin does not match argmax(ref_fixed_logits.bin) + 1')
    return meta, arrays, hashes


def pick_window(gt, size, min_px=50, stride=4):
    """滑窗统计每类像素数（积分图），返回 (r0, c0, 类别数, 有标签比例)。"""
    H, W = gt.shape
    if size <= 0 or size > min(H, W) or stride <= 0 or min_px < 1:
        raise ValueError('invalid window size, stride or minimum class count')
    integ = np.zeros((NCLS + 1, H + 1, W + 1), np.int64)
    for k in range(NCLS + 1):
        integ[k, 1:, 1:] = np.cumsum(np.cumsum(gt == k, 0), 1)
    best = None
    for r in range(0, H - size + 1, stride):
        for c in range(0, W - size + 1, stride):
            cnt = integ[:, r + size, c + size] - integ[:, r, c + size] - integ[:, r + size, c] + integ[:, r, c]
            ncls = int(np.sum(cnt[1:] >= min_px))
            labeled = 1.0 - cnt[0] / (size * size)
            key = (ncls, labeled)
            if best is None or key > best[0]:
                best = (key, r, c)
    (ncls, labeled), r, c = best
    return r, c, ncls, labeled


_net = None
_region = None


def _init(model, region):
    global _net, _region
    import torch
    torch.set_num_threads(1)
    from fixed_point_sim import Net
    from quant import Fmt
    _net = Net(model, Fmt(DF=12, WF=14, MF=14))
    _region = region


def _one(args):
    import preprocess
    r, c = args
    patch = preprocess.patch_tensor(_region, r, c).astype(np.float64)
    lf = _net.forward(patch, fixed=True)
    ff = _net.forward(patch, fixed=False)
    return r, c, lf, ff


def write_c(meta, gt, ref):
    S = gt.shape[0]
    validate_geometry(S, int(meta['row0']), int(meta['col0']))
    if meta['model'] != 'unoverlapping' or gt.shape != (S, S) or ref.shape != gt.shape:
        raise ValueError('C export requires a 64 x 64 unoverlapping block and matching maps')
    region_path = (OUT / 'region_f32.bin').resolve().as_posix()
    h = f'''// 由 model/export_block.py 生成，勿手改
#ifndef TT_BLOCK_DATA_H
#define TT_BLOCK_DATA_H
#include <stdint.h>
#define TT_BLOCK_SIZE {S}
#define TT_BLOCK_ROW0 {meta["row0"]}
#define TT_BLOCK_COL0 {meta["col0"]}
#define TT_BLOCK_PAD 3
#define TT_BLOCK_RW (TT_BLOCK_SIZE + 2 * TT_BLOCK_PAD)      // 图块边长 {S + 6}
#define TT_BLOCK_BANDS 270
#define TT_BLOCK_MODEL "{meta["model"]}"
#define TT_BLOCK_N 6
extern const float tt_block_region[];      // [RW][RW][270] float32 HWC，预处理后、patch 归一化前
extern const uint8_t tt_block_gt[];        // [S][S] 0 = 无标签
extern const uint8_t tt_block_ref[];       // [S][S] PC 定点仿真 argmax+1
#endif
'''
    (SRC / 'tt_block_data.h').write_text(h, encoding='utf-8')

    def arr(name, a):
        a = np.asarray(a).ravel()
        lines = [f'const uint8_t {name}[{len(a)}] = {{']
        for i in range(0, len(a), 64):
            lines.append('  ' + ','.join(str(int(v)) for v in a[i:i + 64]) + ',')
        lines.append('};\n')
        return '\n'.join(lines)

    # JSON quoting also produces valid C string literals, with exactly one level
    # of escaping. The assembler receives newlines and quotes around the path.
    asm_lines = ['.section .rodata', '.balign 32', '.global tt_block_region',
                 'tt_block_region:', f'.incbin "{region_path}"',
                 '.size tt_block_region, . - tt_block_region', '.previous']
    asm_text = '\n'.join('    ' + json.dumps(line + '\n') for line in asm_lines)
    c = f'''// 由 model/export_block.py 生成，勿手改
// 图块 {region_path} 用 .incbin 直接进 .rodata（约 {(S + 6) * (S + 6) * 270 * 4 // 1024} KB），32 字节对齐。
#include "tt_block_data.h"
#if defined(__arm__) || defined(__aarch64__)
__asm__(
{asm_text});
#endif
{arr("tt_block_gt", gt)}
{arr("tt_block_ref", ref)}'''
    (SRC / 'tt_block_data.c').write_text(c, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', choices=['unoverlapping'], default='unoverlapping')
    ap.add_argument('--size', type=int, choices=[64], default=64)
    ap.add_argument('--origin', type=int, nargs=2)
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--c-only', action='store_true', help='validate existing bin files and regenerate only tt_block_data.c/.h')
    args = ap.parse_args()
    if args.workers < 1:
        ap.error('--workers must be positive')
    try:
        if args.origin:
            validate_geometry(args.size, *args.origin)
        if args.c_only:
            meta, arrays, hashes = read_existing()
            if args.origin and tuple(args.origin) != (meta['row0'], meta['col0']):
                raise ValueError('--origin conflicts with the saved block; --c-only cannot replace data')
            write_c(meta, arrays['gt_u8.bin'], arrays['ref_fixed_u8.bin'])
            _, _, after = read_existing()
            if hashes != after:
                raise RuntimeError('saved block inputs changed during C generation')
            print(json.dumps(hashes, indent=2))
            print('C regenerated; saved region and all references are unchanged')
            return
    except (OSError, KeyError, ValueError) as exc:
        ap.error(str(exc))
    import preprocess
    OUT.mkdir(parents=True, exist_ok=True)
    S = args.size
    lk = preprocess.LongKou()
    if lk.gt.shape != SCENE_SHAPE or lk.padded.shape != (SCENE_SHAPE[0] + 6, SCENE_SHAPE[1] + 6, 270):
        ap.error('unexpected LongKou scene dimensions or band count')
    if args.origin:
        r0, c0 = args.origin
        cnt = np.bincount(lk.gt[r0:r0 + S, c0:c0 + S].ravel(), minlength=NCLS + 1)
        ncls, labeled = int(np.sum(cnt[1:] > 0)), 1 - cnt[0] / (S * S)
    else:
        r0, c0, ncls, labeled = pick_window(lk.gt, S)
    print(f'block origin=({r0},{c0}) size={S} classes={ncls} labeled={labeled:.1%}')
    gt = lk.gt[r0:r0 + S, c0:c0 + S].astype(np.uint8)
    region = lk.padded[r0:r0 + S + 6, c0:c0 + S + 6, :]              # float64，padded[i] 对应原图 i-3
    if region.shape != (S + 6, S + 6, 270) or not np.isfinite(region).all():
        ap.error('invalid region dimensions or non-finite pixels')
    region.astype('<f4').tofile(OUT / 'region_f32.bin')
    gt.tofile(OUT / 'gt_u8.bin')
    # 板上会用 float32 图块；参考也从同一份 float32 图块出发，与 lk.patch 完全一致（patch_tensor 先 astype float32）
    region32 = region.astype(np.float32)
    assert np.array_equal(preprocess.patch_tensor(region32, 5, 7), lk.patch(r0 + 5, c0 + 7))

    t = time.time()
    coords = [(r, c) for r in range(S) for c in range(S)]
    ref_fixed = np.zeros((S, S), np.uint8); ref_float = np.zeros((S, S), np.uint8)
    logits = np.zeros((S * S, NCLS), np.float64)
    with Pool(args.workers, initializer=_init, initargs=(args.model, region32)) as pool:
        for i, (r, c, lf, ff) in enumerate(pool.imap(_one, coords, chunksize=16)):
            ref_fixed[r, c] = lf.argmax() + 1
            ref_float[r, c] = ff.argmax() + 1
            logits[r * S + c] = lf
            if i % 512 == 511:
                print(f'  {i + 1}/{S * S}  {time.time() - t:.0f}s')
    ref_fixed.tofile(OUT / 'ref_fixed_u8.bin'); ref_float.tofile(OUT / 'ref_float_u8.bin')
    logits.astype('<f8').tofile(OUT / 'ref_fixed_logits.bin')
    lab = gt > 0
    oa_fixed = np.mean(ref_fixed[lab] == gt[lab]); oa_float = np.mean(ref_float[lab] == gt[lab])
    agree = np.mean(ref_fixed == ref_float)
    meta = dict(model=args.model, size=S, row0=r0, col0=c0, classes=ncls, labeled=f'{labeled:.4f}',
                oa_fixed=f'{oa_fixed:.4f}', oa_float=f'{oa_float:.4f}', fixed_vs_float_agree=f'{agree:.4f}',
                seconds=f'{time.time() - t:.0f}')
    (OUT / 'meta.txt').write_text(''.join(f'{k}={v}\n' for k, v in meta.items()), encoding='utf-8')
    print((OUT / 'meta.txt').read_text(encoding='utf-8'))
    read_existing()
    write_c(meta, gt, ref_fixed)
    print('written', SRC / 'tt_block_data.c', SRC / 'tt_block_data.h')


if __name__ == '__main__':
    main()
