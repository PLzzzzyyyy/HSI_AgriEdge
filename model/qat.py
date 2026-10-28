"""int8 版 QAT 假量化（PLAN §17 B5，engine_arch §3.7）。

与 format_scan.py 的 "all8 pm: act Q3.4, w pm, mid Q3.4/8"（fixed_point_sim 定点路径）同一套舍入点：
  投影输入（归一化输出）→ Q3.4；模 1 后、模 2 后 → mid Q3.4；模 3 后 → data_t Q3.4（投影输出本来就要进 data_t）；
  因子逐矩阵 2 的幂 int8：e = floor(log2(127 / max|m|))，值域 ±127。
舍入 floor(v·2^f + 0.5)、饱和到 [-128, 127]（AP_RND + AP_SAT），反向直通（STE）。残差、注意力、分类头仍浮点，与定点仿真一致。

用法：qat.enable(model) 之后 model 的前向即 int8 假量化前向；qat.disable(model) 恢复浮点前向（评"QAT 模型自己的浮点路径"）。
"""
import math
import types
import torch
import tt_model

DF = MF = 4
BITS = 8
LIM = (1 << (BITS - 1)) - 1        # 127，权重不用 -128


def fq(x, frac, lo=-(1 << (BITS - 1)), hi=(1 << (BITS - 1)) - 1):
    s = float(1 << frac) if frac >= 0 else 1.0 / (1 << -frac)
    q = torch.clamp(torch.floor(x * s + 0.5), lo, hi) / s
    return x + (q - x).detach()


def weight_frac(m):
    return int(math.floor(math.log2(LIM / m.detach().abs().max().item())))


def _project(self, x, name):
    x = fq(x, DF)
    for i, m in enumerate(self.factors(name)):
        x = tt_model.mode_dot(x, fq(m, weight_frac(m), -LIM, LIM), mode=i + 1)
        x = fq(x, MF if i < 2 else DF)
    return x


def enable(model):
    for enc in model.encoder.encoders:
        enc.project = types.MethodType(_project, enc)
    return model


def disable(model):
    for enc in model.encoder.encoders:
        enc.__dict__.pop('project', None)
    return model
