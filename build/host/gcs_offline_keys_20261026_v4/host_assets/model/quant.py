"""PL 算子 tucker_proj 的逐位定点仿真（numpy int64 整数运算，与 HLS 的 ap_fixed 语义一一对应）。

格式（由 Fmt 给出，最终值写入 src/hls/tt_types.h，两边必须一致）：
  data_t : ap_fixed<16, 16-DF, AP_RND, AP_SAT>   DDR 里的激活，PS 用 int16 + SCALE=2^DF 解释
  wt_t   : ap_fixed<16, 16-WF, AP_RND, AP_SAT>   DDR 里的因子矩阵
  mid_t  : ap_fixed<18, 18-MF, AP_RND, AP_SAT>   模 1、模 2 之后的片上中间量（18 位：DSP48E1 一乘一 DSP）
  acc_t  : 足够宽，累加不舍入

AP_RND = 加半个 LSB 后截断 = floor(v + 0.5)；AP_SAT = 饱和不回绕。
运算顺序固定为 模1 → 模2 → 模3，HLS 里也是这个顺序，改顺序结果就不逐位相等了。
"""
from dataclasses import dataclass
import numpy as np

W, J = 7, 54           # 空间窗、光谱长度
D = W * W * J          # 2646
NF = 2 * W * W + J * J # 一个投影的因子元素数 3014：M1(49) M2(49) M3(2916)


@dataclass(frozen=True)
class Fmt:
    DF: int = 12   # data_t 小数位   Q3.12  ±8
    WF: int = 14   # wt_t   小数位   Q1.14  ±2
    MF: int = 14   # mid_t  小数位   18 位  Q3.14 ±8
    DB: int = 16
    WB: int = 16
    MB: int = 18

    @property
    def scale(self):
        return 1 << self.DF


def rnd_sat(acc_int, shift, bits):
    """整数 acc（定标 2^(f+shift)）→ 舍到 f 位小数并饱和到 bits 位有符号。AP_RND 的 tie 向 +inf。"""
    if shift > 0:
        half = 1 << (shift - 1)
        v = np.floor_divide(acc_int + half, 1 << shift)   # floor((acc + 0.5*LSB) / LSB)，负数也正确
    else:
        v = acc_int
    lim = 1 << (bits - 1)
    return np.clip(v, -lim, lim - 1)


def quant(x, frac, bits=16):
    """float → 定点整数（AP_RND + AP_SAT），返回 int64。"""
    v = np.floor(np.asarray(x, dtype=np.float64) * (1 << frac) + 0.5)
    lim = 1 << (bits - 1)
    return np.clip(v, -lim, lim - 1).astype(np.int64)


def dequant(q, frac):
    return np.asarray(q, dtype=np.float64) / (1 << frac)


def pack_factors(m1, m2, m3, fmt=Fmt()):
    """三个因子矩阵 → DDR 里的 3014 个 int16，顺序 M1[a][i] 行主序、M2、M3。"""
    return np.concatenate([quant(m1, fmt.WF).ravel(), quant(m2, fmt.WF).ravel(),
                           quant(m3, fmt.WF).ravel()]).astype(np.int16)


def tucker_proj_int(x_q, factors_q, fmt=Fmt()):
    """x_q: (N, 7, 7, 54) int64（data_t 整数）；factors_q: 3014 int64。返回 (N,7,7,54) int64（data_t 整数）。
    与 HLS 逐位一致的参考实现。"""
    m1 = factors_q[:49].reshape(W, W)
    m2 = factors_q[49:98].reshape(W, W)
    m3 = factors_q[98:].reshape(J, J)
    # 模 1：t1[n,a,i2,j] = sum_i1 M1[a,i1] * x[n,i1,i2,j]     定标 DF+WF -> 舍到 MF
    t1 = np.einsum('ai,nibj->nabj', m1, x_q)
    t1 = rnd_sat(t1, fmt.DF + fmt.WF - fmt.MF, fmt.MB)
    # 模 2：t2[n,a,b,j] = sum_i2 M2[b,i2] * t1[n,a,i2,j]     定标 MF+WF -> 舍到 MF
    t2 = np.einsum('bi,naij->nabj', m2, t1)
    t2 = rnd_sat(t2, fmt.MF + fmt.WF - fmt.MF, fmt.MB)
    # 模 3：y[n,a,b,c] = sum_j M3[c,j] * t2[n,a,b,j]         定标 MF+WF -> 舍到 DF
    y = np.einsum('cj,nabj->nabc', m3, t2)
    return rnd_sat(y, fmt.MF + fmt.WF - fmt.DF, fmt.DB)


def tucker_proj_float(x, m1, m2, m3):
    """浮点参考（同样的收缩约定），用于量化误差对比。x: (N,7,7,54)"""
    t = np.einsum('ai,nibj->nabj', m1, x)
    t = np.einsum('bi,naij->nabj', m2, t)
    return np.einsum('cj,nabj->nabc', m3, t)


# ---- DDR 块布局：PL 一次读写整块 (D, N)，元素 (p, n) 在 p*N + n，p = (i1*7+i2)*54 + j ----
def to_block(x_nijk):
    """(N,7,7,54) -> 一维块，长度 D*N，布局 (p, n)。这正是 torch (B,7,7,54,N) 的内存序。"""
    return np.ascontiguousarray(np.moveaxis(x_nijk, 0, -1)).reshape(-1)


def from_block(blk, N):
    return np.moveaxis(np.asarray(blk).reshape(W, W, J, N), -1, 0)
