# Tensor Transformer 高光谱分类网络的 Zynq-7020 实现 —— 从论文到板卡的全栈讲解

> **对象**：论文 Zhang et al., *Tensor Transformer for hyperspectral image classification*, Pattern Recognition 163 (2025) 111470，及作者开源代码与 LongKou 预训练权重。目标器件 Zynq-7020 / XC7Z020CLG400-2（正点原子领航者）。
> **本文的边界**：只讲本仓库 `D:\TT_HSI_FPGA` 里已经做出来、并且有验证结果的东西。论文里说的、代码里做的、仿真估的、板上测的，四种口径分开写，不拼成同一件事。
> **源码定位**：`model/` 是 PC 侧 Python，`hls/src/` 是 PL 侧 C++，`vitis/src/` 是 PS 侧 C++。上游原始代码在 `D:\FPGAlearn\Tensor-Transformer-for-HSIC-master\`，本文引用时标"上游"。
> **与上一篇的关系**：上一篇讲的是 YOLOv4-tiny 的卷积加速器（`pose6d_fpga/docs/ACCELERATOR_EXPLAINED.md`）。本篇是它的姊妹篇：同一块板、同一套工具链、同一种"PS 调度 + PL 算子 + DDR 交换"的架构，但算子从卷积换成了张量模积，而且这次从 PC 侧模型复刻到板上验证全部是我们自己做的，每一步都有对拍数据。

## 阅读路线与目录 <a id="toc"></a>

本文按"先总后分"组织。**第 0 章是总览，读完就知道整个系统在算什么、谁在算、数据长什么样**。后面三个部分分别展开 PC、PL、PS，每一节都是同一个套路：先说这一步只做哪一件事，再用固定实例的数字走一遍，最后对照源码。

```
第 0 章：一句话说清网络 → 系统分工 → 固定实例 → 证据口径 → 一页数据流
第一部分 PC：网络按代码是什么样 → 输入怎样变成 token → 模积是什么 → 注意力的三个怪癖 → 定点怎么定 → 黄金基准链
第二部分 PL：为什么只做一个算子 → 接口与 DDR 布局 → 逐函数读 tucker_proj → 周期与资源 → 分区
第三部分 PS：一层的调度 → 每个数值步骤的索引 → cache → 性能分段表与串口输出 → 平台与工程设置
第四部分：整个项目的脚本、命令与产物
附录：一页串起数据流 / 面试复述与自测 / 优化方向 / 容易背错的结论 / 证据与版本表 / 踩坑索引
```

- [0. 总览](#s0)
  - [0.1 这个网络在算什么](#s0-1)
  - [0.2 系统分工：PC、PS、PL、DDR](#s0-2)
  - [0.3 全文固定实例](#s0-3)
  - [0.4 四种证据口径](#s0-4)
  - [0.5 一页数据流](#s0-5)
- [第一部分：PC 端](#h1)
  - [1.1 网络结构：按代码，不按论文](#s1-1)
  - [1.2 输入怎样变成 token：预处理七步与 CHW 交错](#s1-2)
  - [1.3 Tucker 模积：定义、约定与计数](#s1-3)
  - [1.4 注意力的三个怪癖](#s1-4)
  - [1.5 定点格式怎么定](#s1-5)
  - [1.6 黄金基准链：六环对拍](#s1-6)
- [第二部分：PL 端](#h2)
  - [2.1 为什么只做一个算子、为什么不用上一篇的 conv IP](#s2-1)
  - [2.2 接口、寄存器与 DDR 布局](#s2-2)
  - [2.3 逐函数读 tucker_proj](#s2-3)
  - [2.4 周期与资源：三种报告对照](#s2-4)
  - [2.5 数组分区：每个 pragma 在回答什么访问需求](#s2-5)
- [第三部分：PS 端](#h3)
  - [3.1 文件分工与一次运行的顺序](#s3-1)
  - [3.2 一层的调度：24 次启动](#s3-2)
  - [3.3 每个数值步骤的索引](#s3-3)
  - [3.4 cache：谁写、谁读](#s3-4)
  - [3.5 性能：352 → 173 ms 的分段表与串口输出讲解](#s3-5)
  - [3.6 平台脚本与 Vitis 设置](#s3-6)
- [第四部分：整个项目的脚本、命令与产物](#h4)
- [附录 A：一页串起完整数据流](#hA)
- [附录 B：面试复述与自测](#hB)
- [附录 C：优化方向与适用边界](#hC)
- [附录 D：容易背错的结论](#hD)
- [附录 E：证据、版本与数据表](#hE)
- [附录 F：踩坑索引](#hF)

---

# 0. 总览 <a id="s0"></a>

## 0.1 这个网络在算什么 <a id="s0-1"></a>

**任务**：高光谱图像（Hyperspectral Image，HSI）逐像素分类。LongKou 数据集是一张 550×400 的无人机航拍图，每个像素有 270 个波段（400～1000 nm），要判成 9 类作物/地物。网络一次只判一个像素：取该像素周围 7×7 邻域的全部 270 个波段作为输入（一个 7×7×270 的 patch），输出 9 个 logit。

**网络**：Tensor Transformer（TT），12 层 Tensor Encoder Layer（TEL）+ 一个全连接分类头。它和普通 Transformer 的区别只有一处：Q、K、V 的投影不是"向量 × 大矩阵"，而是"三阶张量 × 三个小矩阵"（Tucker 模积）。

先用数字建立尺度感。全文都用 LK 非重叠模型（上游 `TensorTransformerHSI_unoverlapping_LK`，`N = 6` 个 token）：

| 量 | 值 | 怎么来的 |
|---|---:|---|
| 一个 token 的元素数 D | 2646 | 7 × 7 × 54 |
| token 数 N | 6 | 5 个光谱子张量 + 1 个 cls token |
| 一层激活的元素数 D×N | 15876 | int16 时 31.75 KB |
| 一个投影的因子矩阵元素数 | 3014 | 7×7 + 7×7 + 54×54 |
| 每层投影数 | 4 | Q、K、V、"MLP" |
| 总参数 | 187017 | 12×4×3014 + cls 2646 + pos 15876 + 分类头 9×2646+9 |
| 权重 int16 总量 | 289 KB | 12×4×3014×2 字节；上一篇 YOLO 是 11.3 MB |
| 单 patch 乘加数 | 5413 万 | 见 1.3 节；上一篇 YOLO 是 34 亿/帧 |
| 其中模积占比 | 95.7% | 注意力 12 层合计 4.2%（单层 0.35%），分类头 0.04%；逐层表见 `model/data/layer_stats_unoverlapping.md` |

**两个直接推论**，后面所有设计都从这里来：
1. 权重和激活都小到片上放得下（BRAM 630 KB），不需要上一篇那种"整张特征图切块"的机制。
2. 算力几乎全在模积里，PL 只做模积就够了；注意力、归一化留给 CPU 做，代价可以忽略。

## 0.2 系统分工：PC、PS、PL、DDR <a id="s0-2"></a>

和上一篇同一套架构，先把"谁在算"和"数据放在哪"分开：

| 名称 | 含义 | 在本项目里做什么 |
|---|---|---|
| PC | 开发电脑 | 复刻模型、复刻预处理、定定点格式、导出权重与黄金向量、画图 |
| PS | Processing System，ARM Cortex-A9 | 归一化、量化、注意力、残差、分类头；每层启动 PL 两次 |
| PL | Programmable Logic | 运行 HLS 综合出的 `tucker_proj` 算子：一次算 1 或 3 个投影 |
| DDR | 片外内存 | 存权重、激活块；PS 和 PL 通过它交换数据 |
| BRAM | PL 片上存储 | 一次装下整块激活（最多 10 个 token）和一个投影的因子矩阵 |
| DSP | PL 乘法器 | 模 1、模 2 各 49 个、模 3 有 54 个乘法器并行 |

一层的节拍：

```
PS：x → normalize → 量化成 int16 → 写 DDR
PS：把 in/out/w 的地址和 n_tok=6、n_proj=3 写进 PL 寄存器，启动
PL：读整块 → 对 6 个 token 各算 Q、K、V 三个投影 → 写回 DDR 三块
PS：等完成 → 反量化 → 注意力 → 残差 → normalize → 量化 → 写 DDR
PS：启动 PL，n_proj=1，算 MLP 投影
PL：读整块 → 算 → 写回
PS：反量化 → 残差 → 得到下一层输入 x
```

12 层 × 2 次 = **24 次 PL 启动**，每次启动都是"PS 给地址，PL 自己去 DDR 搬"，不是 PS 把数据从寄存器一个个塞进去。

## 0.3 全文固定实例 <a id="s0-3"></a>

为了不在每节换数字，全文固定用：

| 项 | 值 |
|---|---|
| 模型 | LK 非重叠，`N=6`，12 层 |
| 像素 | LongKou 图第 224 行、第 158 列（在河中央） |
| 真值 | 第 7 类 Water |
| 模型输出 | argmax = 6，即第 7 类（标签 = argmax + 1），判对 |
| 主要看的层 | 第 0 层 |
| 定点格式 | 激活 Q3.12、权重 Q1.14、中间量 18 位 Q3.14 |

它的黄金向量在 `model/data/golden/`（第 0 层 QKV 与 MLP 两次调用的输入、权重、期望输出，全部 int16 逐位），整网参考 logits 在 `golden/logits_fixed.bin`，板上程序把它编进了 `tt_data.c`。

## 0.4 四种证据口径 <a id="s0-4"></a>

本文提到任何数字时，都属于下面四种之一，不混用：

| 口径 | 来源 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 论文 | PDF 正文和表格 | 作者的实验设置与结果 | 代码实际怎么写的（有三处不一致） |
| 代码/仿真 | 上游 Python、我们的 numpy、HLS csim/cosim | 算法逐位行为、周期数（无 DDR 等待） | 板上时间 |
| 综合/实现报告 | Vitis HLS csynth、Vivado impl | 资源估算 / 实际占用、时序 | 运行时间；csynth 的 LUT/DSP/BRAM 三项都被证明不准 |
| 板上 | 串口打印、XTime 计时 | 某次运行的结果和时间 | 不同输入下的全部行为 |

## 0.5 一页数据流 <a id="s0-5"></a>

```
PC
  WHU_Hi_LongKou.mat (550×400×270 float32)
    → 3×3 高斯滤波 → 逐波段标准化 → 全局标准化 → 四周补零 3
    → 取像素 (224,158) 的 7×7×270 窗 → 转成 (270,7,7) → 整块减均值除无偏 std      = patch（float32，13230 个数）
  checkpoint .pth → 12×4 组因子矩阵 → 量化 Q1.14 → weights_all.bin（289 KB）
  patch + 权重 → numpy 定点仿真 → 逐层参考、9 个参考 logits
                     │  export_c_arrays.py 生成 tt_data.c
                     ▼
