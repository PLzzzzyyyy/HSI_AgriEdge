# 整网引擎架构（PLAN §17 D1）

状态：2026-09-23 初稿；同日用户评审通过，并追加三项（int16 / int8 两版、分类头进 PL、取窗 + patch 归一化 + embed 进 PL），契约升为 v2 冻结。09-24 用户按 D3 结果定四项：立方体改 bfp（契约 v3，§3.6）、并列像素规则、max\|dlogit\| 验收线 0.06、int8 验收口径（§0 第 9 条）。§3（数值契约）与 §5（接口契约）以本文为准，`src/hls/tt_engine_regs.h` 是两边共用的机器可读版本。D2（M2）、D3（参考与注意力）、D4（M3a / M3b）、D5（int8 版）都按本文开发；改契约必须先改本文和头文件，再改代码。
前置：B3 黄金向量（`sim/golden/`）、C1 平台（`build/vivado/build_zu5ev.tcl`，IP 换掉即可复用）、v1.4 IP 作为 M1 基线与算法参考（`src/hls/tucker_proj.cpp`、`src/ps/tt_ref_int.h`）。板上数字一律以 Vivado 实现和串口为准，本文的拍数与资源都是估计，只用来做取舍。

## 0 决定（2026-09-23 用户评审）

| # | 决定 | 依据 |
|---|---|---|
| 1 | int16 版片上 data_t 用 **18 位 Q5.12**（±32，小数位不变）；DDR 输入仍 int16；mid_t 18 位 Q3.14、wt_t 16 位不变。报告里两版记作 **W16A18** 与 **W8A8** | §3.1：饱和像素 max\|dlogit\| 0.18～2.1 → ≤0.03，未饱和像素逐位不变；16 位 Q4.11 / Q5.10 所有像素都变差并有标签翻转。18 位在 BRAM / URAM / DSP 里不多占单元 |
| 2 | 注意力：**精确整数 scores + 查表 softmax（attn Q0.24）+ 整数 ctx**，不复刻 float32 | §3.4：整数加法与求和顺序无关，可并行、可五级逐位；float 保序累加每链 II = 4，36 链约 11k 拍，超过一个 job，且 expf 跨平台本来就不逐位 |
| 3 | 残差加在舍入后的 xn_q 上（整数加） | §3.3 |
| 4 | 并行度：投影核按编译参数 `TT_K3`（mode3 每拍位置数）参数化。**int16 版目标 E2（14），退路 E1（7）**；**int8 版目标 E2（14），冲刺 E3（21）**；E0（4）只作最后退路。E2 在 Vivado 过 150 MHz 就比 E1 @200 MHz 快，过不了按实测取舍 | §4.6。评分看性能与资源效率，利用率本身不加分 |
| 5 | P（片上 patch 数）做编译参数 `TT_P_MAX`；URAM 优先给 X 双缓冲与权重双库，余下给 P。P ≥ 3 后吞吐不再增加，报告如实写"P > 4 只换延迟与灵活性" | §4.5；int16 E2 下 URAM 估计只够 P = 4 |
| 6 | **分类头进 PL**（int16 权重逐类 2 的幂缩放，精确整数累加）。输出由 mode 选：默认**类别 + 置信度**（每像素 4 B），单点探查出全部 logits，调试出终块 / 逐层块 | §3.6。与 PLAN §5.2 的"标签与 softmax 最大值"、§5.5 单点探查对齐；写回从每像素 7,938 拍降到约 1 拍 |
| 7 | M2 与 M3 是同一 IP 的两种模式；**M3 必做**，分两步：**M3a** 输入 PS embed 后的块（能直接用黄金向量调整网），**M3b** 输入立方体（片上前端）。M3a 的输入口一直保留 | §4.7 |
| 8 | HLS 目标 200 MHz，Vivado 按 200 / 150 / 100 三档各出一版报告 | §4.6 |
| 9 | int8 版：同一源码 `TT_NUM=8`，激活与中间量 Q3.4、权重逐矩阵 2 的幂 int8、DSP48E2 双乘打包；**权重 QAT 重训**，验收线（09-24 用户改）：官方 Test OA 比 int16 版掉 ≤ 0.5 个点，且 int8 定点路径与 torch 假量化前向一致（标签 100%）；不再要求"对自身浮点路径一致率 ≥ 99%"；达不到退到只权重 int8。**09-26 用户改**：第二条改为"int8 精度用与板上逐位的整数参考在官方 Test 全集上算"，与假量化的一致率只作诊断；实测过线（§3.7） | §3.7 |
| 10 | **前端进 PL**：从 DDR 立方体（int16）取 7×7 窗、patch 归一化（整数）、embed（查表加 cls + 位置编码）直接写片上 X。PS 只剩装载、调度与 I/O；整景预处理（高斯 + 全景归一化）仍在 PC 导出时做（PLAN §14.2） | §3.6、§4.2 |
| 11 | （09-24 追加）**立方体 bfp**：每条光谱一个 2 的幂指数存波段 270，窗内按最小指数对齐，FRONT_S = 48，S1/Sxx 每像素重算；契约升 v3（寄存器与 DDR 尺寸不变）。**并列规则**：浮点模型前两名 logit 差 < 0.01 的翻转像素单列、不算失败。**max\|dlogit\| 验收线 0.06**（原 0.05） | §3.6、`sim/tolerance.md` |

## 1 结论摘要

- 一个 IP `tt_engine`：立方体 → 取窗 → patch 归一化 → embed → 12 层 → 分类头 → 类别 + 置信度，全链在 PL；权重包（投影因子 + embed 表 + 分类头）约 470 KB 全部驻片上。
- 投影核是全部性能的来源：mode1 → mode2 → mode3 三段 token 级 dataflow，mode3 一拍算 `TT_K3` 个空间位置 × 54 个输出，累加在 DSP 内部。E2（14 位置）每 token 每投影 189 拍，每像素 ≈ 56k 拍：**0.28 ms @200 MHz，0.37 @150，0.56 @100**（估计）。
- 其它工作（前端、归一化趟、scores、softmax、ctx+残差、MLP 残差、统计量、分类头）都是与投影核并行的侧单元，宽度随档位放大，靠 P 个 patch 轮转把依赖链藏起来。
- 数值：片上激活 18 位 Q5.12；归一化、注意力、残差、前端、分类头全部整数化，只有每个 token / patch 一次 float32 sqrt 与除法（IEEE，跨平台逐位）。PC 参考（numpy int64）→ 主机 C → csim → cosim → 板上，五级逐位，一直验到类别与置信度。浮点模型只用来评标签一致率与 logits 误差。
- 接口：同一套寄存器覆盖 PROJ（M2）、FULL + 块输入（M3a）、FULL + 立方体（M3b）；一次调用可给任意多个像素（整景巡检每行一次），引擎内部按 P 批处理。
- 两个版本：**int16 版（W16A18）**是主线；**int8 版（W8A8）**是 `TT_NUM=8` 编译，权重经 QAT。两版寄存器、DDR 布局、PS 代码相同。

## 2 计算特征与 v1.4 的时间去向

每像素（N = 6，12 层）：

| 项 | 乘加数 | 占比 | 说明 |
|---|---:|---:|---|
| Tucker 投影 mode3 | 41.15 M | 79.4% | 12 层 × 4 投影 × 6 token × 2646 × 54 |
| 投影 mode1 + mode2 | 10.67 M | 20.6% | 每 token 每投影 2 × 378 × 49 |
| scores + ctx | 2.29 M | 4.4%（另计） | 每层各 36 × 2646 |
| 归一化 | 24 趟 × 15,876 元素 | | 统计量 + 逐元素变换 |

