"""一景一次导出板上 SD 卡镜像与地面站底图（PLAN §14）。

data/scenes/<scene>/                      不入库，整目录拷到 SD 卡 /scenes/<scene>/
  cube_f32.bin        (H+6, W+6, 270) float32 HWC，高斯 + 全景归一化 + 3 像素零边；板上按 preprocess.patch_tensor 取窗
  gt_u8.bin           (H, W) uint8，0 = 无标签
  meta.txt            尺寸、类别、权重版本、各文件 sha256
  weights/<ver>/weights_all.bin                       12 层 × 4 投影 × 3014 int16 Q1.14，IP 装载
  weights/<ver>/{cls_token,pos_embed,classifier_w,classifier_b}.bin   float32，PS 用
gcs/scenes/<scene>/                       入库
  rgb.png             假彩色底图；palette.json 类别名、颜色、尺寸

用法：D:/pytorch/python.exe model/export_scene.py --scene longkou [--model unoverlapping] [--ckpt x.pth]
      [--weights-version v1] [--skip-cube]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess
import scenes
from fixed_point_sim import Net
from quant import Fmt, D

FMT = Fmt(DF=12, WF=14, MF=14)
ROOT = scenes.ROOT
PAD = preprocess.HALF


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_weights(net, out):
    out.mkdir(parents=True, exist_ok=True)
    allw = np.concatenate([net.layers[li][nm]['q'].astype('<i2')
                           for li in range(len(net.layers)) for nm in ('query', 'key', 'value', 'mlp')])
    allw.tofile(out / 'weights_all.bin')
    net.cls[..., 0].astype('<f4').tofile(out / 'cls_token.bin')
    net.pos.astype('<f4').tofile(out / 'pos_embed.bin')
    net.cw.astype('<f4').tofile(out / 'classifier_w.bin')
    net.cb.astype('<f4').tofile(out / 'classifier_b.bin')


def engine_package(eng):
    """weights_engine.bin（src/hls/tt_engine_regs.h 段布局）：eng = engine_ref.Engine（num 16 或 8）。返回 uint8 数组。"""
    from engine_ref import NCLS_MAX
    num = eng.cfg.num
    total = 191232 + (289344 if num == 16 else 144832)
    buf = np.zeros(total, np.uint8)

    def put(off, arr):
        b = np.ascontiguousarray(arr).view(np.uint8)
        buf[off:off + b.size] = b
    wq, e, b = eng.hw
    ncls = eng.ncls
    assert ncls <= NCLS_MAX and np.abs(e).max() < 128
    put(0, np.array([0x32455454, 2, ncls, num], '<u4'))
    eh = np.zeros(NCLS_MAX, np.int8); eh[:ncls] = e
    put(32, eh)
    put(64, eng.emb.astype('<i4').reshape(-1))
    hb = np.zeros(NCLS_MAX, '<i4'); hb[:ncls] = b
    put(63616, hb)
    for c in range(ncls):
        put(63744 + c * 5312, wq[c].astype('<i2'))
    if num == 16:
        put(191232, np.concatenate([np.concatenate([m.reshape(-1) for m in w[:3]]) for row in eng.wp for w in row]).astype('<i2'))
    else:
        put(191232, np.concatenate([np.concatenate([m.reshape(-1) for m in w[:3]]) for row in eng.wp for w in row]).astype(np.int8))
        put(191232 + 144672, np.array([x for row in eng.wp for w in row for x in w[3]], np.int8))
    return buf


def write_engine(eng, out, name):
    out.mkdir(parents=True, exist_ok=True)
    engine_package(eng).tofile(out / name)


def write_gcs(name, spec, scene, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out.mkdir(parents=True, exist_ok=True)
    rgb = np.stack([scene.raw[:, :, b] for b in spec['rgb_bands']], -1).astype(np.float64)
    lo, hi = np.percentile(rgb, 2), np.percentile(rgb, 98)
    plt.imsave(out / 'rgb.png', np.clip((rgb - lo) / (hi - lo), 0, 1))
    ncls = len(spec['classes'])
    (out / 'palette.json').write_text(json.dumps(dict(
        scene=name, height=int(scene.gt.shape[0]), width=int(scene.gt.shape[1]), bands=270,
        classes=['unlabeled'] + spec['classes'], colors=scenes.PALETTE[:ncls + 1],
        rgb_bands=list(spec['rgb_bands'])), indent=1, ensure_ascii=False), encoding='utf-8')


def export_engine(args, spec, out, ncls):
    import engine_ref
    c32, c16, k, _ = engine_ref.scene_cube(args.scene)
    i16 = out / 'cube_i16.bin'
    if not isinstance(c16, np.memmap):
        c16.tofile(i16)
    ckpt = args.ckpt or spec['ckpt'].get(args.model)
    if not ckpt or not Path(ckpt).exists():
        sys.exit(f'checkpoint not found: {ckpt}')
    eng = engine_ref.Engine(str(ckpt), ncls, num=args.num)
    ver = args.weights_version + ('_int8' if args.num == 8 else '')
    rel = f'weights/{ver}/weights_engine.bin'
    write_engine(eng, out / 'weights' / ver, 'weights_engine.bin')
    meta_p = out / 'meta.txt'
    lines = [l for l in meta_p.read_text(encoding='utf-8').splitlines()
             if not l.startswith(('cube_k=', 'sha256:cube_i16.bin=', f'sha256:{rel}=', f'engine_ckpt:{ver}='))]
    lines += [f'cube_k={"bfp" if k is None else k}', f'sha256:cube_i16.bin={sha256(i16)}', f'sha256:{rel}={sha256(out / rel)}', f'engine_ckpt:{ver}={ckpt}']
    meta_p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{args.scene}: cube_k={k}, {rel} {(out / rel).stat().st_size} B, head e={eng.hw[1].tolist()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', required=True, choices=list(scenes.SCENES))
    ap.add_argument('--model', default='unoverlapping')
    ap.add_argument('--ckpt', help='覆盖 scenes.py 里的 checkpoint 路径')
    ap.add_argument('--weights-version', default='v1')
    ap.add_argument('--skip-cube', action='store_true', help='只重导权重与 gcs，立方体与真值沿用已有文件')
    ap.add_argument('--no-weights', action='store_true', help='还没有 checkpoint 的景：只导立方体、真值、gcs')
    ap.add_argument('--engine-only', action='store_true',
                    help='只导整网引擎文件（不读 .mat）：cube_i16.bin（由已有 cube_f32.bin）与 weights/<ver>/weights_engine.bin，meta 追加 cube_k 与 sha256')
    ap.add_argument('--num', type=int, default=16, choices=[16, 8],
                    help='--engine-only 的权重位宽；8 写到 weights/<ver>_int8/（int8 版，QAT checkpoint 用 --ckpt 给）')
    args = ap.parse_args()
    spec = scenes.SCENES[args.scene]
    out = ROOT / 'data' / 'scenes' / args.scene
    out.mkdir(parents=True, exist_ok=True)
    ncls = len(spec['classes'])
    if args.engine_only:
        export_engine(args, spec, out, ncls)
        return

    cube_path, gt_path = scenes.raw_paths(args.scene)
    scene = preprocess.Scene(cube_path, gt_path, spec['band_drop'])
    H, W = scene.gt.shape
    if scene.padded.shape != (H + 2 * PAD, W + 2 * PAD, 270):
        ap.error(f'unexpected padded shape {scene.padded.shape}')
    if scene.gt.max() != ncls or scene.gt.min() < 0:
        ap.error(f'gt has {scene.gt.max()} classes, scenes.py lists {ncls}')
    if not args.skip_cube:
        scene.padded.astype('<f4').tofile(out / 'cube_f32.bin')
        scene.gt.astype(np.uint8).tofile(out / 'gt_u8.bin')
        # 板上会从 float32 立方体取窗，参考也必须从同一份 float32 出发
        cube32 = np.fromfile(out / 'cube_f32.bin', dtype='<f4').reshape(scene.padded.shape)
        i, j = H // 2, W // 2
        assert np.array_equal(preprocess.patch_tensor(cube32, i, j), scene.patch(i, j))

    write_gcs(args.scene, spec, scene, ROOT / 'gcs' / 'scenes' / args.scene)
    if args.no_weights:
        meta = dict(scene=args.scene, H=H, W=W, pad=PAD, bands=270, band_drop=list(spec['band_drop']), classes=ncls,
                    weights_version='none', cube_source=str(cube_path), gt_source=str(gt_path))
        for f in ('cube_f32.bin', 'gt_u8.bin'):
            meta[f'sha256:{f}'] = sha256(out / f)
        (out / 'meta.txt').write_text(''.join(f'{k}={v}\n' for k, v in meta.items()), encoding='utf-8')
        print((out / 'meta.txt').read_text(encoding='utf-8'))
        return

    ckpt = args.ckpt or spec['ckpt'].get(args.model)
    if not ckpt or not Path(ckpt).exists():
        ap.error(f'checkpoint not found: {ckpt}')
    net = Net(args.model, FMT, ckpt=ckpt, classes=ncls)
    if net.cw.shape != (ncls, D):
        ap.error(f'classifier shape {net.cw.shape} != ({ncls}, {D})')
    wdir = out / 'weights' / args.weights_version
    write_weights(net, wdir)

    files = ['cube_f32.bin', 'gt_u8.bin'] + [f'weights/{args.weights_version}/{f}' for f in
             ('weights_all.bin', 'cls_token.bin', 'pos_embed.bin', 'classifier_w.bin', 'classifier_b.bin')]
    meta = dict(scene=args.scene, model=args.model, H=H, W=W, pad=PAD, bands=270, band_drop=list(spec['band_drop']),
                classes=ncls, N=net.N, D=D, DF=FMT.DF, WF=FMT.WF, MF=FMT.MF,
                weights_version=args.weights_version, ckpt=str(ckpt), ckpt_sha256=sha256(ckpt),
                cube_source=str(cube_path), gt_source=str(gt_path),
                cube_bytes=(out / 'cube_f32.bin').stat().st_size, gt_bytes=(out / 'gt_u8.bin').stat().st_size)
    for f in files:
        meta[f'sha256:{f}'] = sha256(out / f)
    (out / 'meta.txt').write_text(''.join(f'{k}={v}\n' for k, v in meta.items()), encoding='utf-8')
    print((out / 'meta.txt').read_text(encoding='utf-8'))

    # LongKou 的 v1 权重（上游 checkpoint）必须与 7020 时期 model/data 下的完全一致（csim 与主机回归在用）；
    # 自训权重导成 v2 及以后，不做此检查
    old = ROOT / 'model' / 'data' / 'weights_all.bin'
    if args.scene == 'longkou' and args.weights_version == 'v1' and old.exists():
        same = all(sha256(wdir / f) == sha256(ROOT / 'model' / 'data' / f) for f in
                   ('weights_all.bin', 'cls_token.bin', 'pos_embed.bin', 'classifier_w.bin', 'classifier_b.bin'))
        print('weights identical to model/data:', same)
        if not same:
            sys.exit('weight export changed; do not use before understanding why')


if __name__ == '__main__':
    main()
