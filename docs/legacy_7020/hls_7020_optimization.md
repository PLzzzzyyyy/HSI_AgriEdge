# Zynq-7020 投影 IP 优化记录

更新：2026-09-19。目标是继续降低现有 7020 的块推理时间。本轮把三项 PL 改动合并成候选（64 位激活接口、32 位因子接口、token 级 DATAFLOW），再加一个 mode3 双位置的 dual 变体；两者 csim / RTL cosim 逐位通过、Vivado 布线后时序通过、XSCT 建平台通过，候选 XSA 已生成，**尚未上板**。定点格式、舍入位置、DDR 布局和 PS 调用接口全部不变。

## 版本一览

| 版本 | 变体 / 位置 | 状态 |
|---|---|---|
| v1.0 已部署 | `hls/ip_export`，平台 `vitis/tsam` → `vivado/tt_soc_v1_wns-0.019.xsa` | 板上运行中的 IP（乘法位宽问题版，WNS −0.019 ns；修复版 `vivado/tt_soc.xsa` 从未换进平台） |
| v1.1 | `hls/optimization_build/mode1_banked/`（上一轮，只修 t1 分区） | cosim 通过，未上板，被 v1.2 取代 |
| v1.2 候选 | `hls/optimization_build/fm64_wt32_df/`，`vivado/tt_soc_fm64_wt32_df.xsa` | csim + cosim 逐位通过，Vivado 时序通过，XSCT 建平台通过，等上板 |
| **v1.3 dual 候选** | `hls/optimization_build/fm64_wt32_df_dual/`，`vivado/tt_soc_fm64_wt32_df_dual.xsa` | **2026-09-19 已上板**：单 patch 38.8 → PS 轮 3 后 35.3 ms，流水 25.9 ms/像素，4096/4096 |
| **v1.4 norm 候选** | `hls/optimization_build/fm64_wt32_df_norm/`，`vivado/tt_soc_fm64_wt32_df_norm.xsa` | **2026-09-20 已上板（终态）**：单 patch 37.5 ms，流水 24.3 ms/像素，max\|dlogit\| 1.1e-03；平台需从 XSA 重新新建 |

## v1.4：token 归一化搬进 PL（`TT_NORM_IN`，2026-09-20）

动机：dual 上板后流水吞吐完全由 PS 决定（25.9 ms/像素，PL 9.9 ms 藏在后面），PS 里 normalize+quant 占 8.35 ms。用户要求"尽量减少数据交互"，所以层间激活改为 int16 Q3.12 存 DDR，IP 输入口不变。

- **接口**：`in` 仍是 int16 [D*N]，但是未归一化的 x；新增 `stats` 输出（m_axi FM 束，每 token 一个 64 位字 `{inv_q24, mean_q24}`，AXI-Lite 寄存器 0x30）；驱动多一个 `XTucker_proj_Set_stats`，其余寄存器偏移不变。
- **算法**（`vitis/src/tt_ref_int.h`，HLS / 主机仿真 / tb 共用）：S1=Σx、Sxx=Σx² 整数精确（搬运时 4 车道 × 5 槽同时累加，4 个 DSP）；var_num = D·Sxx − S1²；mean_q24 = (S1<<12)/D；inv = 10835968.0f / sqrtf((float)var_num)（float32 标量，每 token 一次，clamp ≤127）；q = sat16(((x<<12 − mean_q24)·inv_q24 + 2^35) >> 36) 原地写片上 xb。与 PS float32 归一化只差 ±1 LSB（0.07%）。
- **PS**：`TTWork = {x(int16), out_q, out_k, out_v, stats(int32[32])}`；embed 直接量化；ctx / mlp 残差用 stats 复原 xn 后原地写回 int16 x；normalize/xn/in_q 全部消失。主机 4096 像素：4096/4096 vs PC 定点，OA 98.8123%，max|dlogit| 0.0086（阈值 0.01，余量 14%）。
- **cosim**（N=6）：QKV 96940 拍、MLP 44087 拍（各比 v1.2 多约 13.6k 拍归一化）→ 12 层 PL 16.9 ms。normalize_block 是 1890×7 拍逐元素（奇偶两组同拍），可改 4 车道再省约 2 ms/patch。
- **Vivado**：WNS +0.203 ns，LUT 33102 (62.2%)，FF 28471，BRAM 53 tile，DSP 180 (81.8%)。dual 底子 + norm 估 DSP 235，放不下。
- **预期**：PS 侧约 16～17 ms/像素，PL 每层 1.41 ms 与 PS 每层约 1.35 ms 接近持平；流水吞吐预期 16～18 ms/像素，可能第一次由 PL 决定。
- **板上（2026-09-20，三次只 Build 应用）**：首次 41.66 / 27.59（PS 残差内核慢），PS 轮 5b 后 **37.49 ms / 24.30 ms/像素**。PL 每层 1.132 + 0.542 = 1.674 ms（含驱动）与 cosim 一致。PS 侧 20.9、PL 16.9，重叠不完全，实测 24.3。见 [CPU_PL_BENCHMARK](CPU_PL_BENCHMARK.md)。
- **不兼容**：新 PS 源码只能配 v1.4 平台；退回 dual XSA 时源码也要退回 `vitis/benchmark_build/before_round4_sync_20260920_113102/`。换 IP 版本时旧平台用 Update Hardware Specification 会读不出来（pitfalls 09-20），删掉从 XSA 新建。

