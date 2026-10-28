"""Tensor Transformer (TT) —— 只保留部署会用到的类，去掉 utils.pyc 依赖和 git 冲突。

来源：D:/FPGAlearn/Tensor-Transformer-for-HSIC-master/.../TensorTransformerFramework.py
      （HEAD 与另一分支内容逐字相同，已由 analysis/audit_model.py 核对）

与论文不一致、但权重就是这么训的、必须照代码来的三处：
  1. TensorEncoder 输出取 x[..., 1]（第一个光谱子张量），不是 cls token（index 0）。
  2. 非重叠模型 reshape(-1,7,7,54,5)：token i 拿到的是波段 i, i+5, i+10, ...（交错），不是连续 54 波段。
  3. V 的 reshape 是 (-1, N, 2646)，Q/K 是 (-1, 2646, N)。V 不是转置，是按内存顺序切块。

mode_dot 约定（与 tensorly.tenalg.mode_dot 一致，由 verify_mode_dot() 核对）：
  Y = X ×_m M   ⇔   Y[..., a, ...] = Σ_i M[a, i] · X[..., i, ...]   （在第 m 轴收缩）
"""
import torch
import torch.nn as nn


def mode_dot(x, m, mode):
    """x: (..., I_mode, ...)，m: (A, I_mode)。在 x 的第 `mode` 轴与 m 的第 1 轴收缩，结果放回原轴位置。"""
    y = torch.tensordot(x, m, dims=([mode], [1]))   # 收缩轴消失，新轴 A 追加到最后
    return torch.movedim(y, -1, mode)


def transformer_normalize(t):
    """对每个 token 的 (I1,I2,J) 三个轴做均值/无偏标准差归一化，无仿射参数。t: (B,7,7,54,N)"""
    mean = t.mean(dim=(1, 2, 3), keepdim=True)
    std = t.std(dim=(1, 2, 3), keepdim=True)     # 无偏（除以 n-1）
    return (t - mean) / std


class Self3DAttentionToken(nn.Module):
    """一层 TEL。参数名 query_0/1/2, key_0/1/2, value_0/1/2, mlp_0/1/2 与 checkpoint 一致。"""

    def __init__(self, win_size, dims, channels):
        super().__init__()
        self.win_size, self.dims, self.channels = win_size, dims, channels
        for name in ('query', 'key', 'value', 'mlp'):
            for i, size in enumerate((win_size, win_size, dims)):
                self.register_parameter(f'{name}_{i}', nn.Parameter(torch.zeros(size, size)))

    def factors(self, name):
        return [getattr(self, f'{name}_{i}') for i in range(3)]

    def project(self, x, name):
        """x: (B,7,7,54,N) → 对每个 token 做 ×1 M1 ×2 M2 ×3 M3。token 轴 N 在最后，不参与。"""
        for i, m in enumerate(self.factors(name)):
            x = mode_dot(x, m, mode=i + 1)
        return x

    def forward(self, x):
        B = x.shape[0]
        N = self.channels + 1
        D = self.dims * self.win_size * self.win_size
        x = transformer_normalize(x)
        q = self.project(x, 'query').reshape(B, D, N)
        k = self.project(x, 'key').reshape(B, D, N)
        v = self.project(x, 'value').reshape(B, N, D)          # ★ 原代码的 V 布局，按内存顺序切块
        attn = torch.softmax(q.transpose(-1, -2) @ k, dim=-1)  # (B,N,N)，无 1/sqrt(d) 缩放
        ctx = (attn @ v).reshape(x.shape)
        x = transformer_normalize(x + ctx)
        return x + self.project(x, 'mlp')


class TensorEncoder(nn.Module):
    def __init__(self, winsize, dim, channels, layer):
        super().__init__()
        self.encoders = nn.Sequential(*[Self3DAttentionToken(winsize, dim, channels) for _ in range(layer)])
        self.cls_token = nn.Parameter(torch.zeros(1, winsize, winsize, dim, 1))
        self.pos_embed = nn.Parameter(torch.zeros(1, winsize, winsize, dim, channels + 1))

    def forward(self, x):
        x = torch.cat((self.cls_token.expand(x.shape[0], -1, -1, -1, -1), x), dim=-1)
        x = x + self.pos_embed
        x = self.encoders(x)
        return x[..., 1]          # ★ 不是 cls token