v1.4 IP（M1 基线）每层 141,027 拍（cosim，QKV 96,940 + MLP 44,087），拆开看：token 级投影约 65k 拍、片上归一化趟 26k、块进出 DDR 24k、因子装载 6k、其余是统计量与流水启停。也就是说**真正算投影的拍数只占 46%**，而且 mode3 每拍只用 54 个乘法器。整网进 PL 要做的就是三件事：权重不再从 DDR 装、激活不再进出 DDR、mode3 并行度提 7 倍。

每层的依赖链（同一 patch 内串行，无法打散）：

```
stats(x) → 归一化趟 → Q → K → scores → softmax → V → ctx+残差 → stats(x') → 归一化趟 → M → 残差 → stats(x'')
```

单 patch 走这条链，投影核会在 scores/softmax/ctx/归一化趟上空等约 30%；所以引擎同时持有 P 个 patch，A 在 ctx 时 B 在投影（§4.5）。

## 3 数值契约

### 3.1 data_t：18 位 Q5.12

实验（`model/format_scan.py`，结果 `report/format_scan_pc.md`）：在 `fixed_regression.py` 抽过的三景 4,700 个官方 Test 像素上，把 PL 投影路径换成候选格式，与同一 checkpoint 的全浮点路径比：

| 景（像素 / 饱和像素） | 格式 | 标签一致率 | max\|dlogit\| 全部 / 饱和 / 未饱和 | mean\|dlogit\| |
|---|---|---|---|---|
| LongKou 900 / 16 | Q3.12/16（现状） | 100% | 0.177 / 0.177 / 0.011 | 0.00101 |
| | Q4.11/16 | 100% | 0.014 / 0.005 / 0.014 | 0.00101 |
| | Q5.10/16 | 100% | 0.015 / 0.005 / 0.015 | 0.00174 |
| | **Q5.12/18** | 100% | **0.011 / 0.004 / 0.011** | **0.00066** |
| HongHu 2200 / 17 | Q3.12/16 | 100% | 0.222 / 0.222 / 0.027 | 0.00150 |
| | Q4.11/16 | 99.95%（1 翻） | 0.037 / 0.007 / 0.037 | 0.00217 |
| | Q5.10/16 | 99.95%（1 翻） | 0.065 / 0.013 / 0.065 | 0.00384 |
| | **Q5.12/18** | 100% | **0.027 / 0.005 / 0.027** | **0.00143** |
| HanChuan 1600 / 42 | Q3.12/16 | 100% | 2.104 / 2.104 / 0.025 | 0.00297 |
| | Q4.11/16 | 99.88%（2 翻） | 0.565 / 0.565 / 0.051 | 0.00251 |
| | Q5.10/16 | 99.94%（1 翻） | 0.076 / 0.030 / 0.076 | 0.00419 |
| | **Q5.12/18** | 100% | **0.025 / 0.015 / 0.025** | **0.00157** |

读法：
- Q5.12/18 对未饱和像素的结果与 Q3.12 **逐位相同**（小数位一样，只是范围 ±8 → ±32），只有 1～3% 的饱和像素改变，而且改向浮点模型（max\|dlogit\| 从 0.18～2.1 降到 ≤ 0.03）。
- 16 位的 Q4.11 / Q5.10 用范围换分辨率，未饱和像素的误差反而增大 1.3～3 倍，mean\|dlogit\| 增大，HongHu 各 1 个、HanChuan 2 个 / 1 个标签翻转；Q4.11 在 HanChuan 仍有 0.57 的饱和误差。不取。
- mid_t 加宽到 20 位 Q5.14 与保持 18 位 Q3.14 结果逐位相同（三景全部像素），说明模 1/模 2 中间量从不饱和，mid_t 不改。

代价：ZU5EV 的 BRAM 原生 18 位宽、URAM 72 位 = 4 × 18、DSP48E2 是 27 × 18，18 位激活在存储和乘法器上都不多花一个单元，只有加法器和 mux 宽 12%。

定义（`src/hls/tt_types.h` M3 编译配置；`model/quant.py::Fmt(DF=12, WF=14, MF=14, DB=18, WB=16, MB=18)`）：

| 量 | 类型 | 格式 | 范围 | 用在哪 |
|---|---|---|---|---|
| data_t | ap_fixed<18, 6, AP_RND, AP_SAT> | Q5.12 | ±32 | 片上激活：X（残差流）、XN（归一化块）、Q/K/V、投影输出 |
| mid_t | ap_fixed<18, 4, AP_RND, AP_SAT> | Q3.14 | ±8 | 模 1、模 2 之后（不变） |
| wt_t | ap_fixed<16, 2> | Q1.14 | ±2 | 因子（不变，权重包投影段 = weights_all.bin 原样） |
| acc_t | ap_fixed<48, 20> | | 不舍入不饱和 | DSP 内部累加（不变） |
| DDR 输入 | int16 | Q3.12 / 立方体 | | M3a：x_embed（与 v1.4 相同，符号扩展到 Q5.12）；M3b：立方体（§3.6） |
| DDR 输出 | 32 位 | | | CLASS / LOGITS / FEAT（§5.2）；FEAT 为 Q5.12 整数符号扩展，PS 乘 2^-12 |

舍入位置与 v1.4 完全相同（模 1 后、模 2 后舍到 mid_t，模 3 后舍到 data_t，AP_RND + AP_SAT）。M2 编译配置用 DB = 16（Q3.12），其余相同（§4.7）。

已知未覆盖（M3a）：PS embed 输出 int16 Q3.12，patch 归一化后个别元素 > 8 时在 PS 量化处饱和（与现状相同）。M3b 由 PL 前端直接写 18 位 X（§3.6），这个问题不存在；D3 的 `engine_ref.py` 顺带统计 M3a 路径的饱和比例。

### 3.2 token 归一化（沿用 v1.4 整数算法，位宽随 18 位放大）

算法不变（`src/ps/tt_ref_int.h::normalize`）：S1 = Σx、Sxx = Σx² 精确整数；var_num = D·Sxx − S1²；mean_q24 = (S1 << 12) / D 向零截断；inv = 10835968.0f / sqrtf((float)var_num)，clamp ≤ 127，inv_q24 = trunc(inv · 2^24)；q = sat((x << 12 − mean_q24) · inv_q24 + 2^35) >> 36。
位宽（x 18 位）：|S1| < 2^29、Sxx < 2^46、var_num < 2^57、|mean_q24| < 2^30（int32 够）、|d| < 2^31、d · inv_q24 < 2^62；输出饱和到 18 位。INV_C 只依赖 D 与 DF，不变。sqrtf 与除法是 IEEE 正确舍入，hls::sqrt / A53 / x86 逐位一致（v1.4 已验）。

实现上归一化块**只算一趟**：stats 在写 X 时顺带累计（写多少拍就 8 个平方器），token_stats 6 个 token 流水约 120 拍，然后归一化趟从 X 读、写 XN（8 元素/拍，1,985 拍）。投影核（mode1）和残差都读 XN。v1.4 的 normalize_block 是 2 元素/拍 13,230 拍，这里是同一算法的 4 倍宽版本。

### 3.3 残差（整数加）

```
x'  = sat18(xn_q  + ctx_q)      ctx_q 见 3.4，Q5.12
x'' = sat18(xn2_q + m)          m 为 MLP 投影输出，Q5.12
```
xn_q 是 3.2 的舍入结果（Q5.12），和投影用的是同一个值。现状 PS 用 float32 未舍入的 xn 做残差再量化，与本定义差在 LSB 级；M3 参考按本定义重新生成（§3.5）。

### 3.4 注意力（精确整数 scores，定点 softmax，整数 ctx）