## 版本一览（v1.3 为止）

板上基线（2026-09-16 用户实测，[日志](results/board_uart_20260916_block.txt)）：块流水网络吞吐 37.307 ms/像素，含取窗 37.696 ms/像素，4096 个分类与 PC 定点参考全部一致。其中 PL 侧约 31 ms（cosim 26.1 ms + 24 次驱动调用的 cache 维护），PS 侧约 25.9 ms。

## 脚本

- `hls/run_7020_opt.tcl`：`TT_HLS_VARIANT`（变体表见脚本）+ `TT_HLS_STAGE=synth|cosim|export`。synth 阶段先把 `hls/src`、`hls/tb`、`model/data/golden` 快照到 `<variant>/snapshot/`，后续阶段只用快照，跑综合期间改仓库源码不影响结果。日志请用 bash 重定向（PowerShell `*>` 会写成 UTF-16）。
- `vivado/build_tt_soc_opt.tcl`：`TT_VARIANT` 选变体，读导出 IP 的版本号，独立工程 `vivado/tt_soc_<variant>/`，报告 `vivado/tt_soc_<variant>_{utilization,timing}.rpt`，**时序不过不导 XSA**。HP0/HP1 显式 64 位。导出后自动调用 `tools/fix_xsa_driver_makefile.py` 把 XSA 内驱动 Makefile 的 `#echo` 行删掉（XSA 就是 zip，manifest 里没有校验和；位流不动）。
- 变体全部通过 `hls/src/tucker_proj.cpp` 里的宏开关：`TT_FM64`、`TT_WT32`、`TT_TOKEN_DF`、`TT_MODE3_DUAL`；不定义任何宏就是 v1.0 的算法与接口（`hls/tb/tb_tucker_proj.cpp` 仍可对拍）。

## 本轮改动（v1.2 = FM64 + WT32 + TOKEN_DF）