PS（vitis/src/tt_net.cpp）
  embed：patch 按内存序拆成 5 个 token，前面加 cls，加位置编码 → x[2646×6]（double）
  12 层，每层：
    normalize → quant → [PL: Q,K,V] → dequant → attention → 残差 → normalize → quant → [PL: MLP] → dequant → 残差
  取 token 1 → 2646→9 全连接 → argmax
                     │  AXI-Lite 写 9 个寄存器 + ap_start；m_axi 经 HP0/HP1 读写 DDR
                     ▼
PL（hls/src/tucker_proj.cpp）
  load_block：DDR 整块 (p,n) → 片上 xb[n][i1][r]
  对每个投影：load_factors → 对每个 token：mode1 → mode2 → mode3 → store_block
                     ▼
DDR
  in 块 15876×int16，out_q/k/v 三块，w 三块各 3014×int16
```

**这张图画的是数据流，不是时序图。** PL 内部各步是串行的，PS 在 PL 忙时是轮询等待，没有重叠。

---

# 第一部分：PC 端 <a id="h1"></a>

PC 端回答两个问题：**要算什么**（把上游模型逐字复刻成可控的形式），**正确结果是什么**（黄金基准）。它不碰板子。

## 1.1 网络结构：按代码，不按论文 <a id="s1-1"></a>

### 一层 TEL 的完整步骤

上游 `Self3DAttentionToken.forward` 逐行展开（`model/tt_model.py` 是它的干净复刻，两者 fp64 差 1e-15）：

```
输入 x：(B, 7, 7, 54, N)，最后一维是 token
1  xn  = normalize(x)                       每个 token 对自己的 2646 个数减均值、除无偏标准差
2  q   = xn ×1 Mq1 ×2 Mq2 ×3 Mq3            对 N 个 token 各做一次 Tucker 模积（1.3 节）
3  k   = xn ×1 Mk1 ×2 Mk2 ×3 Mk3
4  v   = xn ×1 Mv1 ×2 Mv2 ×3 Mv3
5  q   = q.reshape(B, 2646, N)              Q、K 按 (p, n) 看
6  k   = k.reshape(B, 2646, N)
7  v   = v.reshape(B, N, 2646)              ★ V 按 (n, p) 看，这不是转置（1.4 节）
8  a   = softmax(qᵀ k)                       (B, N, N)，没有 1/√d 缩放
9  ctx = (a @ v).reshape(x.shape)           按内存序塞回 (7,7,54,N)
10 x   = xn + ctx                            ★ 残差加在 xn 上，不是原始 x（1.4 节）
11 xn2 = normalize(x)
12 out = xn2 + (xn2 ×1 Mm1 ×2 Mm2 ×3 Mm3)    ★ "MLP" 也是一个模积，没有激活函数
```

**整层没有任何非线性激活**（没有 GELU、ReLU）。唯一的非线性是 normalize 里的除法和 softmax 里的指数。这一点对硬件很友好：PL 只需要乘加。

### 整网

```
patch (270,7,7) ──reshape──> 5 个 token (7,7,54)
            ┌ cls token（可学习，7×7×54）拼在最前面 → N = 6
            └ 加位置编码 pos_embed（7×7×54×6，可学习）
   → TEL × 12
   → 取 token 1（★ 不是 cls token 0）→ flatten 2646 → Linear(2646, 9)