为什么不复刻 float32：PS 的 scores 是 36 条 float32 累加链各 2646 步、按 p 升序；PL 里 mode3 每拍产出同一 token 的 8 个 p，保序累加要求一拍内串 8 次 fadd，做不到；即使缓冲后按 1 元素/拍算，每链 II = fadd 延迟（4 拍），36 链共享也要 ~11k 拍，超过一个 job。再者 expf 在 x86 / A53 / hls::exp 之间本来就只在 ulp 级一致，float 方案永远做不到逐位。整数方案所有中间量精确、与并行度和求和顺序无关。

定义（q、k、v 为 Q5.12 整数；全部 int64 可算，`model/engine_ref.py` 与 HLS 共用常量与表）：

```
s[n][c]   = Σ_p q[p][n] · k[p][c]                     精确，Q10.24，|s| < 2^46，48 位累加
m[n]      = max_c s[n][c]
d         = m[n] − s[n][c]  (≥ 0，Q.24)
e[c]      = 0                                         若 d ≥ 25 · 2^24（exp(−25) < 2^-24 的 LSB）
          = ((T_HI[f >> 8] · T_LO[f & 255] + 2^23) >> 24) >> i   否则
            其中 u = d · LOG2E_Q24（Q.48，LOG2E_Q24 = round(log2(e) · 2^24) = 24204406）
                 i = u >> 48（0..24），f = (u >> 32) & 0xFFFF
                 T_HI[a] = round(2^(−a/256) · 2^24)，T_LO[b] = round(2^(−b/65536) · 2^24)，各 256 项 Q0.24（LUTRAM）
S         = Σ_c e[c]                                  2^24 ≤ S < 6 · 2^24
r         = floor(2^47 / S)                           ≤ 2^23，每行一次整数除法（每层每 patch 6 次，串行除法器即可）
attn[n][c]= (e[c] · r + 2^22) >> 23                   Q0.24，≤ 2^24
ctx(441s + m, t) = Σ_c attn[s][c] · v(441c + m, t)    精确，Q5.36（24 + 12 位小数）
ctx_q     = sat18((ctx + 2^23) >> 24)                 Q5.12
```
ctx 的下标形式来自原模型 V 按内存序切块的语义（`tt_net.cpp` 头注释）：N = 6 时 D = 6 × 441，扁平下标 i = 6p + t 的段号 s = p / 441、段内偏移 6(p mod 441) + t，所以 ctx 对元素 (p, t) 是同一 token t、6 个相距 441 的 p 的加权和，权重是第 s = p/441 行的 attn。这一步不需要转置，也不需要按 token 分块。

精度：表与乘积各 ≤ 2^-25 相对误差，截掉的 16 位以下小数 ≤ 1.1e-5 相对误差，attn 误差 ~1e-5，ctx 误差 ≤ 1e-5 × Σ|v| ≲ 1 LSB（Q5.12）。D3 先在 PC 上用三景回归像素跑 `engine_ref.py` 比标签一致率与 dlogit，不达标（一致率 < 现状或 max\|dlogit\| > 0.05）再把 attn 加宽到 Q0.28，寄存器不变。

单元成本：scores 24 个 DSP（4 元素/拍 × 6 token，从 K 流缓冲读），softmax 约 6 个 DSP + 2 个 256 项 ROM + 1 个 48/27 位除法器，ctx 24 个 DSP（每 4 个 m 用 6 拍算 144 次乘加）。

### 3.5 参考实现与黄金向量

| 编译 / 模式 | 数值定义（唯一来源） | 主机 C 参考 | 黄金向量 | 用途 |
|---|---|---|---|---|
| M2（DB = 16，PROJ） | 现有 `model/quant.py` + `fixed_point_sim.py`（不改） | 现有 `tt_ref_int.h` / `tt_hw_sim.cpp`（不改） | 现有 `sim/golden/n6_real`：每层 x_embed / x_mid / x_out 是输入，q/k/v/mlp/stats 是期望 | D2 csim 直接回放 12 层 × 2 次调用，逐位 |
| M3a（DB = 18，FULL，块输入） | 新 `model/engine_ref.py` 入口 A：从 int16 Q3.12 的 x_embed 起，归一化（3.2）、投影（3.1）、注意力（3.4）、残差（3.3）、分类头（3.6） | 新 `sim/host/engine_ref.cpp`，与 Python 逐位 | 新 `sim/golden/n6_engine/`：每层 xn_q、q、k、v、s、attn、x_mid、xn2_q、m、x_out，终块、logits、类别、置信度 | D3/D4 csim、cosim、板上 FULL + DUMP 逐位 |
| M3b（同上，立方体输入） | `engine_ref.py` 入口 B：从 int16 立方体起，前端（3.6）接入口 A 之后的全部 | 同上 | 同上，另加立方体窗、patch 统计量、x_embed（18 位） | D4b，前端单独 csim 再并入 |
| int8 版 | `engine_ref.py --num 8`（QAT 权重） | 同上 | `sim/golden/n6_engine_i8/` | D5 |

M3 的黄金向量与 M1/M2 的在 LSB 级不同（3.1 饱和、3.3 残差、3.4 注意力、3.6 前端与分类头），这是定义的改变不是误差；报告里 M3 的"逐位"指对 `engine_ref.py`，精度指对浮点模型的标签一致率与 dlogit（PLAN §16.5 口径）。`engine_ref.py` 在三景回归像素上的结果追加到 `report/accuracy_fixed_pc.md`，另加一列"参考版本"。

### 3.6 前端与分类头（都在 PL）

**立方体**（`export_scene.py` 输出 `cube_i16.bin`，契约 v3 bfp）：沿用 PC 预处理（高斯 + 全景归一化 + 3 像素零边，`preprocess.py`）的 float 结果 x，**每条光谱一个 2 的幂指数**：e = min(15, floor(log2(32767 / max_b\|x_b\|)))（全零光谱 e = 15），q_b = round(x_b · 2^e)（不会饱和），e 存波段 270，波段 271 补 0。布局 HWC，每像素 272 个 int16，544 B，与 v2 尺寸相同。

为什么不用 v2 的整景一个 k：HanChuan 有离群亮点（max\|x\| = 115.8），整景 k 只能取 8，暗平 patch 的 σ 只有约 29 LSB，量化噪声约 1%，入口 B max\|dlogit\| 0.34、2 个翻转；允许少量饱和（k = 11）又让亮 patch 出错（HongHu 0.38）。bfp 下三景前端单列误差 0.005 / 0.012 / 0.017（`sim/tolerance.md` §3）。

**窗内对齐**：取窗后 49 条光谱取 e_min，每个元素 a = (q + 2^(s−1)) >> s，s = e − e_min（s = 0 不动）；a 仍 ≤ 16 位。patch 归一化对整窗统一缩放不变，所以对齐到 e_min 只丢精度、不改语义。

**patch 归一化**（每像素一次，n = 13,230，无偏 ddof = 1，与 `preprocess.patch_tensor` 同义）：

```
S1 = Σ a，Sxx = Σ a²                         精确，|S1| < 2^29，Sxx < 2^44（48 位）
V  = n·Sxx − S1²                             < 2^58，int64
d  = n·a − S1                                精确，|d| < 2^30；不需要先算均值，没有均值截断
g  = trunc(C_P / sqrtf((float)V) · 2^s)      每像素一次 float32 sqrt + 除法，C_P 只依赖 n（含 sqrt((n−1)/n)）
xn = d · g >> t                              Q.24，符号保留
```
D3 定死（09-24）：s = FRONT_S = 48，t = s − 24 = 24，g ≤ GMAX = 2^25 − 1（25 位，乘法 2 个 DSP）；C_P = float32(sqrt((n−1)/n) · 2^48)，g = trunc(min(C_P / sqrtf((float)V), GMAX))。对齐后 sqrt(V) 范围窄，三景回归像素 g ∈ [2^20.2, 2^24.3]，不截断。
实现：对齐量 s 取决于窗内 e_min，每个像素不同，所以 S1 / Sxx **每像素对 49 条光谱重算**（不再按光谱部分和滑窗复用）：13,230 元素 / w，E2 约 830 拍，远小于每像素约 56k 拍；WIN 里存原始 q 与 e，读出时移位。

