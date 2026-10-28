"""测量各中间量取值范围，为定点格式选型。输入用高斯随机 patch（真实数据到位后重跑）。"""
import torch, tt_model
from tt_model import mode_dot, transformer_normalize

def stats(name, t):
    t = t.detach()
    print(f'{name:28s} min {t.min():9.3f} max {t.max():9.3f} |mean| {t.abs().mean():7.4f} std {t.std():7.4f}')

torch.manual_seed(0)
for mname in ('unoverlapping', 'overlapping'):
    print('=====', mname)
    model = tt_model.load(mname).double()
    x = torch.randn(64, 7, 7, 270, dtype=torch.float64)      # 64 个随机 patch
    with torch.inference_mode():
        x = model.encoder.cls_token.expand(64, -1, -1, -1, -1)
        x = torch.cat((x, model.tokens(torch.randn(64, 7, 7, 270, dtype=torch.float64))), -1) + model.encoder.pos_embed
        for li, enc in enumerate(model.encoder.encoders):
            B, N, D = x.shape[0], enc.channels + 1, 2646
            xn = transformer_normalize(x)
            outs = {}
            for name in ('query', 'key', 'value', 'mlp'):
                f = enc.factors(name)
                t1 = mode_dot(xn, f[0], 1); t2 = mode_dot(t1, f[1], 2); t3 = mode_dot(t2, f[2], 3)
                outs[name] = (t1, t2, t3)
            q = outs['query'][2].reshape(B, D, N); k = outs['key'][2].reshape(B, D, N); v = outs['value'][2].reshape(B, N, D)
            scores = q.transpose(-1, -2) @ k
            attn = torch.softmax(scores, -1)
            ctx = (attn @ v).reshape(x.shape)
            xr = xn + ctx
            xn2 = transformer_normalize(xr)
            f = enc.factors('mlp')
            m1 = mode_dot(xn2, f[0], 1); m2 = mode_dot(m1, f[1], 2); m3 = mode_dot(m2, f[2], 3)
            if li in (0, 5, 11):
                print(f'--- layer {li}')
                stats('x (layer input)', x); stats('normalize(x) [PL in]', xn)
                for name in ('query', 'key', 'value'):
                    stats(f'  {name} mode1 mid', outs[name][0]); stats(f'  {name} mode2 mid', outs[name][1]); stats(f'  {name} out [PL out]', outs[name][2])
                stats('attn scores', scores); stats('ctx', ctx); stats('x+ctx', xr)
                stats('normalize(x+ctx) [PL in]', xn2); stats('  mlp mode1 mid', m1); stats('  mlp mode2 mid', m2); stats('  mlp out [PL out]', m3)
            x = xn2 + m3
        stats('final token (to classifier)', x[..., 1])
        w = torch.cat([p.flatten() for n, p in model.named_parameters() if 'encoders' in n])
        stats('all factor weights', w)
        stats('classifier weight', model.classifier[0].weight); stats('classifier bias', model.classifier[0].bias)
        stats('cls_token', model.encoder.cls_token); stats('pos_embed', model.encoder.pos_embed)