1. **激活块 64 位 AXI（`TT_FM64`）**：`in/out_*` 由 16 位元素改为 `ap_uint<64>`，一拍 4 个 int16。加载时 4 个 lane 按 token 奇偶写进两组片上缓冲（`xb[n&1][i1][…]`，N 为偶数所以组号是编译期常量）；输出缓冲 `ob` 改成 DDR 输出块的原样线性镜像、按下标 mod 4 分 4 路，store 每拍从 4 路各取一个拼成一拍。load 15876 → 3969 拍，store 同样。要求 n_tok ∈ {6, 10}，否则 IP 直接返回。
2. **因子矩阵 32 位 AXI（`TT_WT32`）**：每投影 3014 个 int16 = 1507 个 32 位字，起址 4 字节对齐（权重数组 32 字节对齐，跨距 6028 = 4×1507）。M3 的一个字永远落在同一行，m3 第二维按奇偶分两路一拍写两个。3014 → 1510 拍。没有做 64 位：6028 不是 8 的倍数。
3. **token 级 DATAFLOW（`TT_TOKEN_DF`）**：`for n: mode1; mode2; mode3` 的循环体加 `DATAFLOW`，t1/t2 变 ping-pong，第 n 个 token 的 mode3（2646 拍）与第 n+1 个的 mode1+mode2（778 拍）重叠；每 token 3438 → 2712 拍。t1 的 49 个小块显式 `BIND_STORAGE impl=lutram`，否则 ping-pong 后各占一块 BRAM。
4. **mode3 写出方式**：一个位置的 54 个结果先进 `pend[]` 寄存器，接下来 54 拍逐拍写到 `ob[(ab*54+c)*N + n]`（地址每拍 +N，全程递增），代替原来 54 路并行写。这样 ob 是 16 位宽单端口，HLS 估计 28 块 BRAM18K；之前 32 位打包 + 双端口 + 局部写的方案是 108 块，而且 LUT 爆炸（见 pitfalls 2026-09-17）。
5. 其他：所有片上地址改为跑动计数器（无变量乘除，DSP 不再被地址运算占用）；`m1/m2` 用 `complete dim=0`；`mode1_banked` ��轮的 t1 双维分区保留。

`TT_MODE3_DUAL`（v1.3）：mode3 一拍算两个空间位置，108 个乘法器；两路写地址 wl 与 wl+54N 需要 `DEPENDENCE inter false` 才能 II=1。

## 验证结果

Vitis HLS 2020.2，`xc7z020clg400-2`，100 MHz。测试平台 `hls/tb/tb_tucker_fm64.cpp`：N=6 黄金向量（Q/K/V/MLP 共 63504 个输出）+ N=10 全值域置换用例（跨 64 位边界、最后一个奇数位置、饱和）+ 输入/未用输出的哨兵检查。

| 检查 | v1.0 部署 | v1.1 | **v1.2** | v1.3 dual |
|---|---:|---:|---:|---:|
| csim | 逐位 | 逐位 | 逐位 | 逐位 |
| RTL cosim | 逐位 | 逐位 | **逐位** | 逐位 |
| cosim：QKV 调用（N=6） | 155335 拍 | 134875 | **83348** | 60040 |
| cosim：MLP 调用（N=6） | 62435 | 55610 | **30500** | 22730 |
| cosim：QKV 调用（N=10） | – | – | 135740 | 96890 |
| 12 层 PL 合计（N=6） | 26.13 ms | 22.86 ms | **13.66 ms** | 9.93 ms |
| HLS 估计 BRAM18K / DSP / LUT | 109 / 156 / 29k | 102 / 156 / 31k | 108 / 154 / 41k | 115 / 209 / 52k |

cosim 周期含 AXI 读写的真实延迟，不含板上 DDR 争用和驱动 cache 维护。

## Vivado 实现（以此为准）

| 指标 | v1.0 部署 | v1.2 候选 | **v1.3 dual 候选** |
|---|---:|---:|---:|
| WNS | +0.374 ns | +0.296 ns | **+0.363 ns** |
| LUT | 13012 (24.5%) | 28605 (53.8%) | 35027 (65.8%) |
| FF | 13804 (13.0%) | 23363 (22.0%) | 29351 (27.6%) |
| BRAM tile | 85 (60.7%) | 53 (37.9%) | 56.5 (40.4%) |
| DSP | 160 (72.7%) | 156 (70.9%) | **211 (95.9%)** |
| XSA | `tt_soc_v1_wns-0.019.xsa` | `vivado/tt_soc_fm64_wt32_df.xsa` | **`vivado/tt_soc_fm64_wt32_df_dual.xsa`** |