**embed**（与 `tt_net.cpp::tt_embed` 同义，单次舍入）：

```
x_embed(p, 0) = sat18((EMB(p, 0) + 2^11) >> 12)                    cls + 位置编码，常数
x_embed(p, n) = sat18((xn(e) + EMB(p, n) + 2^11) >> 12)，n = 1..5   e = 5p + (n − 1)
```
EMB 是权重包里的 int32 Q.24 表（cls_token + pos_embed，15,876 项）；e 是 patch 的 CHW 扁平下标 c·49 + h·7 + w（`preprocess.py` 头注释），所以 e → (c, h, w) 是固定置换，用跑动计数器生成。int8 版把 `>> 12` 换成 `>> 20` 得 Q3.4。M3a 的块输入走 PS 的 float embed + Q3.12 量化，结果与 M3b 在 LSB 级不同，两个入口各有黄金向量。

**分类头**（token 1 的 2,646 个元素 × 类别数，`tt_net.cpp::head` 同义）：

```
acc_c   = Σ_p W_c[p] · x(p, 1)                  W_c int16，逐类小数位 e_c（使 max|W_c| 落在 [2^14, 2^15)），精确，< 2^45
l_c     = ((acc_c + 2^(r−1)) >> r) + b_c        r = DF + e_c − 16，l_c 为 Q.16（int32），b_c 为 Q.16 偏置；D3 核对 r ≥ 1
label   = argmax_c l_c                          并列取小下标（与 numpy / tt_net 一致）
conf    = min(0xFFFF, floor(2^40 / Σ_c E(l_max − l_c)))   E 为 §3.4 的定点 exp（输入由 Q.16 左移 8 位到 Q.24），Q0.16
```
DF 为激活小数位（int16 版 12、int8 版 4）；int8 版也用这套 int16 分类头权重。exp 表与除法器与 SOFTMAX 单元共用。最大 softmax 值只是模型分数（PLAN §5.2）。

**精度验收**（D3，`engine_ref.py` 入口 B 对浮点模型，三景 4,700 个回归像素）：标签一致率 100%（并列像素——浮点模型前两名 logit 差 < 0.01——单列、不算失败），max\|dlogit\| ≤ 0.06（09-24 用户由 0.05 放宽：HanChuan 入口 B 为 0.053，是前端 0.017、注意力 0.018、Q5.12 投影 0.025 叠加，没有单个部件超标）；前端与分类头各自的误差单独列一行（把其它部分换回浮点），不达标时先加宽 g、EMB 或 W。

### 3.7 int8 版（`TT_NUM=8`，用户 09-23 要求 int16、int8 各出一版）

定义（`model/quant.py::Fmt(DF=4, WF='pm', MF=4, DB=8, WB=8, MB=8)`，即 `format_scan.py` 的 "all8 pm: act Q3.4" 行）：

| 量 | 格式 | 说明 |
|---|---|---|
| data_t | int8 Q3.4（±8，LSB 1/16） | 片上激活 X/XN/Q/K/V；M3b 前端直接出 Q3.4（§3.6）；块输入（M3a / 调试）仍 int16 Q3.12，装载时舍入；FEAT 输出 int32 整数值，返回值 [23:16] 报小数位 4 |
| mid_t | int8 Q3.4 | 模 1、模 2 之后；必须 8 位，mode2 / mode3 的乘法才能打包 |
| wt_t | int8，逐矩阵 2 的幂缩放 | 每个 M1/M2/M3 自己的小数位 e = floor(log2(127 / max\|w\|))，值域 ±127（不用 −128，打包段累加 16 项不溢出）；权重包投影段 = 144,672 B 权重 + 144 B 指数表（48 投影 × {e1, e2, e3}）+ 16 B 补 0（头文件） |
| acc | DSP 48 位 | 舍入位置同 §3.1（模 1、模 2 后到 mid_t，模 3 后到 data_t），移位量由各矩阵指数决定 |
| 注意力 | 同 §3.4，位宽随 8 位激活缩小（s < 2^30，ctx 累加 < 2^40） | attn 仍 Q0.24 |

PTQ（训练后直接量化、不重训）在三景回归像素上的结果（`report/format_scan_pc.md`，set int8；每格：标签一致率 / max\|dlogit\| / mean\|dlogit\|，对同一 checkpoint 的浮点路径）：

| 格式 | LongKou 900 | HongHu 2200 | HanChuan 1600 | 结论 |
|---|---|---|---|---|
| Q3.12/16（现状） | 100% / 0.18 / 0.0010 | 100% / 0.22 / 0.0015 | 100% / 2.10 / 0.0030 | 对照 |
| 只权重 int8，固定 Q0.7 | 99.4% / 1.22 / 0.049 | 98.9% / 2.39 / 0.161 | 98.3% / 1.30 / 0.106 | 单一定标浪费位数，不行 |
| 只权重 int8，逐矩阵 2 幂 | **100% / 0.27 / 0.020** | **99.7% / 0.66 / 0.047** | **99.5% / 1.07 / 0.039** | 可直接用；只省存储不省 DSP |
| 只激活 int8 Q3.4 | 99.6% / 0.86 / 0.11 | 98.4% / 2.95 / 0.24 | 96.9% / 4.35 / 0.26 | 激活是主要损失源 |
| 只激活 int8 Q4.3 | 99.0% / 1.93 / 0.27 | 95.6% / 6.64 / 0.57 | 94.1% / 5.45 / 0.57 | 8 位下分辨率比范围重要 |
| 全 int8：Q3.4 + 权重 2 幂 + mid Q3.4 | 99.1% / 1.73 / 0.19 | 95.4% / 7.19 / 0.57 | 95.4% / 5.03 / 0.49 | **int8 版的格式；PTQ 不够，要 QAT** |
| 全 int8：Q4.3 | 98.4% / 2.67 / 0.46 | 84.0% / 11.4 / 1.43 | 86.8% / 11.1 / 1.22 | 不取 |

抽样 OA 在各格式之间 ±0.8 个点内随机波动（900～2200 像素，1 个像素 = 0.05～0.11 个点），只有 Q4.3 全 int8 在 HongHu / HanChuan 掉 4～7 个点；判据用标签一致率。读法：因子 max\|w\| < 0.28（`docs/legacy_7020/DESIGN.md`），逐矩阵缩放后 int8 几乎无损，固定 Q0.7 白白丢 2 位以上；损失主要来自激活 Q3.4（归一化后 σ = 1 的 token 只有 4 位小数），mid_t 压到 8 位再丢 1～3 个点。