```

### 与论文不一致、但权重就是这么训的三处

| # | 论文 | 代码（以代码为准） | 影响 |
|---|---|---|---|
| 1 | 输出取 class token | `return x[..., 1]`，取第一个光谱子张量 | 分类头接的是 token 1 |
| 2 | 沿光谱切成连续 54 波段的段 | `reshape(-1,7,7,54,5)` 作用在 CHW 内存序上，token i 拿到的是交错的元素 | 见 1.2 节，PS 必须按内存序排 |
| 3 | V 与 Q、K 同样处理 | V reshape 成 (N, 2646)，按内存顺序切块 | 注意力的 AV 不是"按 token 加权" |

审计脚本 `analysis/audit_model.py`（在上游目录）用 `value_reshape_equals_transpose = false, disagreement 96%` 确认了第 3 条。这三处都不是 bug 修复的对象：checkpoint 是这样训出来的，改任何一处结果都变。

## 1.2 输入怎样变成 token：预处理七步与 CHW 交错 <a id="s1-2"></a>

### 上游预处理源码缺失，怎么复刻的

上游只提供 `__pycache__/utils.cpython-38.pyc`，没有 `utils.py`。我们用 xdis 反汇编字节码，从 `img_predict.py` 的调用顺序加字节码常量把七步完整还原（`model/preprocess.py`），然后用作者附带的预测图闭环验证：随机 1000 个有标签像素，我们的预处理 + 模型给出的类别与作者预测图 **100% 一致**（两个模型都是）。

### 七步

| 步 | 操作 | 关键细节 |
|---|---|---|
| 1 | 逐波段 3×3 高斯滤波 | 核 `[[.05,.1,.05],[.1,.4,.1],[.05,.1,.05]]`，`scipy.signal.convolve2d(mode='same')`，零边界 |
| 2 | 逐波段标准化 | `mean = np.mean(np.mean(x,0),0)`；**`std = np.std(np.std(x,0),0)`**，是"每列的标准差再取标准差"，不是逐波段标准差，照抄 |
| 3 | 全局标准化 | `utils.normalize`：`(x - x.mean()) / x.std()`，numpy 的 std 是 **ddof=0** |
| 4 | 补零 | 四周各 3 像素 |
| 5 | 取窗 | 以像素为中心 7×7×270，`astype(float32)` |
| 6 | ToTensor | torchvision 把 (7,7,270) HWC 转成 **(270,7,7) CHW**；float 输入不除 255 |
| 7 | patch 级标准化 | 再调一次 `utils.normalize`，但这次对象是 torch tensor，`.std()` 是 **无偏 ddof=1** |

第 3 步和第 7 步是同一个函数，语义却不同：接收 numpy 时 ddof=0，接收 torch 时 ddof=1。这类东西反汇编看不出来，只能从接收者类型推。

### CHW 交错：模型的"空间轴"其实混着波段

第 6 步之后 patch 在内存里是 (270,7,7)，元素编号 `e = c×49 + h×7 + w`（c 波段、h 行、w 列，共 13230 个）。模型直接 `reshape(-1, 7, 7, 54, 5)`，reshape 不动内存，只是换一种读法。(7,7,54,5) 的步长是 1890 / 270 / 5 / 1，所以：

```
i1 = e ÷ 1890
i2 = (e ÷ 270) mod 7
j  = (e ÷ 5)   mod 54
n  = e mod 5
```

用几个 e 走一遍：

| e | 真实 (c,h,w) | 模型看到的 (i1,i2,j,n) |
|---:|---|---|
| 0 | 波段 0，(0,0) | (0,0,0, token 0) |
| 1 | 波段 0，(0,1) | (0,0,0, token 1) |
| 4 | 波段 0，(0,4) | (0,0,0, token 4) |
| 5 | 波段 0，(0,5) | (0,0,1, token 0) |
| 49 | 波段 1，(0,0) | (0,0,9, token 4) |
| 1890 | 波段 38，(4,0) | (1,0,0, token 0) |

也就是说，**5 个 token 的同一个位置 (i1,i2,j) 装的是同一行相邻 5 个像素**，"j 轴"每 5 个元素走一格，49 个像素才换一个波段。模型的 i1、i2、j 与图像的行、列、波段没有物理对应。论文里"沿光谱切段保留空间结构"的叙述，在这份代码里并不成立。

**这对硬件意味着什么**：PS 不需要理解这个映射，只要保证把 patch 按 `e` 顺序、每 5 个一组分给 5 个 token 即可。`tt_embed` 里就一行：`x[p*N + 1 + m] = patch[p*5 + m]`，`p` 是 token 内编号 0～2645，`m` 是 token 号 0～4。

### 固定实例的数字

像素 (224,158) 的 patch：13230 个 float32，标准化后均值 0、无偏 std 1，范围约 −1.89～2.68。文件 `golden/patch_f32.bin`。

## 1.3 Tucker 模积：定义、约定与计数 <a id="s1-3"></a>

### 定义

一个三阶张量 X（形状 I1×I2×J，这里 7×7×54）沿第 m 个轴与矩阵 M 做**模积**（mode product，记 ×m），就是把该轴上的每一根"纤维"（fiber，固定其他两个下标、沿该轴变化的一维向量）左乘 M：

```
(X ×1 M1)[a, i2, j] = Σ_{i1} M1[a, i1] · X[i1, i2, j]          M1 是 7×7
(X ×2 M2)[i1, b, j] = Σ_{i2} M2[b, i2] · X[i1, i2, j]          M2 是 7×7
(X ×3 M3)[i1, i2, c] = Σ_{j}  M3[c, j]  · X[i1, i2, j]          M3 是 54×54
```

三个连起来 `Y = X ×1 M1 ×2 M2 ×3 M3`，因为每次收缩的轴不同，**顺序不影响数学结果**（浮点下有 1e-14 的求和顺序差；定点下中间舍入位置不同则不逐位相等，所以硬件固定 1→2→3）。

### 约定核对

tensorly 的 `mode_dot(x, m, mode)` 是 `Σ_i m[a, i] · x[..., i, ...]`，即矩阵的**第二个下标**参与收缩。`tt_model.verify_mode_dot()` 用随机张量核对过：按这个约定实现与 tensorly 差 1e-14，如果把矩阵转置，差 ~40。**矩阵行列顺序错了不会报错，只会全错**，所以这一步必须用数值核对，不能靠读文档。

### 一个能手算的小例子

取 I1=I2=J=2，X 全 1，M1 = [[1,2],[3,4]]，其余为单位阵：

```
(X ×1 M1)[a, i2, j] = M1[a,0]·1 + M1[a,1]·1
a=0：1+2 = 3        a=1：3+4 = 7
```

结果是 2×2×2 张量，第一"层"全 3、第二"层"全 7。可以看到模 1 只在 i1 轴上混合，(i2, j) 的每个位置各自独立地做了同一个 2×2 矩阵乘。这正是硬件里"沿 i1 并行取 7 个数、乘一个 7×7 矩阵、输出 7 个数"的由来。

### 乘加数

固定一个 token（7×7×54）、一个投影：

| 模 | 输出元素数 | 每个输出的乘加数 | 乘加合计 |
|---|---:|---:|---:|
| 模 1 | 7×7×54 = 2646 | 7 | 18522 |
| 模 2 | 2646 | 7 | 18522 |
| 模 3 | 2646 | 54 | 142884 |
| 合计 | | | **179928** |

模 3 占一个投影的 79%。往上乘：

```
一个投影、6 个 token：179928 × 6 = 1,079,568
一层 4 个投影：       × 4     = 4,318,272
注意力 QᵀK：2646 × 6 × 6      =    95,256
注意力 AV：           同样     =    95,256
一层合计：                     = 4,508,784
12 层：                        = 54,105,408
分类头 2646 × 9：              =    23,814
单 patch：                     = 54,129,222 MAC
```

这个数和审计脚本用 torch profiler 数出的 `aten::mm/bmm` FLOPs（108,258,444 = 2×MAC）完全一致，说明我们对网络的理解没有漏项。

### 参数为什么这么少

上游 README 里的 `Tucker_TRL` 注释说了动机：直接对 2646 维做一个 2646×2646 的线性变换要 700 万参数，Tucker 分解成三个小矩阵只要 3014 个。代价是表达能力受限（只能表示可分解成三个轴独立变换的映射），论文认为这反而保留了"结构"。

## 1.4 注意力的三个怪癖 <a id="s1-4"></a>

这三处在 1.1 节表格里列过，这里把索引写到能直接对照 C 代码的程度。torch 张量 (7,7,54,N) 的内存序是 `p×N + n`，其中 `p = (i1×7 + i2)×54 + j`。下文 "块" 指这个 15876 个元素的一维内存。

### 怪癖 1：Q、K 正常，V 按内存序切块

```
q.reshape(B, 2646, N)：元素 (p, n) 就在 p×N + n     ← 与块布局一致，不动内存
k 同上
v.reshape(B, N, 2646)：元素 (n, p') 在 n×2646 + p'   ← 同一段内存，按每 2646 个切一块
```

所以 `qᵀk` 是正常的 token 间内积：`scores[n][c] = Σ_p q[p×N+n] · k[p×N+c]`。而 `a @ v` 的第 c 行 `v[c, :]` 是块的第 `c×2646 ～ c×2646+2645` 段，**这一段横跨了所有 6 个 token 的元素**（因为块里相邻元素是不同 token 的同一位置）。最后 `reshape(x.shape)` 又把 (N, 2646) 的结果按内存序重新解释为 (7,7,54,N)。

写成 C 索引（`vitis/src/tt_net.cpp::tt_attention`）：

```c
scores[n][c]   = Σ_p q[p*N + n] * k[p*N + c]          // (D,N) 内积
ctx_flat[n*D + p'] = Σ_c attn[n][c] * v_flat[c*D + p']  // 按内存序切块加权
x[i] = xn[i] + ctx_flat[i]                             // 扁平相加：ctx_flat 按 i = p*N + n 重解释
```

最后一行是踩过坑的地方：ctx_flat 的下标 `n×D + p'` 只是计算时的写法，加残差时它就是一段 15876 长的内存，与 xn 按同一个扁平下标相加。如果把它当成 (n, p) 布局去转置相加，logits 会差 4.9（见附录 F）。

### 怪癖 2：残差加在归一化后的 xn 上

上游第 1 步 `x = transformer_normalize(x)` 把 x 覆盖了，第 10 步 `x = x + context_layer` 加的是归一化后的值。论文的框图画的是标准 pre-norm 残差（加原始输入）。复刻 numpy 路径时按论文写，与 torch 差 4e-2，逐层定位到第一层残差差 1.9 才发现。

### 怪癖 3：输出取 token 1

`TensorEncoder.forward` 最后 `return x[..., 1]`，上一行被注释掉的才是 `x[..., 0]`。token 1 是第一个光谱子张量（装着 patch 里 e mod 5 == 0 的那些元素）。cls token 参与了 12 层注意力但最后没用。

## 1.5 定点格式怎么定 <a id="s1-5"></a>

### 先量范围

`model/measure_ranges.py` 用真实权重 + 64 个随机 patch 跑 fp64，记录每个中间量在第 0、5、11 层的极值：

| 量 | 范围 | 说明 |
|---|---|---|
| normalize 之后（PL 输入） | ±5 | 每 token 归一化到 std=1，尾部到 5σ |
| 模 1 之后 | ±2.0 | |
| 模 2 之后 | ±0.8 | |
| 模 3 之后（PL 输出） | ±0.85 | |
| 注意力分数 | −66 ～ +40 | 2646 项内积，**超出任何 16 位定点** → 留在 PS 浮点 |
| 全部因子矩阵 | ±0.27 | |
| 分类头权重 | ±0.07 | |

上一篇 YOLO 用的 Q6.9（±64）在这里浪费 3 位整数位；权重 ±0.27 用 Q6.9 步长 1/512 相对误差近 1%。

### 三种类型

| 类型 | ap_fixed | 格式 | 范围 | 步长 | 用途 |
|---|---|---|---|---|---|
| data_t | `<16, 4, AP_RND, AP_SAT>` | Q3.12 | ±8 | 2.4e-4 | DDR 里的激活；PS 用 int16 + SCALE=4096 解释 |
| wt_t | `<16, 2, AP_RND, AP_SAT>` | Q1.14 | ±2 | 6.1e-5 | 因子矩阵 |
| mid_t | `<18, 4, AP_RND, AP_SAT>` | Q3.14 | ±8 | 6.1e-5 | 模 1、模 2 之后的片上中间量 |
| acc_t | `<48, 20>` | | | | 累加器，不舍入不饱和 |

mid_t 取 18 位而不是 32 位，是因为 DSP48E1 一次能做 25×18 位乘法：16×18 一个 DSP 搞定，宽了就要拆成两个（2.4 节的事故就是这么来的）。

### 舍入位置固定为三处

```
模 1 累加（DF+WF = 26 位小数） → 舍到 mid_t（14 位小数）：右移 12 位
模 2 累加（MF+WF = 28 位小数） → 舍到 mid_t：右移 14 位
模 3 累加（MF+WF = 28 位小数） → 舍到 data_t（12 位小数）：右移 16 位
```

AP_RND 的定义是"加半个 LSB 后截断"，等价于 `floor(v + 0.5)`，tie 向 +∞；AP_SAT 是饱和不回绕。numpy 侧用 int64 精确整数复刻：`floor_divide(acc + 2^(shift-1), 2^shift)` 再 clip。三份实现（`quant.py::tucker_proj_int`、`tucker_proj.cpp`、`tt_hw_sim.cpp`）逐位一致，这是后面所有对拍的基础。

### 格式扫描

`fixed_point_sim.py` 把 PL 算子换成定点逐位仿真、其余浮点，跑整网：

| 格式（激活/权重/中间） | 100 随机 patch 分类一致率 | max\|Δlogit\| |
|---|---:|---:|
| Q6.9 / Q1.14 / Q3.14 | 100% | 0.0071 |
| Q4.11 / Q1.14 / Q3.14 | 100% | 0.0018 |
| **Q3.12 / Q1.14 / Q3.14** | **100%** | **0.0009** |
| Q3.12 / Q1.14 / Q5.12 | 100% | 0.0013 |
| Q2.13 / Q1.14 / Q3.14 | 100% | 0.0063 |

再用 300 个真实 LongKou 像素：定点与浮点分类 100% 一致，OA 都是 92.3%，max|Δlogit| 0.11（真实数据比随机数据尾部重）。Q2.13 变差是因为 ±4 的范围开始截到归一化后的尾部，Q3.12 是拐点。

## 1.6 黄金基准链：六环对拍 <a id="s1-6"></a>

上一篇讲过"用第一处不一致缩小范围"。本篇把它做成了一条完整的链，每一环都有数字：

| 环 | 比什么 | 手段 | 结果 |
|---|---|---|---|
| ① 模型复刻 | `tt_model.py` vs 上游类 | 同一随机输入，两个 checkpoint | fp32 差 4.8e-7，fp64 差 1.1e-15 |
| ② 预处理复刻 | 我们的预处理+模型 vs 作者预测图 | 随机 1000 有标签像素 | 100% 一致（两模型） |
| ③ 定点 | 定点仿真 vs 浮点 | 100 随机 + 300 真实 patch | 分类 100% 一致 |
| ④ HLS | csim / cosim vs numpy 定点 | 第 0 层 4 个投影 63504 个 int16 | 0 个不匹配 |
| ⑤ PS 胶水 | `host_test.exe`（C 版整网 + C 版算子仿真）vs numpy | 12 层逐层 + logits | 逐层差 ≤ 3.6e-15，logits 差 4.3e-14 |
| ⑥ 板上 | 板卡 vs numpy | 同一 patch | logits 差 4.3e-14，PASS |

⑤ 和 ⑥ 的差完全相同（4.263e-14），说明板上 PL 输出与主机端 C 仿真逐位相同，差异只来自 double 运算的舍入。

**这条链证明的是"板子等价于作者的模型"，不证明"模型判得准"。** 模型的精度是作者的 OA 91.6%（滤波前）/ 95.5%（7×7 众数滤波后），板子会继承同样的 8% 错误率。要测板上 OA，得送几百上千个像素上板，这是下一步。

---

# 第二部分：PL 端 <a id="h2"></a>

PL 端只有一个算子 `tucker_proj`（`hls/src/tucker_proj.cpp`，149 行）。本部分先讲为什么是这个形态，再按数据流逐函数读，最后对照三种报告。

## 2.1 为什么只做一个算子、为什么不用上一篇的 conv IP <a id="s2-1"></a>

### 算力分布决定分工

0.1 节的表：模积占 95.7%，注意力 4.2%（12 层合计），归一化/残差是逐元素操作。PL 做模积就拿到了几乎全部算力；注意力的分数范围到 −66（1.5 节），16 位定点放不下，留 PS 浮点最省事。

### 上一篇的 conv IP 能不能直接用

能，但不划算。模 3 在"通道 = 光谱 j、像素 = 49 个空间位置"的布局下就是 `ch_in=54, ch_out=54` 的 1×1 卷积；模 1、模 2 合成 49×49 矩阵后也能当 1×1 卷积。问题有三：

| 问题 | 数字 |
|---|---|
| pwconv 分支只有 32 路乘加，3×3 分支的 128 路用不上 | 峰值 3.2 GMAC/s，单 patch 理想 17 ms |
| 三个模的"通道轴"不同，用 1×1 卷积就得在 PS 转置，每层 4～5 次 | 每次 15876 个元素 |
| conv IP 的分块、halo、stride 机制对模积全是死重 | 白占 94.5 块 BRAM |

而模积需要的"沿不同轴收缩"，在片上缓存里靠索引就能做到，根本不需要转置。所以重写一个专用算子：它没有分块（整块放得下）、没有 padding、没有 stride，只有三段乘加和两段搬运。

### 一次调用做多少事

一次启动 = **对 n_tok 个 token、算 n_proj 个投影**。n_proj=3 时 Q、K、V 共享一次输入块加载。每层两次调用：

```
调用 1：in = normalize(x) 的量化块，n_proj=3 → out_q, out_k, out_v，权重 w_q, w_k, w_v
调用 2：in = normalize(xn+ctx) 的量化块，n_proj=1 → out_q（装 MLP 结果），权重 w_q（装 M_mlp）
```

调用 2 的 out_k/out_v/w_k/w_v 传占位地址，PL 不会访问它们。

## 2.2 接口、寄存器与 DDR 布局 <a id="s2-2"></a>

### 顶层签名

```cpp
void tucker_proj(data_t *in, data_t *out_q, data_t *out_k, data_t *out_v,
                 wt_t *w_q, wt_t *w_k, wt_t *w_v,
                 unsigned short n_tok, unsigned short n_proj);
```

| 参数 | 接口 | 内容 |
|---|---|---|
| in | m_axi bundle FM | D×N 个 data_t，激活块 |
| out_q / out_k / out_v | m_axi bundle FM | 各 D×N 个 data_t |
| w_q / w_k / w_v | m_axi bundle WT | 各 3014 个 wt_t |
| n_tok | s_axilite | token 数，最大 10 |
| n_proj | s_axilite | 1 或 3 |
| return | s_axilite | ap_start / ap_done |

7 个指针 → 2 个 AXI Master（FM、WT）→ 分别接 HP0、HP1。控制走一个 AXI-Lite bundle CTRL，寄存器表由 HLS 生成（`hls/ip_export/drivers/tucker_proj_v1_0/src/xtucker_proj_hw.h`）：

```
0x00 AP_CTRL   0x10 in     0x18 out_q   0x20 out_k   0x28 out_v
0x30 w_q       0x38 w_k    0x40 w_v     0x48 n_tok   0x50 n_proj
```

PS 一次启动写 9 个寄存器 + 1 次 ap_start。综合时用 `config_interface -m_axi_addr64=false -s_axilite_data64=false` 保持 32 位指针寄存器（与上一篇相同的坑：不关会多出一个 s_axi_control 口）。

### DDR 布局：和 torch 内存序一致，PS 零转置

激活块 D×N 个 int16，元素 (p, n) 在 `p×N + n`，`p = (i1×7 + i2)×54 + j`：

```
偏移:  0      1      2      3      4      5   |  6      7     ...   11   |  12 ...
      p0,n0  p0,n1  p0,n2  p0,n3  p0,n4  p0,n5 | p1,n0  p1,n1  ...  p1,n5 |
```

这正是 torch (7,7,54,N) 的内存序（1.4 节）。PS 从 embed 到分类头全程用这一个布局；PL 读整块进片上再按需索引。**布局是 PC、PS、PL 三方之间约定的唯一接口**，任何一方改了都要三方一起改。

权重块 3014 个 int16：M1[7][7] 行主序（49 个）、M2[7][7]（49 个）、M3[54][54]（2916 个）。12 层 × 4 投影顺序拼成 `weights_all.bin`，第 l 层第 k 个投影（k = 0 Q、1 K、2 V、3 MLP）的起点是 `(l×4 + k)×3014`。

### 固定实例的数字

`golden/in_qkv.bin`（第 0 层 QKV 调用的输入块）范围 −15485～14839，Q3.12 下即 −3.78～3.62；`out_q` 范围 −3727～3144，即 −0.91～0.77。都远离 ±32768 饱和线。

## 2.3 逐函数读 tucker_proj <a id="s2-3"></a>

### 先看数据在片上长什么样

| 片上数组 | 形状 | 类型 | 谁写 | 谁读 |
|---|---|---|---|---|
| `xb[10][7][378]` | token × i1 × (i2·54+j) | data_t | load_block | mode1 |
| `m1[7][7]` `m2[7][7]` `m3[54][54]` | | wt_t | load_factors | mode1/2/3 |
| `t1[7][7][54]` | a × i2 × j | mid_t | mode1 | mode2 |
| `t2[7][7][54]` | a × b × j | mid_t | mode2 | mode3 |
| `ob[2646][10]` | p × token | data_t | mode3 | store_block |

xb 的第二维是 i1、第三维把 (i2, j) 拍平成 `r = i2×54 + j`：为了让模 1 一拍取出同一个 r 的 7 个 i1 值。ob 的布局直接就是 DDR 的 (p, n)，写回时不用转。

### 调用层次

```
tucker_proj
  ├ load_block               DDR → xb，一次
  ├ one_projection(w_q)      ┐
  │   ├ load_factors         │ 每个投影一次
  │   ├ for n in 0..n_tok-1: │
  │   │    mode1 → mode2 → mode3     每个 token 三段
  │   └ store_block          ┘
  ├ one_projection(w_k)      n_proj ≥ 2 时
  └ one_projection(w_v)      n_proj ≥ 3 时
```

### 2.3.1 load_block：整块进片上并重排

```cpp
static void load_block(data_t *in, data_t xb[TT_NMAX][TT_W][TT_R], unsigned short n_tok) {
    const unsigned int total = (unsigned int)TT_D * n_tok;
    unsigned short n = 0, r = 0, i1 = 0;
    for (unsigned int e = 0; e < total; e++) {
#pragma HLS PIPELINE II=1
        xb[n][i1][r] = in[e];
        if (n == n_tok - 1) { n = 0; if (r == TT_R - 1) { r = 0; i1++; } else r++; }
        else n++;
    }
}
```

DDR 里第 e 个元素是 (p, n)：`p = e ÷ N`，`n = e mod N`；再把 p 拆成 `i1 = p ÷ 378`、`r = p mod 378`。代码不做除法，用三个计数器进位：n 走到 N−1 归零并让 r 加 1，r 走到 377 归零并让 i1 加 1。

走几个 e（N=6）：

| e | n | r | i1 | 对应 p |
|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 |
| 5 | 5 | 0 | 0 | 0 |
| 6 | 0 | 1 | 0 | 1 |
| 2267 | 5 | 377 | 0 | 377 |
| 2268 | 0 | 0 | 1 | 378 |
| 15875 | 5 | 377 | 6 | 2645 |

**为什么写成单层循环**：第一版写成 for i1 / for r / for n 三层嵌套，内层 trip 只有 6，综合出 5292～55566 拍（理论 15876）；每次进内层都付一次流水启动。拍平后报告 15878 拍，II=1。

### 2.3.2 load_factors：3014 个权重进片上

三段顺序循环，各 II=1，共 49 + 49 + 2916 = 3014 拍（报告 50 + 50 + 2917）。m1、m2 完全分区成 49 个寄存器，m3 按第一维 c 分区成 54 组、每组 54 个。

### 2.3.3 mode1：沿 i1 收缩

```cpp
for (r = 0; r < 378; r++) {                        // r = i2*54 + j
#pragma HLS PIPELINE II=1
    data_t x[7];  for (i1) x[i1] = xb[n][i1][r];  // 一拍取 7 个
    for (a = 0; a < 7; a++) {
        acc_t acc = 0;
        for (i1) acc += x[i1] * m1[a][i1];        // 49 个乘法并行
        t1[a][r / 54][r % 54] = (mid_t)acc;       // 舍到 18 位
    }
}
```

每一拍：读 7 个输入（xb 按 i1 分区，7 个 bank 各一个）、49 次乘加、写 7 个 t1。乘法写成 `x[i1] * m1[a][i1]` 而不是 `(acc_t)x[i1] * m1[a][i1]`，后者会让乘法变成 48 位宽、DSP 数翻倍（2.4 节的事故）。

**报告显示这个循环达成 II=4，不是 1。** 原因：一拍要写 7 个 `t1[a][i2][j]`，a 从 0 到 6 而 i2、j 相同；t1 只按第二维 i2 分区，7 个写入落进同一个 BRAM，双端口一拍最多写 2 个。修法是 t1 再按第一维 a 分区。本文写作时**尚未修**（改 IP 要重建平台），影响是 mode1 每 token 1524 拍而非 378，占一次 QKV 调用约 18%。记在附录 C。

### 2.3.4 mode2：沿 i2 收缩

```cpp
for (a) for (j) {                                  // 378 次
#pragma HLS PIPELINE II=1
    mid_t x[7];  for (i2) x[i2] = t1[a][i2][j];   // t1 按 i2 分区：7 个 bank 各读一个
    for (b) { acc = Σ_i2 x[i2] * m2[b][i2];  t2[a][b][j] = (mid_t)acc; }   // 写 7 个不同 b
}
```

读 7 个不同 i2（t1 的分区维）、写 7 个不同 b（t2 按第二维 b 分区），都是各 bank 一个，II=1 达成，386 拍。

### 2.3.5 mode3：沿 j 收缩，54 路并行

```cpp
acc_t acc[54];                                     // 54 个累加器，完全分区
for (ab = 0; ab < 49; ab++) for (j = 0; j < 54; j++) {   // 2646 次
#pragma HLS PIPELINE II=1
    mid_t x = t2[ab / 7][ab % 7][j];
    for (c = 0; c < 54; c++) {
        acc_t p = x * m3[c][j];                   // 54 个乘法：m3 按 c 分区，一拍取 54 个
        acc[c] = (j == 0) ? p : acc[c] + p;
    }
    if (j == 53) for (c) ob[ab * 54 + c][n] = (data_t)acc[c];   // 每 54 拍出一个位置的 54 个数
}
```

数据流是"一个输入广播给 54 个乘法器，54 个累加器各自累加，54 拍后同时出 54 个结果"。输出写到 `ob[p][n]`，p = ab×54 + c，54 个 c 连续；ob 按第一维 cyclic 分区 54 路，p mod 54 = c，正好 54 个 bank 各写一个。

累加写成 `(j == 0) ? p : acc + p` 而不是先清零再累加，是为了让 II=1 的循环体里没有额外的初始化分支。报告 2658 拍，II=1。

### 2.3.6 store_block：片上 → DDR

与 load_block 对称，单层循环 `out[e] = ob[p][n]`，n 进位到 p。ob 是 (p, n) 布局，读出来就是 DDR 顺序。报告 15895 拍，II=1。

### 2.3.7 一次 QKV 调用的拍数账

按 csynth 报告逐项相加（N=6）：

```
load_block                                    15878
每个投影：
  load_factors                                 3017
  6 token × (mode1 1524 + mode2 392 + mode3 2660) = 27456
  store_block                                 15895
  小计                                         46368
3 个投影                                      139104
合计                                          154982    ≈ cosim 实测 155350 拍 = 1.55 ms @ 100 MHz
```

cosim 报的 155350 与手算差 0.2%，差在函数进出的几拍。MLP 调用（n_proj=1）：15878 + 46368 = 62246 ≈ cosim 62435。

从账上看：**搬运（load + 3 次 store = 63563 拍）占 41%，mode3 占 31%，mode1 因 II=4 占 18%**，真正的算力瓶颈 mode3 还不到三分之一。这决定了附录 C 的优化顺序：先把 AXI 位宽从 16 提到 64（搬运 ÷4），再修 mode1 的 II，最后才是 mode3 双路。

## 2.4 周期与资源：三种报告对照 <a id="s2-4"></a>

### csynth 估算 vs Vivado 实现

| 资源 | csynth 第一版 | Vivado 第一版 | csynth 第二版 | Vivado 第二版 |
|---|---:|---:|---:|---:|
| LUT | 33561 (63%) | 30637 (58%) | 29365 (55%) | **13012 (24%)** |
| FF | 30506 | 14050 | 27436 | 13804 |
| BRAM 18K | 109 (38%) | 170 (61%) | 109 (38%) | **170 (61%)** |
| DSP | 154 (70%) | **220 (100%)** | 156 (70%) | **160 (73%)** |
| WNS @100 MHz | 估 7.3 ns 路径 | **−0.019 ns 违例** | 估 7.3 ns 路径 | **+0.374 ns 收敛** |

第一版和第二版的源码只差三处 `(acc_t)x * w` → `x * w`。csynth 两版都报约 155 个 DSP，看不出问题；Vivado 第一版实际 220 个用满，溢出的乘法被放进 LUT 搭的 CARRY4 链，时序差 19 ps。这是上一篇结论"HLS 资源估算两个方向都不准"的又一个实例，这次连 DSP 也不准。

BRAM 实际 170 个 18K（85 个 36K 块）比估算多 56%：xb 按 i1 分 7 个 bank 各 3780×16 位、ob 分 54 个 bank 各 490×16 位，小 bank 各独占一整块 18K BRAM，容量利用率低。这是"逻辑字节小、物理 BRAM 多"的同一个现象。

### 时序

100 MHz，第二版 WNS +0.374 ns。第一版违例的 XSA 也保留了（`vivado/tt_soc_v1_wns-0.019.xsa`），板上第一次 PASS 就是用它跑的；19 ps 在这块芯片上没触发错误，但不能当"违例无所谓"的证据。

### 周期

见 2.3.7 的账。cosim：QKV 调用 155350 拍、MLP 调用 62435 拍。这是 RTL 仿真的周期，不含真实 DDR 等待。板上分段计时 PL qkv 20.9 ms ÷ 12 层 = 1.74 ms 一次，比 1.55 ms 多 12%，差的就是 DDR 延迟加 cache 维护。

## 2.5 数组分区：每个 pragma 在回答什么访问需求 <a id="s2-5"></a>

| 数组 | pragma | 形成的 bank | 回答的需求 |
|---|---|---|---|
| xb | `complete dim=2` | 7 个（按 i1） | mode1 一拍读 7 个 i1 |
| m1, m2 | `complete` | 49 个寄存器 | mode1/2 一拍读全部 49 个权重 |
| m3 | `complete dim=1` | 54 个（按 c） | mode3 一拍读 54 个 c 的同一列 j |
| t1 | `complete dim=2` | 7 个（按 i2） | mode2 一拍读 7 个 i2；**mode1 一拍写 7 个 a 却撞在同一 bank → II=4** |
| t2 | `complete dim=2` | 7 个（按 b） | mode2 一拍写 7 个 b；mode3 一拍读 1 个 |
| acc | `complete` | 54 个寄存器 | mode3 54 个累加器并行 |
| ob | `cyclic factor=54 dim=1` | 54 个（按 p mod 54） | mode3 一拍写 54 个连续 p |

分区回答"同时访问哪些元素"，流水回答"多快启动下一次"。t1 那一行是反例：读的需求满足了，写的需求没满足，II 就掉到 4。检查方法是看 csynth 报告里每个循环的 achieved II，而不是只看有没有写 `PIPELINE II=1`。

---

# 第三部分：PS 端 <a id="h3"></a>

PS 端做三件事：把 patch 变成第一层输入、每层调度 PL 两次并做 PL 不做的数值步骤、最后出 logits。代码在 `vitis/src/tt_net.cpp`（126 行）和 `vitis/src/tt_hw_xil.cpp`。

## 3.1 文件分工与一次运行的顺序 <a id="s3-1"></a>

| 文件 | 负责的事 | 板上编译 | 主机编译 |
|---|---|:-:|:-:|
| `tt_net.h / tt_net.cpp` | 整网调度、embed、normalize、quant/dequant、attention、残差、分类头、分段计时 | ✓ | ✓ |
| `tt_hw.h` | PL 调用抽象：`tt_hw_init()`、`tt_hw_proj(...)` | ✓ | ✓ |
| `tt_hw_xil.cpp` | 板上实现：写寄存器、启动、轮询、cache 维护 | ✓ | |
| `tt_hw_sim.cpp` | 主机实现：int64 整数逐位仿真 PL 算子 | | ✓ |
| `tt_data.h / tt_data.c` | 由 PC 生成：权重、cls、pos、分类头、黄金 patch、参考 logits，全是 const 数组 | ✓ | |
| `main.cpp` | 板上主程序：初始化、跑一次、对拍、计时、打印 | ✓ | |
| `host_test.cpp` | 主机主程序：读 `model/data/` 的二进制，逐层对拍 numpy | | ✓ |

同一份 `tt_net.cpp` 在主机上与 `tt_hw_sim.cpp` 链接、在板上与 `tt_hw_xil.cpp` 链接。主机端先证明胶水逻辑对（1e-15），板上只剩驱动和 cache 两个新变量。

板上一次运行：

```
main
  tt_hw_init          XTucker_proj_Initialize，查找设备 0
  Xil_DCacheFlush     常量数组由调试器写进 DDR 时可能停在 cache 里，整体 flush 一次
  tt_forward          embed → 12 × tt_layer → 分类头，XTime 计时
  打印 9 个 logits 与参考的差、PASS/FAIL、总时间、分段表
```

数据不走 SD 卡、不走 QSPI：一个 patch 加权重共约 500 KB，直接编进 elf（`tt_data.c` 1.7 MB 源码），调试器下载 elf 时一起写进 DDR。这是"先跑通一个 patch"最短的路；多 patch 精度测试再换数据通道。

## 3.2 一层的调度：24 次启动 <a id="s3-2"></a>

`tt_layer(net, wk, layer)`，x 原地更新。缓冲全在 DDR，`wk.x / wk.xn / wk.ctx` 是 double，`wk.in_q / out_q / out_k / out_v` 是 int16、32 字节对齐：

| 步 | 函数 | 输入 → 输出 | 布局 |
|---|---|---|---|
| 1 | `tt_normalize` | x → xn | (p,n) → (p,n) |
| 2 | `tt_quant` | xn → in_q | double → int16 |
| 3 | `tt_hw_proj(..., N, 3)` | in_q, w_q/k/v → out_q/k/v | PL |
| 4 | `dequant_np` ×2 | out_q → qf、out_k → kf | (p,n) int16 → **(n,p)** double |
| 5 | `tt_dequant` | out_v → vf | (p,n) → 扁平内存序 |
| 6 | `tt_attention` | qf, kf, vf → ctx_flat | 见 1.4 节 |
| 7 | 残差 | x = xn + ctx_flat | 扁平相加 |
| 8 | `tt_normalize` | x → xn | |
| 9 | `tt_quant` | xn → in_q | |
| 10 | `tt_hw_proj(..., N, 1)` | in_q, w_mlp → out_q | PL |
| 11 | `tt_dequant` | out_q → ctx | |
| 12 | 残差 | x = xn + ctx | 下一层输入 |

第 4 步把 q、k 转成 (n,p) 布局是为了让注意力按 token 连续访问（3.5 节的优化），v 不转是因为 AV 本来就按内存序切块。

## 3.3 每个数值步骤的索引 <a id="s3-3"></a>

每个函数都和 `model/fixed_point_sim.py` 里的同名步骤一一对应，改动时两边同步。

### embed

```c
x[p*N + 0]     = cls_token[p]      + pos_embed[p*N + 0]        // token 0
x[p*N + 1 + m] = patch[p*5 + m]    + pos_embed[p*N + 1 + m]    // token 1..5，m = 0..4
```

`patch[p*5 + m]` 就是 1.2 节的 `e = p×5 + m`：patch 内存里每 5 个连续元素分给 5 个 token 的同一位置 p。

### normalize

对固定 n，遍历 p：均值 `Σ x / 2646`，方差 `Σ (x−mean)² / 2645`（无偏，与 torch.std 默认一致），再 `(x − mean) / sqrt(var)`。实现上按 p 顺序扫一遍、6 个 token 各一个累加器，每个 token 内部的求和顺序与逐 token 扫完全相同，所以结果逐位不变。

### quant / dequant

```
quant:   t = x × 4096 + 0.5;  q = floor(t) 饱和到 [−32768, 32767]
dequant: x = q × (1/4096)
```

floor 不用 libm，用 `(int)t` 向零截断再对负的非整数减 1，结果逐位相同（3.5 节）。1/4096 是 2 的幂，乘法与除法逐位相同。

### attention

1.4 节的三行索引。36 个分数放在同一个 p 循环里各自累加，每个分数的求和顺序（p 从 0 到 2645）与逐个算完全相同。softmax 减最大值再取 exp，双精度下与 numpy 一致。

### 残差与分类头

残差是扁平相加。分类头 `logit[c] = b[c] + Σ_p W[c][p] × x[p*N + 1]`，取 token 1，p 的顺序就是 (i1,i2,j) 的 flatten 顺序。

## 3.4 cache：谁写、谁读 <a id="s3-4"></a>

PL 经 HP 口直接读写 DDR，不经过 CPU cache。`tt_hw_xil.cpp` 每次调用：

```
启动前：Xil_DCacheFlushRange(in, 块字节数)         PS 写的输入 → 真正落到 DDR
        Xil_DCacheFlushRange(w_q / w_k / w_v, 6028)   权重虽是常量，首次也要 flush
写 9 个寄存器 → XTucker_proj_Start → while (!IsDone)
完成后：Xil_DCacheInvalidateRange(out_q / k / v, 块字节数)   丢掉 CPU 的旧副本，重新从 DDR 读
```

长度按 32 字节向上取整，缓冲用 `__attribute__((aligned(32)))`。不对齐时 invalidate 会连带作废相邻数据的 cache 行，如果那一行恰好有 CPU 刚写还没落盘的数据，就丢了。分段计时把 flush/invalidate 算在 PL 项里，所以板上 PL 时间比 cosim 多 12%。

## 3.5 性能：352 → 173 ms 的分段表与串口输出讲解 <a id="s3-5"></a>

> **2026-09-20 终态（本节后面的分段表是早期 double 版本的历史记录，最新数字看这里）**
>
> | 版本 | 单 patch | 块流水 ms/像素 | 关键改动 |
> |---|---:|---:|---|
> | PS double 第二轮（09-15） | 138.7 ms | – | 累加器进寄存器 |
> | PS float32 + NEON（09-16） | 57.6 | 37.3 | A9 只有单精度 NEON；块流水（PS/PL 双 patch 重叠） |
> | IP v1.3 dual + 驱动少 flush（09-19） | 35.3 | 25.9 | PL 64 位 AXI、token DATAFLOW、mode3 双位置；PL 13.7 → 9.9 ms |
> | **IP v1.4 归一化进 PL + int16 层间激活 + PS 轮 5b（09-20）** | **37.5** | **24.3** | PS 去掉 normalize；残差内核按 NEON 依赖链交错 |
>
> 终态分段（12 层合计）：PL norm+qkv 13.6 / scores 5.5 / ctx+resid 6.4 / PL norm+mlp 6.5 / mlp resid 4.6 / embed+head 0.8 ms。4096 像素板上标签与 PC 定点 100% 一致，OA 98.81%。板上 A9 的三条硬教训：double 数组累加器落栈（09-15）、指令估算对 DDR 数据差 3 倍（09-19）、NEON 顺序发射按最长依赖链 × 6 拍计时而非指令数（09-20），细节在 `.claude/pitfalls.md` 与 [CPU_PL_BENCHMARK](CPU_PL_BENCHMARK.md)。

### 三次测量

| 版本 | forward | 变化 |
|---|---:|---|
| 第一版，Vitis 默认 -O0 | 352.0 ms | |
| 开 -O2 | 173.5 ms | 编译器优化，代码没动 |
| -O2 + PS 第一轮（连续访问、去 floor、乘 1/4096） | 166.7 ms | 只有 quant 有效；attention/normalize 不变 |
| -O2 + PS 第二轮（N 模板化，累加器进寄存器） | **138.7 ms** | attention 54→39、normalize 32→18.5；对拍仍 4.263e-14 |

### -O2 版的分段表（12 层合计）

```
--- breakdown (12 layers total) ---
  normalize x2     29.886 ms   17.2%
  quant x2         34.016 ms   19.6%
  PL qkv           20.859 ms   12.0%
  dequant x4       14.947 ms    8.6%
  attention        54.058 ms   31.2%
  PL mlp            8.860 ms    5.1%
  residual x2       9.866 ms    5.7%
  sum             172.492 ms  (PL qkv+mlp = 29.719 ms, incl. cache flush/invalidate)
```

**读法**：
- 每行是该步骤在 12 层里的累计。"x2" 表示每层做两次。
- PL 两项合计 29.7 ms，与 cosim 的 12 × (1.55 + 0.62) = 26.1 ms 对上，多出的 3.6 ms 是 DDR 延迟和 cache 维护。
- PS 合计 143 ms，占 82%。**瓶颈不在 PL。**
- sum 与 forward 差 1 ms，是 embed 和分类头（不在分段里）。

### 每一项慢在哪、怎么改、为什么改完仍逐位一致

| 项 | 原因 | 改法 | 为什么结果不变 |
|---|---|---|---|
| attention 54 ms | q、k 按 (p,n) 布局，内积对 n 是 stride-6 跳读；每个内积单累加器串行，VFP 加法延迟 4～5 拍等着 | dequant 时把 q、k 转成 (n,p)；36 个分数放同一个 p 循环、36 个独立累加器 | 每个分数自己的 p 求和顺序不变 |
| quant 34 ms | 每个数调一次 libm `floor()`，31752 个数 × 24 次 | `(int)t` 截断 + 负数修正 | 与 floor 定义逐位相同 |
| normalize 30 ms | 三趟 stride-6 跳读 | 按 p 顺序扫，6 个累加器 | 每个 token 的求和顺序不变 |
| dequant 15 ms | 除法 | 乘 1/4096 | 2 的幂，逐位相同 |
| residual 10 ms | 正常 | 不动 | |

改完主机对拍 max|Δlogit| 仍是 4.263e-14，与改前一个数不差，证明"只改访问方式、不改运算顺序"做到了。

**但板上第一轮几乎无效（166.7 ms）**：attention 53.8、normalize 31.7 都没动。用 Vitis 自带的 `arm-none-eabi-objdump -d` 反汇编 `tsamapp/Debug/src/tt_net.o`，QK 内层是：

```
vldr  d16,[r2]        ; 从栈上读累加器 attn[n][c]
vldr  d17,[r3]        ; 读 k
vmla.f64 d16,d18,d17
vstmia r2!,{d16}      ; 写回栈
```

N 是运行时变量，`attn[N][N]`、`s[N]` 无法拆成寄存器，每次乘加读写一次栈并等 vmla 的 9 拍延迟。"跳读"的假设是错的，真正的瓶颈是累加器落栈。

**第二轮**把 N 做成模板参数（`attention_t<6>`、`normalize_t<6>`，运行时按 N 分派，`#pragma GCC unroll`），累加器进 VFP 寄存器。反汇编确认内层变成 7 条 `vldmia` + 6 条 `vmla`、零写回。板上 138.7 ms，attention 38.9、normalize 18.5。

### 第二轮的分段表

```
  normalize x2     18.546 ms   13.4%
  quant x2         24.323 ms   17.5%
  PL qkv           20.857 ms   15.0%
  dequant x4       16.322 ms   11.8%
  attention        38.933 ms   28.1%
  PL mlp            8.841 ms    6.4%
  residual x2       9.873 ms    7.1%
  sum             137.695 ms
```

剩下的 39 ms 不再是写法问题：每个 p 要从 7 条数据流各取一个 double，k 的三块共 127 KB 超过 32 KB 的 L1，每拍都在等 L2；A9 的双精度 VFP 每 2 拍才发一条 vmla。PS 用 double 到此为止，再往下是 float32 + NEON（放弃逐位对拍）或整层进 PL（附录 C）。

### 串口输出逐行讲解

```
=== Tensor Transformer on Zynq-7020 (unoverlapping, N=6) ===
```
模型名和 token 数来自 `tt_data.h` 的宏，由 PC 导出时写入。

```
class 0: board  -9.477316  ref  -9.477316  diff 2.13e-14
...
class 6: board +17.078711  ref +17.078711  diff 4.26e-14
```
9 行，每行三个数：板上算出的 logit、PC numpy 定点仿真的 logit、两者之差的绝对值。1e-14 量级是 double 加法在不同机器上舍入顺序的噪声，说明 PL 输出逐位相同、PS 浮点路径也一致。class 6 最大（17.08），对应第 7 类。

```
pixel 224,158  gt=7  board argmax=6  ref argmax=6  max|diff|=4.263e-14  -> PASS
```
像素坐标、真值类别（1 起）、板上 argmax（0 起）、参考 argmax、9 个差里最大的。PASS 条件：argmax 相同且 max|diff| < 1e-4。argmax 6 + 1 = 7 = gt，这个像素判对了。

```
forward time: 173.513 ms (12 layers, 24 PL launches + PS float glue)
```
XTime 计时，从 embed 到分类头，不含打印。

```
--- breakdown (12 layers total) ---
  normalize x2     29.886 ms   17.2%
```
分段表，见上。百分比以 forward time 为分母。

**没打出 breakdown 表**：说明用的是旧 `main.cpp`（第一次覆盖没生效），不是程序错。

## 3.6 平台脚本与 Vitis 设置 <a id="s3-6"></a>

### Vivado（脚本化，`vivado/build_tt_soc.tcl`）

```
create_project → ip_repo_paths = hls/ip_export
create_bd_design
source ps7_cfg.tcl        ← 上一个项目 conv_soc 的 processing_system7_0 完整 CONFIG（write_bd_tcl 导出）
关 HP2/HP3
create tucker_proj_0
apply_bd_automation ×3：GP0 → s_axi_CTRL；m_axi_FM → HP0；m_axi_WT → HP1，时钟 FCLK_CLK0 100 MHz
assign_bd_address / validate / make_wrapper
launch_runs impl_1 -to_step write_bitstream
write_hw_platform -include_bit → vivado/tt_soc.xsa
```

PS7 配置复用是关键：DDR 型号、MIO、UART0 在 MIO14/15、时钟树，一个字段错了板子就不出串口。从已经跑通的工程里 `write_bd_tcl` 导出再截取 `processing_system7_0` 那一段，比对着手册重填可靠。

### Vitis（GUI 手建）

| 项 | 设置 | 不设的后果 |
|---|---|---|
| 平台 | XSA = `vivado/tt_soc.xsa`，standalone，ps7_cortexa9_0 | |
| HLS 驱动 Makefile | 建平台后先跑 `tools/fix_hls_driver_makefile.py vitis/<平台>` | build platform 报 `#echo` 找不到（附录 F） |
| 应用模板 | Empty Application **(C++)** | C 模板编不过引用和结构体初始化 |
| 源文件 | `main.cpp` + `src/` 六个文件平铺进 src，**不加** `tt_hw_sim.cpp` | 重复定义 `tt_hw_proj` |
| Libraries | 加 `m` | 可能报 undefined reference to sqrt |
| Optimization | -O2 | 352 ms 而不是 173 ms |
| lscript | 默认即可，Stack 可调 0x10000 | .bss 约 1.3 MB 都在 DDR 段，默认够 |
| 换 XSA | Platform → Update Hardware Specification，然后**重跑** Makefile 修复脚本 | 驱动 Makefile 会被重新解出来 |

---

# 第四部分：整个项目的脚本、命令与产物 <a id="h4"></a>

每个脚本只做一件事，按流水线顺序排。全部在 `D:\TT_HSI_FPGA`，Python 用 `D:\pytorch\python.exe`（3.12 + torch 2.5.1）。

## 4.1 PC 侧（model/）

| 脚本 | 作用 | 输入 | 输出 | 怎么看结果 |
|---|---|---|---|---|
| `tt_model.py` | 去掉 utils.pyc 依赖的干净模型定义；`load(name)` 加载 checkpoint；`verify_mode_dot()` 核对模积约定 | 上游 .pth | 模型对象 | 直接运行：打印 `mode_dot == tensorly: True` 和两模型参数量 187017 / 197601 |
| `preprocess.py` | 复刻七步预处理；`LongKou` 类给出任意像素的模型输入 | LK .mat | (270,7,7) float32 | 直接运行：打印 padded 形状 (556,406,270) 和一个 patch 的统计（mean 0，std 1） |
| `measure_ranges.py` | 用真实权重 + 随机 patch 测每个中间量的极值，为定点选格式 | 模型 | 屏幕表格 | 看 PL 输入 ±5、输出 ±0.85、注意力分数到 −66 |
| `quant.py` | 定点仿真核心：`Fmt` 格式、`quant/dequant`、`tucker_proj_int`（逐位）、`pack_factors`、块布局转换 | | 被其他脚本 import | 不单独运行 |
| `fixed_point_sim.py` | 整网仿真：PL 算子换成定点、其余浮点；`Net.forward(patch, fixed, trace)`；`main()` 做格式扫描 | 模型、随机 patch | 屏幕表格 | 第一行 `float path vs torch` 必须 ~1e-15；表格看 argmax 一致率和 max\|Δlogit\| |
| `export_golden.py` | 导出权重 + 一个真实像素的黄金向量 + 整网参考 | `--pixel 224 158` | `data/*.bin`、`data/golden/*` | 打印 meta：gt、argmax、logits |
| `export_c_arrays.py` | 把 data/ 的二进制变成 `vitis/src/tt_data.c/.h` | data/ | 1.7 MB C 源码 | 打印 N 和文件大小 |
| `visualize.py` | 假彩色、真值、作者预测图、黄金像素位置 | LK .mat、上游 .mat | `data/vis/*.png` | 看图 |

复现顺序：`tt_model.py` → `fixed_point_sim.py`（约 3 分钟）→ `export_golden.py --pixel 224 158` → `export_c_arrays.py`。改定点格式时改 `quant.py::Fmt` 默认值和 `hls/src/tt_types.h` 的三个宏，两边必须一致，然后从 `fixed_point_sim.py` 重跑。

## 4.2 PL 侧（hls/）

| 文件 | 作用 |
|---|---|
| `src/tt_types.h` | 三种 ap_fixed 类型、尺寸宏；与 `quant.py::Fmt` 一一对应 |
| `src/tucker_proj.cpp` | 算子本体 |
| `tb/tb_tucker_proj.cpp` | 测试平台：读 `model/data/golden/`，两次调用（QKV、MLP），要求逐位 |
| `run_csim.tcl` | C 仿真 | 
| `run_csynth.tcl` | 综合 + 导出 IP 到 `tt_prj/sol_100mhz/impl/export.zip` |
| `run_cosim.tcl` | RTL 协同仿真 |
| `ip_export/` | 解压后的 IP，Vivado 用；每次重综合后重新解压 |

命令（在 hls/ 目录）：`D:\xilinx\Vitis_HLS\2020.2\bin\vitis_hls.bat -f run_xxx.tcl`。看什么：
- csim：日志末尾 `PASS: bit-exact`，四行 `mismatches 0`。
- csynth：`tt_prj/sol_100mhz/syn/report/tucker_proj_csynth.rpt` 的 Timing、Latency、Utilization；再看每个子函数报告里每个循环的 **achieved II**。
- cosim：日志 `C/RTL co-simulation finished: PASS`，`sim/report/tucker_proj_cosim.rpt` 的 min/avg/max 周期。

测试平台的两个坑：黄金文件路径要从 `__FILE__` 推（csim 的运行目录在 `tt_prj/sol/csim/build`）；所有指针缓冲要按 m_axi 的 depth（26460）分配，否则 cosim 包装器越界。

## 4.3 平台（vivado/）

| 文件 | 作用 |
|---|---|
| `ps7_cfg.tcl` | 上一个项目导出的 PS7 完整配置 |
| `prev_design_1.tcl` | 上一个项目整个 BD 的导出，只作参考 |
| `build_tt_soc.tcl` | 建工程 → BD → 综合实现 → XSA，一条命令 |
| `tt_soc.xsa` | 第二版，时序收敛 |
| `tt_soc_v1_wns-0.019.xsa` | 第一版，DSP 100%、19 ps 违例，板上首次 PASS 用的它 |
| `impl_utilization.rpt` / `impl_timing.rpt` | 实现报告，资源和时序以此为准 |

命令：`D:\xilinx\Vivado\2020.2\bin\vivado.bat -mode batch -source build_tt_soc.tcl`，约 20 分钟，控制台最后打 `IMPL DONE WNS=...` 和 `XSA: ...`。

## 4.4 PS 侧（vitis/）

见 3.1 节表。主机端验证：

```
cd D:\TT_HSI_FPGA
D:\mingw64\bin\g++ -O2 -std=c++11 -o vitis\host_test.exe vitis\host_test.cpp vitis\src\tt_net.cpp vitis\src\tt_hw_sim.cpp
vitis\host_test.exe
```

输出 12 行逐层 `max|x − ref|`（应 ≤ 4e-15）和 9 行 logits 对比，最后 `PASS`。**改 `tt_net.cpp` 后必须先跑这个再上板**，它把"胶水逻辑错"和"板子/驱动错"分开。

## 4.5 工具（tools/）

`fix_hls_driver_makefile.py`：删掉 HLS 驱动 Makefile 里 TAB+`#echo` 的 recipe 行。扫 `drivers/` 和 BSP 的 `libsrc/`，平台里三处副本一次修完。每次建平台或换 XSA 后跑。

## 4.6 数据与文档

| 位置 | 内容 |
|---|---|
| `D:\FPGAlearn\RemoteSensing_LK_data\` | `WHU_Hi_LongKou.mat`（550×400×270 float32，186 MB）、`_gt.mat` |
| `model/data/` | `weights_all.bin`、`w_L{l}_{proj}.bin`、`cls_token.bin`、`pos_embed.bin`、`classifier_*.bin` |
| `model/data/golden/` | 黄金向量与整网参考、`meta.txt` |
| `model/data/vis/` | 图片 |
| `docs/DESIGN.md` | 数值约定与布局的精简版 |
| `docs/TT_EXPLAINED.md` | 本文 |
| `.claude/progress.md` `.claude/pitfalls.md` | 进度与踩坑 |

---

# 附录 A：一页串起完整数据流 <a id="hA"></a>

```
PC
  LK 立方体 → 高斯 → 逐波段标准化 → 全局标准化 → 补零 → 取窗 → CHW → patch 标准化   = 13230 个 float32
  checkpoint → 48 组 (M1,M2,M3) → Q1.14 int16                                          = 144672 个 int16
  numpy：patch → embed → 12 × [norm → 定点模积×3 → attn → 残差 → norm → 定点模积 → 残差] → 分类头
        = 逐层参考 + 9 个参考 logits + 第 0 层黄金向量
  export_c_arrays → tt_data.c
                     │ elf 下载
                     ▼
PS
  embed：x[p*6+0] = cls[p] + pos；x[p*6+1+m] = patch[p*5+m] + pos
  每层：
    normalize → quant → flush → 写 9 寄存器 → start → 轮询 → invalidate    ┐ PL: QKV
    dequant(q,k 转 (n,p)；v 内存序) → attention → x = xn + ctx_flat          │
    normalize → quant → flush → start → 轮询 → invalidate                     ┘ PL: MLP
    x = xn2 + mlp
  token 1 → 2646→9 → argmax → 与参考对拍 → 串口
                     │ AXI-Lite / HP0 / HP1
                     ▼
PL  tucker_proj
  load_block(15878 拍) → [load_factors(3017) → 6×(mode1 1524 + mode2 392 + mode3 2660) → store_block(15895)] × n_proj
                     ▼
DDR  in[15876] out_q/k/v[15876] w_q/k/v[3014]  全 int16
```

# 附录 B：面试复述与自测 <a id="hB"></a>

## 三十秒版本

> 这个项目把一篇 2025 年 Pattern Recognition 的 Tensor Transformer 高光谱分类网络部署到 Zynq-7020。网络的核心是 Tucker 模积：一个 7×7×54 的张量依次乘三个小矩阵，占 95.7% 的算力，我把它做成一个 HLS 算子，模 1、模 2 各 49 路、模 3 有 54 路乘加并行，一次调用算 6 个 token 的 Q、K、V；归一化、注意力、残差留在 ARM 上用 double 做。
> 定点用 Q3.12 激活、Q1.14 权重、18 位中间量，格式是用整网仿真在 300 个真实像素上扫出来的。验证链是六环：模型复刻对上游 1e-15、预处理对作者预测图 100%、定点对浮点分类 100%、HLS csim/cosim 逐位、PS 胶水主机端 1e-15、板上 logits 对 PC 差 4e-14。
> 板上首版 352 ms，开 -O2 到 173 ms，分段计时显示 PL 只占 30 ms，瓶颈在 ARM 浮点的写法上，正在按"不改运算顺序只改访问方式"的原则压。

## 自测

| 问题 | 至少讲出 | 回看 |
|---|---|---|
| 模积和矩阵乘的区别？ | 沿一个轴的每根纤维乘同一个矩阵；三个轴各一个矩阵；顺序不影响数学结果 | 1.3 |
| 为什么参数只有 3014 个？ | 2646×2646 分解成 7×7 + 7×7 + 54×54 | 1.3 |
| 代码和论文哪三处不一样？ | 取 token 1、CHW 交错、V 按内存序切块 | 1.1 / 1.4 |
| 残差加在什么上？ | 归一化后的 xn，因为原代码 x 被覆盖了 | 1.4 |
| 为什么注意力不进 PL？ | 4.2% 算力（12 层合计）；分数到 −66 超出 16 位 | 1.5 / 2.1 |
| 定点格式怎么定的？ | 先量范围再整网扫描，Q3.12 是 logit 误差最小的拐点 | 1.5 |
| 为什么不用上一篇的 conv IP？ | 只用得上 32 路 pwconv；三个模轴不同要转置；分块机制是死重 | 2.1 |
| PL 一次调用做什么？ | 整块进片上一次，n_proj 个投影各自 load_factors → 每 token 三段 → store | 2.3 |
| 155350 拍怎么来的？ | 15878 + 3 × (3017 + 6×4576 + 15895) | 2.3.7 |
| DSP 为什么从 220 变 160？ | `(acc_t)x*w` 让乘法变 48 位；改原生位宽 | 2.4 |
| mode1 的 II 为什么是 4？ | 一拍写 7 个 t1[a][i2][j] 撞同一 bank | 2.3.3 / 2.5 |
| 板上 4e-14 的差是什么？ | double 舍入噪声；PL 逐位相同 | 1.6 / 3.5 |
| PS 143 ms 慢在哪？ | 跳读、单累加器、libm floor、除法 | 3.5 |
| 改完为什么还能逐位一致？ | 每个数的求和顺序不变，只改访问方式 | 3.5 |
| 板子判对了能说明模型准吗？ | 不能，一个像素；要 1000 像素 OA 对 91.6% | 1.6 |

# 附录 C：优化方向与适用边界 <a id="hC"></a>

按"先测后改"排序，每条写清楚验证方法：

| 方向 | 先解决什么 | 预期 | 验证 |
|---|---|---|---|
| PS 热点重写（已做，待上板） | 跳读、floor、除法、单累加器 | PS 143 → 约 40 ms | 主机对拍 4.263e-14 不变；板上分段表 |
| m_axi 位宽 16 → 64 | load/store 占 PL 41% | 63563 → 约 16000 拍 | cosim 逐位 + 周期；PS 侧 in/out 缓冲 8 字节对齐 |
| t1 按 dim=1 再分区 | mode1 II=4 | 1524 → 378 拍/token | csynth achieved II；csim 逐位 |
| mode3 双路（两个 (a,b) 位置并行） | 算力瓶颈 | 2660 → 1330 拍/token，DSP +54 | csynth DSP；Vivado 时序 |
| normalize / quant 进 PL | PS 两趟扫描 | 省 PS 时间，PL 加 sqrt/除法 | 逐位对拍会变（float vs 定点归一化），需重做格式扫描 |
| 多 patch 精度测试 | 只测过 1 个像素 | 1000 像素 OA 对 PC 91.6% | 需要数据通道（编进 elf 13 MB 或 SD） |
| 区域推理出图 | 板上还没出过图 | 64×64 区域 | 与 PC 预测图逐像素比 |

边界：本文所有周期数针对 N=6；重叠模型 N=10 时 PL 拍数按 2.3.7 的式子换 N，DDR 块 26460 个元素，`TT_NMAX=10` 已留够。改 N 以外的尺寸（7、54）要改 `tt_types.h`、`quant.py`、`tt_net.h` 三处宏并重跑全部对拍。

# 附录 D：容易背错的结论 <a id="hD"></a>

| 容易说错 | 准确说法 |
|---|---|
| 论文说取 cls token，所以分类头接 cls | 代码取 token 1，权重按此训练 |
| token 是连续 54 个波段 | ToTensor 转 CHW 后按内存序 reshape，token 内元素混着行、列、波段 |
| 残差是 x + attention(x) | 是 normalize(x) + attention |
| V 和 Q、K 一样 reshape | V 是 (N,2646) 按内存序切块，不是转置 |
| 模积顺序无所谓 | 数学上无所谓；定点有中间舍入，硬件固定 1→2→3 |
| Q6.9 沿用上一篇就行 | 输入 ±5、权重 ±0.27，Q6.9 浪费 3 位；扫描后选 Q3.12 |
| csynth 报 156 个 DSP 就是 156 个 | Vivado 实现 220 个（第一版）/ 160 个（第二版） |
| 写了 PIPELINE II=1 就是 II=1 | mode1 实际 II=4，看报告的 achieved II |
| cosim 通过就是板上通过 | cosim 没有 DDR 等待和 cache；板上多 12% |
| 板上一个像素 PASS 说明精度达标 | 只证明等价于模型；精度要多像素 OA |
| PL 是瓶颈 | 173 ms 里 PL 30 ms，PS 143 ms |
| 优化 PS 会破坏逐位一致 | 只改访问方式不改求和顺序，对拍 4.263e-14 不变 |
| 时序违例 19 ps 无所谓 | 这次没触发错误，不能推广；第二版已收敛 |

# 附录 E：证据、版本与数据表 <a id="hE"></a>

| 内容 | 来源 | 口径 |
|---|---|---|
| 模型复刻差 1e-15 | `tt_model.py` 自检 + 与上游类同输入对比 | 代码 |
| 预处理 100% 一致 | `preprocess.py` + 上游 `*_predict_result.mat`，1000 随机像素 | 代码 |
| 中间量范围 | `measure_ranges.py`，64 随机 patch | 代码 |
| 格式扫描表 | `fixed_point_sim.py --patches 100`；300 真实像素另跑 | 代码 |
| 单 patch 5413 万 MAC | 手算 + 上游 `analysis/audit_results.json` 的 profiler | 代码 |
| csim / cosim 逐位 | `hls/csim_run.log`、`hls/cosim_run.log` | 仿真 |
| 各函数拍数、II | `hls/tt_prj/sol_100mhz/syn/report/*_csynth.rpt` | 综合估计 |
| cosim 155350 / 62435 拍 | `hls/tt_prj/sol_100mhz/sim/report/tucker_proj_cosim.rpt` | RTL 仿真 |
| LUT 13012 / BRAM 85 / DSP 160 / WNS +0.374 | `vivado/impl_utilization.rpt`、`impl_timing.rpt` | 实现 |
| 第一版 DSP 220 / WNS −0.019 | 同上第一次构建（已被覆盖，XSA 保留） | 实现 |
| 352 / 173.5 ms 与分段表 | 串口，XTime，Vitis -O0 / -O2 | 板上 |
| 主机对拍 4.263e-14 | `vitis/host_test.exe` | 代码 |
| 工具版本 | Vitis HLS / Vivado / Vitis 2020.2；torch 2.5.1；Python 3.12.11 | |

# 附录 F：踩坑索引 <a id="hF"></a>

完整记录在 `.claude/pitfalls.md`，这里只列现象 → 一句话原因：

| 现象 | 原因 |
|---|---|
| numpy 复刻与 torch 差 4e-2 | 残差应加 xn，不是 x |
| 一开始不知道 patch 内存序 | ToTensor 转 CHW，模型直接 reshape |
| 同一个 normalize 两处结果对不上 | numpy std ddof=0，torch ddof=1 |
| cosim 第二次调用全错、csim 却过 | TB 缓冲比 m_axi depth 短，包装器越界 |
| load_block 综合 5 万拍 | 内层 trip 6 的嵌套循环；拍平 |
| Vivado DSP 220、WNS −19 ps | `(acc_t)x*w` 48 位乘法；改原生位宽 |
| Vitis 建平台 `#echo` 找不到 | HLS 驱动 Makefile 在 Windows make 下的老坑；脚本修三处 |
| 新应用向导报 export/tsam 不存在 | 平台还没 build 成功，向导缓存了旧状态 |
| 串口没有 breakdown 表 | 旧 main.cpp 没覆盖 |
| PS 优化后 logits 差 4.9 | ctx_flat 按 (n,p) 转置相加；应扁平相加 |
| mode1 II=4 | t1 写入撞同一 bank（尚未修） |

**本文只修改讲解文档，不修改源码、不运行新的综合或板测。** 所有数字都能在附录 E 的文件里找到。
