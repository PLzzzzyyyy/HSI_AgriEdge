# 设计说明：数值约定与内存布局

## 1. 网络（按代码，不按论文）

每层 TEL（`Self3DAttentionToken.forward`）：

```
xn  = normalize(x)                      每 token 减均值 / 无偏 std，无仿射
q,k,v = xn ×1 M1 ×2 M2 ×3 M3            三组因子，(7×7),(7×7),(54×54)
attn = softmax(qᵀk)                      (N×N)，无 1/√d
ctx  = attn @ v_reshaped                 ★ v 按内存序切成 (N, 2646)，不是转置
xn2 = normalize(xn + ctx)                ★ 残差加在 xn 上（代码里 x 已被 normalize 覆盖）
out = xn2 + (xn2 ×1 ×2 ×3 M_mlp)         "MLP" 也是 Tucker 模积
```

12 层后取 token 1（`x[..., 1]`，不是 cls），flatten 后过 Linear(2646→9)。

输入 token 化：patch (7,7,270) 经 ToTensor 变 (270,7,7)，再按内存序 reshape 成 (7,7,54,5)。
所以模型的"空间轴"混着波段，无物理意义，但权重就是这么训的。PS 端只需保证内存序一致。

## 2. 定点格式（hls/src/tt_types.h == model/quant.py Fmt）

| 量 | 类型 | 格式 | 范围 | 依据 |
|---|---|---|---|---|
| DDR 激活 | data_t | ap_fixed<16,4> Q3.12 | ±8 | normalize 后 \|x\| < 5 |
| 因子矩阵 | wt_t | ap_fixed<16,2> Q1.14 | ±2 | 权重 \|w\| < 0.28 |
| 模 1/2 中间 | mid_t | ap_fixed<18,4> Q3.14 | ±8 | 中间量 \|t\| < 2.1；18 位使 16×18 乘法占一个 DSP |
| 累加器 | acc_t | ap_fixed<48,20> | 不舍入 | |

舍入位置：模 1 后、模 2 后各舍到 mid_t 一次，模 3 后舍到 data_t 一次。全部 AP_RND（tie 向 +∞）+ AP_SAT。
numpy 侧用 int64 整数复刻：`floor((acc + half) / 2^shift)` 再 clip。三处实现（quant.py、tucker_proj.cpp、tt_hw_sim.cpp）逐位一致。

格式扫描（100 随机 + 300 真实 patch）：Q6.9 到 Q2.13 分类全一致；Q3.12 的 logit 误差最小（max 1e-3 随机 / 0.11 真实）。

## 3. DDR 布局

激活块：`D*N` 个 int16，元素 `(p, n)` 在 `p*N + n`，`p = (i1*7 + i2)*54 + j`。
这正是 torch `(7,7,54,N)` 的内存序，所以 PS 从 embed 到分类头全程不转置；PL 一次读整块进片上再按需索引。

权重：每投影 3014 个 int16 = M1[7][7] + M2[7][7] + M3[54][54] 行主序；`weights_all.bin` = 12 层 × (q,k,v,mlp)。

## 4. PL 算子

```
tucker_proj(in, out_q, out_k, out_v, w_q, w_k, w_v, n_tok, n_proj)
  load_block   : DDR 整块 → xb[n][i1][r]，r = i2*54+j            D*N 拍
  每个投影：
    load_factors : 3014 拍
    每个 token：
      mode1 : t1[a][i2][j] = Σ_i1 M1[a][i1] xb[n][i1][r]         378 拍，49 乘
      mode2 : t2[a][b][j]  = Σ_i2 M2[b][i2] t1[a][i2][j]        378 拍，49 乘
      mode3 : y[a][b][c]   = Σ_j  M3[c][j]  t2[a][b][j]         2646 拍，54 乘
    store_block  : ob[p][n] → DDR                                D*N 拍
```

n_proj=3 时 QKV 共享一次 load_block。第一版综合（100 MHz）：DSP 154/220，LUT 估 63%，BRAM 38%；
N=6 单次 QKV 调用估 ~1 ms → 每 patch 约 (1 + 0.4) × 12 ≈ 17 ms PL 时间，加 PS 胶水另计。
mode3 是瓶颈（2646 拍 × 6 token × 4 投影 = 63K 拍/层），下一步可把 mode3 做成 2 路并行（108 DSP）。

## 5. PS 端（vitis/src/tt_net.cpp）

double 浮点；normalize 用两遍扫描（均值、方差）；softmax 减最大值；attention 严格按上面的 reshape 语义写索引。
cache：PL 读的 in/w 先 flush，PL 写的 out 完成后 invalidate；缓冲 32 字节对齐、长度向上取整。