全 int8 PTQ 的一致率 95～99% 不能交付，所以 int8 版必须 **QAT**：`train_scene.py --qat`，前向在三处（归一化输出、模 1 输出、模 2 输出）插入 Q3.4 假量化（STE），权重按逐矩阵 2 幂假量化，从 float checkpoint 起续训 50～100 轮；`export_scene.py` 输出 `weights/vN_int8/weights_engine.bin`（投影段 int8，EMB 与分类头段同 int16 版）。验收线（09-23 定，09-24 用户改）：官方 Test100 OA 比 int16 版掉 ≤ 0.5 个点，且 int8 的精度一律用与板上逐位的整数参考（`engine_ref.py --num 8`，全集用 `model/engine_gpu.py`）在官方 Test 全集上算，与 torch 假量化前向的标签一致率只作诊断（09-26 用户改。原为"与假量化前向标签 100% 一致"：整数引擎比 QAT 多三处 Q3.4 量化——前端输出、残差里的 xn、注意力输出 ctx——实测一致率 99.1% / 96.6% / 93.6%，只要训练前向不与引擎逐位相同就到不了 100%）；删去"对自身浮点路径标签一致率 ≥ 99%"——依据：HongHu PTQ 对自身浮点一致率只有 95.4%，但官方 Test OA int8 0.8508 反而比浮点 0.8482 高 0.26 个点，一致率衡量的是与浮点模型的差别而不是分类好坏（`report/accuracy_int8_pc.md`）；达不到就退到"只权重 int8"（上表第三行，PTQ 即可，权重存储减半、吞吐不变）。QAT 只改训练与导出脚本，引擎不变。09-26 实测（`report/accuracy_int8_pc.md`，整数引擎，官方 Test 全集）：int8 OA 0.9402 / 0.8464 / 0.8570，比 int16 引擎（0.9384 / 0.8482 / 0.8590）+0.18 / −0.19 / −0.20 点，过线，契约不改；混合精度对照（投影核 8 位，残差 / ctx / 前端 / 分类头 18 位，只在参考里实测）0.9392 / 0.8505 / 0.8585，与假量化相差 ≤ 0.02 点，作消融数据。

硬件（与 int16 版同一源码，`TT_NUM=8` 时）：
- DSP48E2 双乘打包（Xilinx WP486 的思路）：27 位 A 口装两个 int8（t2 的两个位置，`a1 << 19 | a2`，19 位间隔），18 位 B 口装一个权重，一拍两个 8×8 乘加在同一个 DSP 内累加；54 项按 16 + 16 + 16 + 6 分四段在 DSP 内累加（每段 16 × 127 × 128 < 2^18，低段不侵入高段），段间在 LUT 加法器（每 DSP 两个 22 位）合并并做低段符号修正。mode1 / mode2 同样打包（两个输出共享一个输入）。
- 档位（`TT_K3`，拍数与 DSP 见 §4.6）：E1-i8 = 7 位置，239 DSP，拍数同 int16 E1；**E2-i8 = 14 位置（两个 a 同拍），投影核 476 DSP，189 拍/token**；E3-i8 = 21 位置（三个 a 同拍，每 job 42 个 a 正好 14 组），投影核约 740 DSP，126 拍/token。
- 存储：72 位字装 8 个 int8（切片对齐布局不变，每块 ≈ 2,016 字，两块合用一个 URAM）；W_M3 每库 7 个 URAM。LUT：打包的段间加法与符号修正约 50 LUT/DSP，E2-i8 约 +19k、E3-i8 约 +30k。
- 报告口径：int8 版对 QAT 模型的整数参考逐位（`engine_ref.py --num 8`），对浮点模型只报一致率与 OA；两版同一批像素、同一时钟档并排列表，这就是 PLAN §7 第 4 / 6 条的设计空间曲线。

## 4 引擎结构

### 4.1 投影核（mode1 → mode2 → mode3，token 级 dataflow）

每个 job = 一个 (patch, 层, 投影) 的 6 个 token；token 之间 dataflow 重叠，稳态每 token 378 拍（E1）。

| 段 | 每拍做什么 | 乘法器 | 拍/token | 读 | 写 |
|---|---|---:|---:|---|---|
| mode1 | 固定 (i2, j) = r，7 个 i1 输入 × 7 个 a 输出 | 49 | 378 | XN：每 4 个 r 取 7 个字（每 i1 一个字，切片对齐，见 4.3） | t1[a][i2][j]，49 个 bank（a, i2） |
| mode2 | 固定 (a, j)，7 个 i2 输入 × 7 个 b 输出 | 49 | 378 | t1 一拍 7 个 bank | t2[a][b][j]，7 个 bank（b） |
| mode3 | 固定 a，7 个 b（位置）× 54 个 c，同一 j；54 拍算完一组 7 个位置的 378 个输出；48 拍内按 p 连续顺序倒出（8 元素/拍） | 378 | 7 组 × 54 = 378 | t2 一拍 7 个 bank，M3 权重列 j 一拍 54 个 | 输出流 8 元素/拍，去向由 job 决定（Q 缓冲 / K 流缓冲 + scores / V 缓冲 / RES2） |

- mode3 是 v1.3 `TT_MODE3_DUAL`（2 个位置）的 7 位置版：7 个位置就是一个 a 的全部 b，t2 按 b 分 bank 正好一拍供 7 个；累加在 DSP48E2 内部 48 位完成，不需要片上加法树；组末 378 个结果进 pend 寄存器（378 × 18 位），在下一组累加的 54 拍里以 2 个 72 位字/拍倒出，输出顺序是 p = 378a … 378a + 377 连续。
- 权重：M3 按 c 分 54 个 bank（4 个 bank 拼一个 URAM 的 72 位字），每 bank 48 个投影 × 54 个 j = 2,592 项，用第 0 口读；M1/M2 按 (a, i1) / (b, i2) 各 49 个 bank × 48 项，LUTRAM。装载走 URAM 第 1 口，所以双库时可以边算边装。
- 档位：mode3 一拍 K3 个位置（编译参数 `TT_K3`）。K3 = 14（E2）时一组是两个 a（每 job 42 个 a 正好 21 组，允许跨 token 配对），mode1 / mode2 各 98 个 DSP，t2 再按 a 奇偶分 bank，倒出 16 元素/拍；K3 = 4（E0）时 13 组 × 54 = 702 拍/token，mode1 / mode2 有空拍。只改 K3 与分 bank 因子，数值不变。
- 所有片上地址用跑动计数器，不出现变量乘除（v1.2 教训，pitfalls 继承条）；全部偏移量 32 位无符号（pose6d 教训）。

### 4.2 侧单元（与投影核并行）

宽度 w = 8 · K3 / 7 元素/拍（E1 8、E2 16、E3 24）。规则：每个单元对一个 patch 一层的工作量 ≤ 该 patch 一层的投影时间 4 × 6 × 拍/token（E1 9,072、E2 4,536、E3 3,024 拍），且在各自的依赖窗口内完成（§4.5），这样投影核不空等。

| 单元 | 触发 | 做什么 | 拍数（E1 / E2） | DSP（E1 / E2） |
|---|---|---|---|---|
| FRONT | 每像素一次（CUBE 模式） | 取窗：每像素只读 1 列新光谱 × 7 行 = 1,904 个 int16（476 个 64 位字，含指数波段）写 WIN；求窗内 e_min；S1/Sxx 一趟（读 WIN、按 e − e_min 移位、累计，v3 每像素重算）；patch 统计量（1 次 sqrt + 除法）；NORM + EMBED 趟写 X（同样移位，复用 NORM 的乘法器） | 取窗 ≈950；S1/Sxx 13,230 / w ≈ 1,654 / 827；统计 ≈60；写 X 15,876 / w = 1,985 / 992 | 平方器 w（与 RES2 共用）+ w 个 4 位移位器 |
| LOAD | 每 patch 一次（非 CUBE 模式，M3a / PROJ） | x_in（int16）→ X，符号扩展；顺带累计 S1/Sxx | 3,969（64 位 AXI） | 同上 |
| STATS | X 写完 | 6 个 token 的 mean_q24 / inv_q24（整数除法 + float sqrt/除法，流水） | ≈120 | ≈4 |
| NORM | STATS 后 | X → XN，w 元素/拍；每层两趟，另加 FRONT 每像素一趟（摊到每层 1/12） | 1,985 / 992 每趟 | 4w = 32 / 64（M3 定义里乘法可缩到 2w，D3 定） |
| SCORES | K job 的倒出 | k 进 KS；从 Q 缓冲 6 平面各读 w/2 元素/拍，48 位累加 | 3,969 / 1,985（窗口 K + V 两个 job = 4,536 / 2,268） | 3w = 24 / 48 |
| SOFTMAX | SCORES 后；分类头之后 | §3.4 的 36 个 e、6 次除法、36 个 attn；分类头的 ncls 个 e 与 1 次除法 | ≈300 | ≈6 |
| CTX+RES | V job 结束且 attn 就绪 | 按 (t, m) 扫：读 V、XN，写 X；顺带累计 S1/Sxx | ≈4,000 / 2,000（窗口 ≥ 6,804 / 3,402） | 3w + 6 平方器 |
| RES2 | M job 的倒出 | x'' = xn2_q + m，写 X；顺带累计 S1/Sxx | 与 M job 同步 | 平方器 w |
| HEAD | 第 12 层 RES2 结束 | 读 X 的 token 1（1 元素/拍）× 24 个类别并行乘加，接 SOFTMAX 出置信度 | 2,646 + ≈40（每像素一次） | 24 |
| OUT | HEAD 后 / 调试 | CLASS：每像素 4 B，攒满 64 B 一次突发；LOGITS：128 B；FEAT：7,938 拍 / 像素（只调试用） | ≈1（CLASS） | |

