"""导出板上/HLS 需要的二进制文件到 model/data/。

权重（定点，int16 小端）：
  w_L{l}_{query|key|value|mlp}.bin   3014 个 int16，Q1.14，顺序 M1 M2 M3（行主序）
  weights_all.bin                    12 层 × 4 投影 顺序拼接，PS 一次性读入（12×4×3014×2 = 289 KB）
浮点参数（float32 小端，PS 端用浮点算的部分）：
  cls_token.bin  (7,7,54)      pos_embed.bin (7,7,54,N)     classifier_w.bin (9,2646)   classifier_b.bin (9)
HLS 黄金向量（真实 patch 第 0 层 QKV 与 MLP 两次调用，定点逐位）：
  golden/in_qkv.bin  (D*N) int16    golden/out_{q,k,v}.bin (D*N) int16    golden/w_{q,k,v}.bin
  golden/in_mlp.bin  golden/out_mlp.bin  golden/w_mlp.bin
  golden/meta.txt
PS 端整网参考：
  golden/patch_f32.bin (270,7,7) float32   golden/logits_fixed.bin (9) float64   golden/logits_float.bin
"""
import argparse
from pathlib import Path
import numpy as np
import preprocess
from fixed_point_sim import Net, normalize_np, attention_np
from quant import Fmt, quant, to_block, tucker_proj_int, D, W, J

FMT = Fmt(DF=12, WF=14, MF=14)
OUT = Path(__file__).resolve().parent / 'data'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='unoverlapping')
    ap.add_argument('--pixel', type=int, nargs=2, default=(100, 100))
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    (OUT / 'golden').mkdir(exist_ok=True)
    net = Net(args.model, FMT)
    N = net.N

    # ---- 权重 ----
    allw = []
    for li, L in enumerate(net.layers):
        for nm in ('query', 'key', 'value', 'mlp'):
            w = L[nm]['q'].astype('<i2')
            w.tofile(OUT / f'w_L{li}_{nm}.bin')
            allw.append(w)
    np.concatenate(allw).tofile(OUT / 'weights_all.bin')
    net.cls[..., 0].astype('<f4').tofile(OUT / 'cls_token.bin')
    net.pos.astype('<f4').tofile(OUT / 'pos_embed.bin')
    net.cw.astype('<f4').tofile(OUT / 'classifier_w.bin')
    net.cb.astype('<f4').tofile(OUT / 'classifier_b.bin')

    # ---- 真实 patch，走定点路径并抓第 0 层 ----
    lk = preprocess.LongKou()
    i, j = args.pixel
    patch = lk.patch(i, j)
    patch.astype('<f4').tofile(OUT / 'golden' / 'patch_f32.bin')
    x = net.embed(patch.astype(np.float64))
    L0 = net.layers[0]
    xn = normalize_np(x)
    xq = quant(xn, FMT.DF)                                    # PL 输入 int
    to_block(xq).astype('<i2').tofile(OUT / 'golden' / 'in_qkv.bin')
    outs = {}
    for nm, tag in (('query', 'q'), ('key', 'k'), ('value', 'v')):
        y = tucker_proj_int(xq, L0[nm]['q'], FMT)
        outs[nm] = y
        to_block(y).astype('<i2').tofile(OUT / 'golden' / f'out_{tag}.bin')
        L0[nm]['q'].astype('<i2').tofile(OUT / 'golden' / f'w_{tag}.bin')
    q, k, v = (outs[nm] / FMT.scale for nm in ('query', 'key', 'value'))
    ctx = attention_np(q, k, v)
    xn2 = normalize_np(xn + ctx)
    xq2 = quant(xn2, FMT.DF)
    to_block(xq2).astype('<i2').tofile(OUT / 'golden' / 'in_mlp.bin')
    to_block(tucker_proj_int(xq2, L0['mlp']['q'], FMT)).astype('<i2').tofile(OUT / 'golden' / 'out_mlp.bin')
    L0['mlp']['q'].astype('<i2').tofile(OUT / 'golden' / 'w_mlp.bin')

    trace = []
    lf = net.forward(patch.astype(np.float64), fixed=True, trace=trace)
    ff = net.forward(patch.astype(np.float64), fixed=False)
    lf.astype('<f8').tofile(OUT / 'golden' / 'logits_fixed.bin')
    ff.astype('<f8').tofile(OUT / 'golden' / 'logits_float.bin')
    # 每层输出 x（定点路径，float64），PS 逐层对拍用
    np.stack([t['x'] for t in trace]).astype('<f8').tofile(OUT / 'golden' / 'layer_out_fixed.bin')

    (OUT / 'golden' / 'meta.txt').write_text(
        f'model={args.model}\nN={N}\nD={D}\nDF={FMT.DF}\nWF={FMT.WF}\nMF={FMT.MF}\n'
        f'pixel={i},{j}\ngt={lk.gt[i, j]}\nargmax_fixed={lf.argmax()}\nargmax_float={ff.argmax()}\n'
        f'logits_fixed={lf.tolist()}\nlogits_float={ff.tolist()}\n')
    print(open(OUT / 'golden' / 'meta.txt').read())
    print('in_qkv range', xq.min(), xq.max(), '| out ranges',
          {nm: (int(outs[nm].min()), int(outs[nm].max())) for nm in outs})


if __name__ == '__main__':
    main()