class TensorTransformerHSI_unoverlapping_LK(nn.Module):
    """LK 非重叠：输入 (B,7,7,270) → (B,7,7,54,5)，5 个交错 token + cls = 6。"""
    WIN, DIM, SEQ, LAYERS, CLASSES = 7, 54, 5, 12, 9

    def __init__(self, classes=None):
        super().__init__()
        self.CLASSES = classes or self.CLASSES
        self.encoder = TensorEncoder(self.WIN, self.DIM, self.SEQ, self.LAYERS)
        self.classifier = nn.Sequential(nn.Linear(self.DIM * self.WIN * self.WIN, self.CLASSES))

    def tokens(self, x):
        return x.reshape(-1, self.WIN, self.WIN, self.DIM, self.SEQ)

    def forward(self, x):
        x = self.encoder(self.tokens(x))
        return self.classifier(torch.flatten(x, start_dim=1))


class TensorTransformerHSI_overlapping_LK(nn.Module):
    """LK 重叠：步长 27、长度 54，9 个 token + cls = 10。"""
    WIN, DIM, SEQ, LAYERS, CLASSES = 7, 54, 9, 12, 9

    def __init__(self, classes=None):
        super().__init__()
        self.CLASSES = classes or self.CLASSES
        self.encoder = TensorEncoder(self.WIN, self.DIM, self.SEQ, self.LAYERS)
        self.classifier = nn.Sequential(nn.Linear(self.DIM * self.WIN * self.WIN, self.CLASSES))

    def tokens(self, x):
        x = x.reshape(-1, self.WIN, self.WIN, 270)
        step = (270 - self.DIM) // (self.SEQ - 1)   # 27
        return torch.stack([x[..., i * step:i * step + self.DIM] for i in range(self.SEQ)], dim=-1)

    def forward(self, x):
        x = self.encoder(self.tokens(x))
        return self.classifier(torch.flatten(x, start_dim=1))


MODELS = {
    'unoverlapping': TensorTransformerHSI_unoverlapping_LK,
    'overlapping': TensorTransformerHSI_overlapping_LK,
}
UPSTREAM = 'D:/FPGAlearn/Tensor-Transformer-for-HSIC-master/Tensor-Transformer-for-HSIC-master'


def load(name='unoverlapping', ckpt=None, classes=None):
    """ckpt 不给时用上游 LongKou 的 .pth；其它景传 data/ckpt 下的路径和类别数。"""
    model = MODELS[name](classes).eval()
    ckpt = ckpt or f'{UPSTREAM}/TensorTransformerHSI_{name}_LK.pth'
    state = torch.load(str(ckpt), map_location='cpu', weights_only=True)
    model.load_state_dict(state, strict=True)
    return model


def verify_mode_dot(tensorly_path='D:/FPGAlearn/tmp/tensor_transformer_audit_deps'):
    """核对本文件的 mode_dot 与 tensorly 逐位一致（tensorly 只在这里用）。"""
    import sys
    sys.path.insert(0, tensorly_path)
    import tensorly as tl
    tl.set_backend('pytorch')
    x = torch.randn(2, 7, 7, 54, dtype=torch.float64)
    for mode, size in ((1, 7), (2, 7), (3, 54)):
        m = torch.randn(size, size, dtype=torch.float64)
        # 模 3 的 54 项求和顺序不同，float64 下差 ~1e-14；约定错了会差 ~40
        assert torch.allclose(mode_dot(x, m, mode), tl.tenalg.mode_dot(x, m, mode=mode), atol=1e-12), mode
    return True


if __name__ == '__main__':
    print('mode_dot == tensorly:', verify_mode_dot())
    for name in MODELS:
        m = load(name)
        print(name, 'params =', sum(p.numel() for p in m.parameters()))