NORM 在 E1 / E2 / E3 下每 patch 每层都是 ≈ 4,100 / 2,070 / 1,380 拍，约占投影时间的 46%，余量足够；SCORES 与 CTX 按窗口计占 88% / 59%，是最紧的两个，w 不够时先加宽它们。

### 4.3 片上存储

字 = 72 位 = 同一 token 的 4 个连续 p（int8 版 8 个）。**X/XN/V 按 i1 切片对齐**：每个 i1 切片 378 个元素占 95 个字（补 2 个空位），每 token 665 字，一个块 3,990 字，正好一个 URAM（4,096 × 72）。mode1 要的"7 个 i1 各取 4 个连续 r"永远是 7 个整字；mode3 倒出的 8 个连续 p 落在同一切片内的 2 个整字。

| 缓冲 | 份数 | 内容 / 布局 | 实现（int16，E1 / E2） |
|---|---:|---|---|
| X | P | 残差流 x（Q5.12），切片对齐字；像素算完即由下一个像素（FRONT）或块（LOAD）重填，不需要双缓冲 | 1 URAM 各 |
| XN | P | 归一化块，同布局；E2 的 mode1 读带宽翻倍，存两份 | 1 / 2 URAM 各 |
| V | 2 | 一个 job 的 v，同布局；E2 的 CTX 读带宽翻倍，存两份 | 1 / 2 URAM 各 |
| Q | 1 | 6 个 token 平面 × 2,646，SCORES 每平面每拍 w/2 个 | 12 / 24 BRAM36 |
| KS | 1 | k 的顺序流 | 1 URAM |
| t1 | 2（乒乓） | mode1 → mode2 | LUTRAM（E1 ≈7 KB，E2 翻倍） |
| t2 | 2（乒乓） | mode2 → mode3，按 b（E2 再按 a 奇偶）分 bank | 7 / 14 BRAM18 |
| pend | 1 | mode3 一组结果 | 寄存器 6.8 / 13.6 kbit |
| WIN | 1 | 取窗缓冲：7 行 × (7 + P) 列的光谱环，按 (行 h, 列 mod 7) 分 49 个 bank。FRONT 的写 X 趟每拍取 w 个（≤ 24）e = 5p + n − 1 连续的元素，它们的 h·7 + w 两两不同（5k mod 49 在 k < 49 内不重复），落在 w 个不同 bank，无冲突 | 49 BRAM18（每 bank ≤ 3 列 × 272） |
| W_M3 | 1 或 2 库 | 54 bank × 2,592 × wt_t | 14 URAM / 库（int8 版 7） |
| W_M12 | 1 或 2 库 | 98 bank × 48 × wt_t | LUTRAM ≈1.6k LUT / 库 |
| EMB | 1 或 2 库 | int32 Q.24 × 15,876 | 2 URAM / 库 |
| W_HEAD | 1 或 2 库 | int16 × 24 × 2,646，字 = 同一 p 的 4 个类别，6 块并行读 | 6 URAM / 库 |
| exp 表 | 1 | T_HI、T_LO 各 256 × 24 位 | LUTRAM ROM |

URAM 合计（P = 4）：int16 E1 单库 33、双库 55；**int16 E2 单库 39、双库 61（共 64）**；int8 E2 单库约 24、双库约 39。所以 int16 E2 下双库与 P = 4 基本占满 URAM，P 再大只能放弃双库（单库时 P 最多约 12）；int8 版余量大，P 可到 8。BRAM36：int16 E2 约 Q 24 + t2 7 + WIN 25 + FIFO 10 ≈ 66（共 144）。

Q 为什么不放 URAM：SCORES 每拍要 6 个 token 平面各 w/2 个 q，一个 URAM 只有 2 个口。K 为什么要缓冲：倒出 w 元素/拍，SCORES 只做 w/2 元素/拍，差的一半靠 K + V 两个 job 的窗口补回来。

### 4.4 权重驻留与热切换

- 装载：`mode.LOAD_W` 时从 w_ddr 线性读权重包 `weights_engine.bin`（int16 版 480,576 B = 60,072 拍 64 位 AXI，约 0.30 ms @200 MHz；int8 版 336,064 B），按头文件的段布局分发到 EMB、W_HEAD、W_M12、W_M3 各 bank；投影段不要求每投影 8 字节对齐（6,028 不是 8 的倍数，v1.2 遇到过）。M2 编译只装投影段。
- 双库（编译参数 `TT_W_BANKS = 2`）：EMB、W_HEAD、W_M12、W_M3 各两份（int16 版多 22 个 URAM），装到 LOAD_BANK、算用 USE_BANK，两者不同就是"后台装载 + 批边界切换"，对应 PLAN §7 第 5 条。D2 按单库出 IP；D4 按 §4.3 的 URAM 账开双库。寄存器位从第一版就存在，单库编译下 LOAD_BANK/USE_BANK 只允许 0。

### 4.5 调度与批处理 P

投影核串行执行 job；每层的 job 顺序（P = 3 例）：

```
投影核   A.Q A.K A.V | B.Q B.K B.V | C.Q C.K C.V | A.M B.M C.M | 下一层 A.Q ...
         ←6·K 拍→ 每个 job（K = 拍/token：E1 378，E2 189）
侧单元
 SCORES/SOFTMAX(A)  与 A.K、A.V 并行，attn_A 在 A.V 末就绪
 CTX+RES(A)         在 B.Q..B.V 期间 → 写 X_A、stats
 STATS+NORM(A)      紧接其后 → XN_A 在 A.M 前就绪
 RES2(A)            与 A.M 倒出同步 → 写 X_A、stats
 STATS+NORM'(A)     在 B.M、C.M 期间 → XN_A 在下一层 A.Q 前就绪
```

- **流式轮换**：一个 patch 做完第 12 层与 HEAD，它的 X/XN 槽立即由 FRONT（CUBE 模式）或 LOAD 装入下一个像素，其余 P − 1 个 patch 照常占用投影核，所以批边界不停流水、不需要 X 双缓冲。一次调用可给任意 n_patch 个像素（整景巡检每行一次调用，约 300～480 个像素），只在段首装满 P 个槽、段尾排空时有空拍，整行摊下来 < 2%。
- P = 3 起投影核没有空拍（每个 patch 的侧工作都藏在别人的 job 里）；P = 2 时 M 之后的 NORM 窗口勉强；P = 1（单点探查）投影核利用率约 70%，加段首取整窗（49 条光谱）约 7k 拍，E2 下约 0.45 ms @200 MHz。
- P 是编译参数 `TT_P_MAX`，每多一个 patch 多 X、XN 各一份（int16 E2 为 3 个 URAM）；P ≥ 3 后吞吐不再增加，P 只影响 URAM、段首尾空拍和单段延迟。int16 E2 双库下取 P = 4（§4.3）。
- V 只要 2 份：V_A 在 CTX(A) 结束（B.V 期间）后就被 C.V 复用。Q、KS 各 1 份：SCORES(A) 在 A.K + A.V 内读完，B.Q 才开始写。