两个候选都通过 100 MHz 时序，DSP 都没有超；dual 的最差路径是 1 级 LUT + 9.06 ns 布线（DSP 96% 带来的布线拥塞），仍有 0.36 ns 余量。dual 之后这块板的 DSP 基本用满，PL 再想提速只能改算法结构（见"后续方向"）或换板。

两个 XSA 都已用 XSCT 在临时工作区实际 `platform create + generate` 过（`tools/check_xsa_platform.tcl`，日志 `vitis/benchmark_build/xsa_check_*.log`）：Windows make 直接通过，BSP 里生成的 `xtucker_proj.h` 驱动 API 与当前平台逐字相同；同步后的 `vitis/tsamapp/src` 用新 BSP 交叉编译链接通过（`vitis/benchmark_build/app_vs_v12_bsp/`）。

新 IP 的 AXI-Lite 寄存器映射与 v1.0 逐字相同（已 diff `xtucker_proj_hw.h`），`tt_hw_xil.cpp` 不需要改寄存器代码；只加了一次性的缓冲对齐检查（FM 8 字节、WT 4 字节）。

## 板上预期

| | PL 12 层（cosim） | 单 patch 延迟（估） | 块流水吞吐（估） |
|---|---:|---:|---:|
| 现状 v1.0 | 26.1 ms（板上含驱动约 31） | 57.6 ms 实测 | 37.3 ms/像素 实测 |
| v1.2 | 13.7 ms | 约 42 ms | 约 22–26 ms/像素 |
| v1.3 dual | 9.9 ms | 约 38 ms | 约 20–24 ms/像素 |

块流水吞吐由 PS 侧（融合 normalize+quant 后约 20–24 ms，含每层驱动 cache 维护）决定，两个候选在流水模式下差别可能只有 2–3 ms；单 patch 延迟差约 4 ms。以上都是估算，以串口 5/4 的实测为准。

## Vitis 操作（用户）

推荐顺序：先上 **dual**（`vivado/tt_soc_fm64_wt32_df_dual.xsa`），异常再退到 `vivado/tt_soc_fm64_wt32_df.xsa`，再退到 `vivado/tt_soc.xsa`（修复版 v1.0）。两个候选的操作完全相同：

1. 平台 `tsam` → **Update Hardware Specification** → 选候选 XSA。
2. 候选 XSA 里自带的 HLS 驱动 Makefile 已经用 `tools/fix_xsa_driver_makefile.py` 修过（`#echo` 行已删，位流字节不变，原件 `*.xsa.orig`），XSCT 实测 generate 直接通过，**正常不用再修 Makefile**。如果 Build platform 仍报 `CreateProcess(NULL, #echo ...)`，再跑老办法：
   `python tools/fix_hls_driver_makefile.py vitis/tsam`
3. Build platform → Build `tsamapp`（源码已同步：`tt_net.cpp/.h` 融合量化、`tt_hw_xil.cpp` 对齐检查、`main_benchmark.cpp` 表头）→ Debug。确认 Debug 配置下载的是新平台的 bitstream，只 Build 应用不会更新 PL。
4. 串口发 `5`：两个不同 patch 的顺序/流水 logits 要逐位一致，记下两种 ms/像素。
5. 串口发 `4`：4096/4096 完成、标签与 PC 全部一致，记网络/取窗/墙钟时间，再按当次打印的地址导出 BMP。
6. 串口发 `1` 也值得看一眼：单 patch 的分段表里 PL qkv / PL mlp 两栏会直接给出新 IP 的板上时间。

## 后续方向

- PS 侧已成为流水瓶颈：驱动每次调用 flush 输入 + 3 个输出块、完成后 invalidate，24 次/patch 约 5 ms，可按"CPU 是否写过输出缓冲"跳过输出 flush；scores/ctx 内核受 L1 容量限制（63 KB 块）。
- PL 侧再往下：dual（若时序通过）约 9.9 ms；再之后是跨投影 dataflow（t2 保存全部 token、mode3 按位置外层循环，输出缓冲缩到 54×N 双缓冲，Q 的 mode3 与 K 的 mode1/2 重叠），估计 5–6 ms，需要重排 t2/ob 存储。
