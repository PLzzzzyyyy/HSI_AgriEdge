"""整网定点仿真：PL 算子用 quant.tucker_proj_int（逐位），其余按 PS 端浮点实现。
目的：(1) 选定点格式；(2) 生成 PS 端行为的参考（src/ps 的 C 实现必须与此一致）。

用法：D:/pytorch/python.exe fixed_point_sim.py [--model unoverlapping] [--patches 200]
"""
import argparse
import numpy as np
import torch
import tt_model
from quant import Fmt, quant, dequant, pack_factors, tucker_proj_int, tucker_proj_float, W, J, D


def normalize_np(x):
    """x: (N,7,7,54) -> 每个 token 减均值除无偏标准差（与 torch.std 默认 unbiased=True 一致）。"""
    mean = x.mean(axis=(1, 2, 3), keepdims=True)
    std = x.std(axis=(1, 2, 3), ddof=1, keepdims=True)
    return (x - mean) / std


def attention_np(q, k, v):
    """q,k,v: (N,7,7,54) float。逐字复刻原代码的 reshape 语义（V 的布局怪癖）。返回 ctx (N,7,7,54)。
    torch 布局是 (7,7,54,N)，内存序 p*N+n。"""
    N = q.shape[0]
    qb = np.moveaxis(q, 0, -1).reshape(D, N)          # (B,D,N) 的 reshape：直接是 (p, n)
    kb = np.moveaxis(k, 0, -1).reshape(D, N)
    vflat = np.ascontiguousarray(np.moveaxis(v, 0, -1)).reshape(-1)   # 内存序
    vb = vflat.reshape(N, D)                          # (B,N,D) 的 reshape：按内存顺序切块，不是转置
    scores = qb.T @ kb                                # (N,N)，无缩放
    scores = scores - scores.max(axis=-1, keepdims=True)
    attn = np.exp(scores)
    attn /= attn.sum(axis=-1, keepdims=True)
    ctx_flat = (attn @ vb).reshape(-1)                # (N,D) 再 reshape 回 (7,7,54,N) 内存序
    return np.moveaxis(ctx_flat.reshape(W, W, J, N), -1, 0)


class Net:
    """把 checkpoint 展成 numpy，两条路径：float（全浮点）和 fixed（PL 算子定点）。"""

    def __init__(self, name='unoverlapping', fmt=Fmt(), ckpt=None, classes=None):
        m = tt_model.load(name, ckpt, classes).double()
        self.model, self.fmt = m, fmt
        self.N = m.SEQ + 1
        self.cls = m.encoder.cls_token.detach().numpy()[0]          # (7,7,54,1)
        self.pos = m.encoder.pos_embed.detach().numpy()[0]          # (7,7,54,N)
        self.layers = []
        for enc in m.encoder.encoders:
            L = {}
            for nm in ('query', 'key', 'value', 'mlp'):
                f = [t.detach().numpy() for t in enc.factors(nm)]
                L[nm] = dict(f=f, q=pack_factors(*f, fmt).astype(np.int64))
            self.layers.append(L)
        self.cw = m.classifier[0].weight.detach().numpy()           # (9, 2646)
        self.cb = m.classifier[0].bias.detach().numpy()

    def embed(self, patch):
        """patch: (7,7,270) float -> tokens (N,7,7,54)，含 cls 与位置编码。"""
        t = self.model.tokens(torch.from_numpy(patch)[None]).numpy()[0]     # (7,7,54,SEQ)
        x = np.concatenate([self.cls, t], axis=-1) + self.pos                # (7,7,54,N)
        return np.moveaxis(x, -1, 0)

    def proj(self, x, L, nm, fixed):
        if not fixed:
            return tucker_proj_float(x, *L[nm]['f'])
        xq = quant(x, self.fmt.DF, self.fmt.DB)
        return dequant(tucker_proj_int(xq, L[nm]['q'], self.fmt), self.fmt.DF)

    def forward(self, patch, fixed, trace=None):
        x = self.embed(patch)
        for li, L in enumerate(self.layers):
            xn = normalize_np(x)
            q, k, v = (self.proj(xn, L, nm, fixed) for nm in ('query', 'key', 'value'))
            ctx = attention_np(q, k, v)
            xn2 = normalize_np(xn + ctx)      # 残差加的是归一化后的 xn（原代码 x 已被 normalize 覆盖）
            mlp = self.proj(xn2, L, 'mlp', fixed)
            x = xn2 + mlp
            if trace is not None:
                trace.append(dict(xn=xn, q=q, k=k, v=v, ctx=ctx, xn2=xn2, mlp=mlp, x=x))
        return self.cw @ x[1].reshape(-1) + self.cb     # token 1，flatten 顺序 (i1,i2,j)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='unoverlapping')
    ap.add_argument('--patches', type=int, default=200)
    args = ap.parse_args()
    rng = np.random.default_rng(0)
    patches = rng.standard_normal((args.patches, 7, 7, 270))

    # 先证明 float 路径 == torch 模型（否则后面的定点比较没有意义）
    net = Net(args.model)
    with torch.inference_mode():
        ref = net.model(torch.from_numpy(patches[:8])).numpy()
    mine = np.stack([net.forward(p, fixed=False) for p in patches[:8]])
    print(f'float path vs torch: max|diff| = {np.abs(ref - mine).max():.3e}')
    assert np.abs(ref - mine).max() < 1e-9

    ref_logits = np.stack([net.forward(p, fixed=False) for p in patches])
    ref_arg = ref_logits.argmax(1)
    print(f'{"format":26s} {"argmax agree":>12s} {"max|dlogit|":>12s} {"mean|dlogit|":>13s}')
    for fmt in (Fmt(DF=9, WF=14, MF=14), Fmt(DF=11, WF=14, MF=14), Fmt(DF=12, WF=14, MF=14),
                Fmt(DF=12, WF=14, MF=12), Fmt(DF=12, WF=13, MF=14), Fmt(DF=13, WF=14, MF=14)):
        net = Net(args.model, fmt)
        fx = np.stack([net.forward(p, fixed=True) for p in patches])
        agree = (fx.argmax(1) == ref_arg).mean()
        d = np.abs(fx - ref_logits)
        print(f'D{fmt.DB}.{fmt.DF} W{fmt.WB}.{fmt.WF} M{fmt.MB}.{fmt.MF}   {agree:12.1%} {d.max():12.4f} {d.mean():13.5f}')


if __name__ == '__main__':
    main()