### 4.6 资源与周期估计（以 Vivado 为准）

DSP（侧单元按 int16 口径估；int8 版侧单元还可再打包，暂不计）：

| 档 | 投影核 | 侧单元（NORM、SCORES、CTX、平方器、STATS、SOFTMAX、HEAD） | 合计 | 占 1,248 |
|---|---:|---:|---:|---:|
| int16 E1（K3 = 7） | 476 | ≈136 | ≈610 | 49% |
| **int16 E2（K3 = 14）** | 952 | ≈200～232 | ≈1,150～1,185 | **92～95%** |
| int8 E1 | 239 | ≈136 | ≈375 | 30% |
| **int8 E2** | 476 | ≈200～232 | ≈680～710 | 55～57% |
| int8 E3（K3 = 21） | ≈740 | ≈300～330 | ≈1,040～1,070 | 83～86% |

其它：URAM 与 BRAM 见 §4.3；LUT 粗估 int16 E1 55k～75k、int16 E2 85k～110k（共 117k）、int8 E2 75k～95k、int8 E3 95k～115k，D2 csynth 后修正。**int16 E2 的 DSP 与 LUT 都接近满额，是本设计最大的实现风险**，退路是同一源码 K3 = 7。

周期（稳态每像素 = 12 层 × 4 投影 × 6 token × 拍/token，另加约 3% 段首尾与调度开销）：

| 档 | 拍/token | 拍/像素 | @100 MHz | @150 | @200 |
|---|---:|---:|---:|---:|---:|
| E0（K3 = 4） | 702 | ≈208k | 2.08 ms | 1.39 | 1.04 |
| E1（K3 = 7） | 378 | ≈112k | 1.12 ms | 0.75 | 0.56 |
| **E2（K3 = 14）** | 189 | ≈56k | 0.56 ms | **0.37** | **0.28** |
| E3（K3 = 21，仅 int8） | 126 | ≈37.5k | 0.38 ms | 0.25 | 0.19 |
| 参考：M1 v1.4 板上 | | 每层 141k + PS | 24.3 ms/像素（7020） | | |

- E2 与 E1 的取舍：E2 @150 MHz（0.37 ms）快于 E1 @200 MHz（0.56 ms）；E2 只能过 100 MHz 时两者相当，按功耗与 LUT 取 E1。
- 整景（估计）：LongKou 22.0 万像素，E2 @200 MHz 约 62 s、E1 @200 约 123 s；HongHu 44.7 万像素约 125 s；HanChuan 36.9 万像素约 103 s。
- 取窗读 DDR：每像素 1,904 B，E2 @200 MHz 下约 7 MB/s，与带宽无关。
- 时钟：HLS 目标 5 ns（200 MHz），Vivado 分 200 / 150 / 100 三档各跑一次实现，哪档时序过就报哪档；E5 的"三档"就是 PL0 时钟三个值，IP 不变。csynth 报告只看趋势。

### 4.7 M2、M3a、M3b 是同一个 IP 的不同模式与编译配置

| | M2（D2） | M3a（D4a） | M3b（D4b） |
|---|---|---|---|
| 模式 | PROJ：PS 逐层调用，算 Q/K/V（或 MLP），q/k/v/stats 写 DDR，注意力在 PS | FULL，块输入：PS embed 后送 x_in，12 层 + 分类头片上 | FULL + CUBE：PL 自取窗，PS 只给行段坐标 |
| 编译 | DB = 16（Q3.12），无注意力、前端、分类头 | DB = 18，全部单元（FRONT 可不编） | DB = 18，全部单元 |
| 数值 | 与 v1.4 逐位相同，黄金向量直接用 | §3 入口 A | §3 入口 B |
| PS | 现有 `tt_net.cpp` 全部保留，只换驱动 `tt_hw_engine.cpp` | 取窗、patch 归一化、embed、批调度 | 装载、行段调度、输出打包与 I/O |
| 预期 | PL 每层每 patch ≈ 12k～24k 拍，PS 注意力+残差每层约 0.5～0.7 ms → **PS 决定吞吐，单核约 6～8 ms/像素**。价值是投影核在板上逐位验过 | PS 前端（单核估计 0.1～0.3 ms/像素，M1 板测 tt_block_app 会给出实测）与 PL 双缓冲；E2 下可能 PS 受限 | 0.28～1.1 ms/像素，PL 决定吞吐 |

M3 编译下 PROJ 模式仍可用（q/k/v 从 Q5.12 饱和到 int16），作为板上逐层调试口；M3b 编译保留块输入（非 CUBE），用于对黄金向量。int8 版（`TT_NUM=8`）沿用 M3b 列：同一套寄存器；PROJ 模式输出 q/k/v 为 int8 值符号扩展进 int16，只作逐层对拍口。

## 5 接口契约（`src/hls/tt_engine_regs.h` 为准，版本 3：v2 + 立方体 bfp，寄存器与参数顺序不变）

### 5.1 顶层函数与寄存器

```
u32 tt_engine(const u64 *x_in, const u64 *cube, u64 *x_out, u64 *q_out, u64 *k_out, u64 *v_out, u64 *stats_out,
              const u64 *w_ddr, u32 cube_w, u32 seg_row, u32 seg_col, u32 n_patch,
              u32 layer_lo, u32 layer_hi, u32 proj_mask, u32 mode, u32 *cycles)
```

参数顺序冻结；偏移由 HLS 生成（`xtt_engine_hw.h`），PS 只用生成的 `XTt_engine_Set_*/Get_*`。各参数语义、mode 位（FULL、LOAD_W、LOAD_BANK、USE_BANK、DUMP、CUBE、OUT[7:6]）、proj_mask 位、错误码见头文件。返回值 [7:0] 错误码，[15:8] 契约版本（= 2），[23:16] FEAT 小数位，[31:24] 片上激活位宽；PS 初始化时先读版本再用。`cycles` 是 IP 自计的 ap_start→ap_done 拍数，板上 PL 时间用它，PS 端到端另计。

AXI：`m_axi` 两个 bundle——FM（x_in、cube、x_out、q/k/v/stats）挂 HP0_FPD，WT（w_ddr）挂 HP1_FPD，先按 C1 平台的 64 位；`s_axilite` CTRL 挂 HPM0_LPD；地址 32 位（缓冲必须在低 4 GB，PS 已有检查）；`ap_ctrl_hs`，interrupt 接 PL_PS_IRQ0。`build_zu5ev.tcl` 只换 IP 名与 `PL_CLK_MHZ`。v2 的输入输出每像素只有几 KB，64 位口够用，不改平台。

### 5.2 DDR 布局

| 区 | 元素 | 每 patch / 像素 | 跨距 | 说明 |
|---|---|---:|---:|---|
| cube | int16 × 272，HWC | 544 B | 行跨距 cube_w × 544 | CUBE 模式；PC 导出的 `cube_i16.bin` 原样装入 |
| x_in | int16 Q3.12 × 15,876，内存序 (p, n) | 31,752 B | 31,808 | 非 CUBE 模式；FULL 是 x_embed，PROJ 是未归一化 x |
| q_out / k_out / v_out | int16 Q3.12 × 15,876 | 31,752 | 31,808 | PROJ 模式；只选 MLP 时写 q_out |
| stats_out | 6 个 64 位字 {inv_q24, mean_q24} | 48 | 64 | PROJ 模式，与 v1.4 相同 |
| x_out CLASS | 32 位 {conf Q0.16, 0, label} | 4 | 4 | 默认；一行 ≤ 481 像素 ≤ 1.9 KB |
| x_out LOGITS | int32 Q.16 × 32 槽 | 128 | 128 | 单点探查 |
| x_out FEAT | int32 × 15,876 | 63,504 | 63,552 | 调试；DUMP 时每层一组，块 (l, i) 在 ((l · n_patch) + i) · 跨距 |
| w_ddr | `weights_engine.bin` | int16 版 480,576 / int8 版 336,064 | | 段布局见头文件 |

所有基址 64 B 对齐（A53 cache 行，也是 8 拍 64 位 AXI 突发的边界）。

### 5.3 PS 侧调用约定

- 装景：SD → DDR 读 `cube_i16.bin` 与 `weights_engine.bin`，各 clean 一次；一次 `LOAD_W`（n_patch = 0）约 0.3 ms，双库编译下可与计算并行，在调用边界翻 USE_BANK。
- 整景巡检 / 区域识别：每行（或框内每行段）一次调用 `FULL | CUBE | OUT(CLASS)`，n_patch = 段长；x_out 两套缓冲，PL 算第 r 行时 PS 打包第 r − 1 行发 UDP、画 DP。单点探查：n_patch = 1、`OUT(LOGITS)`。评测：按标注像素所在行段调用。
- M3a / 调试：非 CUBE 模式，PS 用 `tt_embed` 填 x_in，每次 clean；FEAT + DUMP 逐层对拍。
- 完成后 invalidate 实际使用的输出范围再读。同一时刻一个调用在飞。版本核对、错误码非 0 时打印并停机；`tt_hw:` 行的对齐与 4 GB 检查沿用。

## 6 验证与容差口径

1. PC：`engine_ref.py`（入口 A、入口 B、`--num 8`）对浮点模型（三景回归像素）→ 标签一致率、max/mean\|dlogit\|，写 `report/accuracy_fixed_pc.md`（新增"参考版本"列），前端、注意力、分类头各自的误差单列。验收：一致率 100%（并列像素单列）、max\|dlogit\| ≤ 0.06（09-24 用户定，原 0.05）；int8 版按 §0 第 9 条。
2. 主机 C 参考对 Python：逐位（全整数，只有 token / patch 统计量的 float32 sqrt/除法，IEEE）。
3. HLS csim 对主机 C 参考：逐位；D2 用现有 `sim/golden/n6_real` 回放，D3 注意力与分类头单元用 `n6_engine` 的中间量，D4a 全网（入口 A），D4b 前端 + 全网（入口 B）。
4. cosim：逐位 + 拍数（写进 `sim/m2|m3/`）。
5. 板上：PROJ 模式逐层对黄金向量逐位；FULL + DUMP 逐层逐位；CLASS / LOGITS 对 `engine_ref.py` 的类别、置信度、logits **逐位**（分类头已整数化，不再需要 1e-2 容差）；再跑三景回归像素报一致率与 dlogit。
6. 容差文件 `sim/tolerance.md`（D3）：整数路径全部 0 容差；对浮点模型只报统计量。

## 7 风险与退路

| 风险 | 表现 | 退路 |
|---|---|---|
| int16 E2 的 DSP（≈92～95%）与 LUT 接近满额 | csynth II > 1、Vivado LUT > 90%、布线或时序不过 | 同一源码 K3 = 7（E1）；E2 只过 100 MHz 时也按 §4.6 取舍 |
| mode3 阵列 II = 1 做不到 | csynth 报告 | E0（K3 = 4）；或降时钟档 |
| URAM 访问模式 HLS 推不出（`BIND_STORAGE impl=uram`、双口、lane 使能） | csynth 把 URAM 打成 BRAM 或串行化端口 | 显式 ap_uint<72> 字 + 手写 lane 拼装；或 X/XN/V 改分 bank 的 BRAM |
| URAM 不够（int16 E2 双库 61/64） | Vivado 利用率 | EMB 挪 BRAM（14 块 BRAM36）；或放弃双库（热切换改为停机重载 0.3 ms） |
| FRONT 的 WIN 分 bank、地址置换与 bfp 移位在 HLS 里调不顺 | csim 对不上或 II > 1 | 退到 M3a（PS 前端，接口已在），M3b 顺延 |
| 整数 softmax / patch 归一化 / 分类头精度不够 | `engine_ref.py` 一致率下降或 dlogit > 0.06（立方体整景 k 精度不够已在 09-24 改 bfp 解决） | attn Q0.28、表 512 项；加宽 g、EMB、W_HEAD；寄存器不变 |
| int8 QAT 达不到验收线 | B5 报告 | 退到只权重 int8（PTQ 即可，吞吐同 int16） |
| M2 阶段 PS 成瓶颈显得没进步 | 6～8 ms/像素 | 如实报告；M2 的验收是投影核在板上逐位 + PL 拍数 |
| 32 位 m_axi 地址 | 缓冲落到高 2 GB | 沿用低 4 GB 检查；需要时 HLS 开 addr64（接口不变，驱动多写高 32 位） |
| HLS 2020.2 对 URAM 输出寄存器时序 | 200 MHz 不过 | 150 MHz 档 |

## 8 对 PLAN 的修订（2026-09-23 已改）

- §5.1：整条推理链进 PL（前端、12 层、分类头）；P 为编译参数；注意力整数方案；输出类别 + 置信度。§5.2 取窗与 patch 归一化移入 PL；§5.4 数据流；§14.2 SD 目录加 `cube_i16.bin` 与 `weights_engine.bin`。
- §6：性能目标按本文 §4.6 改；M3 拆 M3a / M3b，M4 int8 版改为必做。
- §7 第 1 条改为全链进 PL；第 6 条改为"并行度档 × 时钟档 × int16 / int8 的效益曲线"。
- §17：D1 完成；D2～D5 按本文 §9 改；B 阶段追加 B5 QAT；E1 的取窗与 patch 归一化只留给 M1 / M2 / M3a 路径。

## 9 下一步入口

- D2（M2）：`src/hls/tt_engine.cpp` PROJ 模式（DB = 16）：投影核按 `TT_K3` 参数化（先 K3 = 7 跑通，同时 csynth K3 = 14 看 DSP / LUT 趋势）、NORM、权重包装载、批调度；csim 回放 `sim/golden/n6_real`；cosim；Vivado 三档；驱动 `tt_hw_engine.cpp` + `tt_net.cpp` 批调用；上板 PROJ 逐层逐位、拍数进 `report/perf_m2.md`。
- D3：`model/engine_ref.py`（入口 A / B、注意力、前端、分类头）与三景回归 → `sim/golden/n6_engine/`；`sim/host/engine_ref.cpp`；`export_scene.py` 出 `cube_i16.bin` 与 `weights_engine.bin`；注意力与分类头单元 HLS 单独 csim/cosim；`sim/tolerance.md`。
- D4a（M3a）：FULL 模式（块输入）、DUMP、RES2、HEAD、OUT、调度；Vivado；上板；`report/perf_m3.md`。
- D4b（M3b）：FRONT（WIN、patch 统计、NORM + EMBED 趟）、CUBE 模式、行段调度；csim 对入口 B；Vivado；上板整景巡检。
- B5（PC，可与 D2 并行）：`train_scene.py --qat`（三处 Q3.4 假量化 + 权重逐矩阵 2 幂假量化，STE，从 float checkpoint 续训 50～100 轮）；`export_scene.py` 出 int8 权重包；`fixed_regression.py` 报 QAT 模型的一致率与 OA，过验收线才进 D5。
- D5（int8 版）：`TT_NUM=8` 编译：打包乘法器与分段累加、8 位存储布局、指数表装载与移位；csim/cosim 对 `engine_ref.py --num 8`；Vivado 三档；上板；与 int16 版并排进 `report/perf_m3.md`。
