# 整网 CPU 计时与板上 PS / PL 串口切换

更新：2026-09-16。第1至5节保留2026-09-15 double版本基准；当前float32+NEON代码对参考的阈值为 `TT_LOGIT_TOL=1e-2`，不要把历史阈值/耗时当作当前版本。

2026-09-16双patch流水的[板上日志](results/board_uart_20260916_pair_check.txt)：两个不同patch重复10次，顺序/流水logits逐位一致，顺序57.692 ms/pixel，流水37.296 ms/pixel，吞吐提升1.547倍。此比较是同板PS+PL顺序与流水，**不是纯PS与PL的加速比**；不含取窗/验证/串口，完整4096块仍待实测。块模式和BMP导出见 [BLOCK_INFERENCE.md](BLOCK_INFERENCE.md)。

电脑主机测试已实测；用户已将串口切换版集成到 `vitis/tsamapp/src` 并完成板上运行。新增逐层/分段计时也已在板上输出。两者都从已经预处理好的 patch 开始，完整执行嵌入、12 层网络和分类头。

## 1. 电脑 CPU 整网时间

入口是 `vitis/host_test.cpp`，执行 `tt_net.cpp + tt_hw_sim.cpp`。`std::chrono::steady_clock` 只包围 `tt_forward()`，没有把读文件、编译、逐层对照、打印或图像预处理算进去。先逐层检查，再预热一次完整前向，最后计时 10 次，每次都核对最终 logits。

本次最终单独运行的记录：

| 项目 | 结果 |
|---|---|
| 模型 / 输入 | unoverlapping，N=6，像素 `(20,20)`，batch=1 |
| 运行环境 | 本机 Windows x64，MinGW GCC 15.2.0，`-O2 -std=c++11`，单线程 |
| 数值路径 | double 的归一化、注意力等 + 整数定点 Tucker 投影 |
| 平均完整前向 | **17.730 ms/patch** |
| 中位数 | 17.704 ms |
| 最小 / 最大 | 16.679 / 18.853 ms |
| 12 层最大输出误差 | `3.997e-15` |
| 最终 logits 最大误差 | `1.776e-14`，10 次均 PASS |
| 预测 | argmax=0，对应标签 1，玉米，与当前 gt=1 一致 |

电脑 CPU 原始日志：[vitis/host_test.log](../vitis/host_test.log)。后续运行若覆盖日志，文中的数字仍指这次测量。电脑 CPU 的速度随负载和频率变化，不能由这个数推算 Cortex-A9 的时间，也不能直接用它除以板上时间宣称 PL 加速比。

在项目根目录重新编译、计时并保存：

```powershell
D:\mingw64\bin\g++ -O2 -std=c++11 -o vitis\host_test.exe vitis\host_test.cpp vitis\src\tt_net.cpp vitis\src\tt_hw_sim.cpp
vitis\host_test.exe | Tee-Object -FilePath vitis\host_test.log
```

## 1.1 板上串口实测结果

用户于 2026-09-15 提供的同板串口记录见 [原始输出](results/board_uart_20260915_pixel20_20.txt)。使用同一个 `(20,20)` patch 和串口切换程序，先运行 PS+PL、返回菜单，再运行纯 PS；两组各 10 次正式前向，均 PASS。该记录没有命令 `3` 的 `COMPARE PASS` 行，下述加速比由两组均值计算。

| 模式 | 平均整网时间 | 中位数 | 12 层阶段合计 | 预测对照 |
|---|---:|---:|---:|---|
| PS+PL | **140.102 ms** | 140.095 ms | 139.068 ms | PASS，最大误差 `1.776e-14` |
| 纯 PS | **1206.110 ms** | 1206.119 ms | 1205.147 ms | PASS，最大误差 `1.776e-14` |

由同板数据计算：

```text
整网加速比 = 1206.110 / 140.102 = 8.609×
总时间下降 = 1 - 140.102 / 1206.110 = 88.38%
```

纯 PS 的每层约 `100.4 ms`，12 层约 `1205.1 ms`；PS+PL 的每层约 `11.6 ms`，12 层约 `139.1 ms`。所以“每层 100 ms”和“整网 140 ms”属于两种不同后端：前者是纯 PS，后者是 PL 加速。

PS+PL 的 12 层累计阶段中，注意力 `38.912 ms`、归一化 `18.570 ms`、量化 `24.396 ms`、QKV PL `21.880 ms`、MLP PL `9.204 ms`。纯 PS 中 QKV 软件投影 `822.727 ms`、MLP 软件投影 `274.286 ms`，两者合计 `1097.013 ms`，是纯 PS 的主要耗时来源。

## 2. 板上使用一个程序切换两种执行方式

新入口：[vitis/main_benchmark.cpp](../vitis/main_benchmark.cpp)。串口发送 **ASCII 文本**：

| 发送 | 操作 |
|---|---|
| `1` | PL 加速整网：PS 处理归一化、注意力等，PL 计算 Tucker 投影 |
| `2` | 纯 PS 整网：全部由 ARM CPU 计算，Tucker 使用 `tt_hw_sim.cpp` 的整数实现 |
| `3` | 先纯 PS、再 PS+PL，各自验证，打印两者时间、输出差和加速比 |

每种方式先预热一次，再计时 10 次，最后额外运行一次带详细计时的完整前向。额外一次不计入前 10 次的平均时间和加速比。运行结束会返回菜单，可反复发送命令。串口工具沿用原有端口和 115200、8N1 设置，关闭“HEX 发送”。可把串口助手的三个自定义发送按钮设置成文本 `1`、`2`、`3`。回车、换行会被忽略；等待本组结束后再发下一个命令。

程序复用同一个 `TTNet`、patch、权重、工作缓冲和 `tt_forward()`；只在完整前向之间切换投影后端：

```text
同一份 tt_net.cpp，完整 12 层
       ↓ tt_hw_proj()
tt_hw_switch.cpp 根据所选模式分派
       ├─ 纯 PS：tt_ps_proj()，ARM 整数运算
       └─ PS+PL：tt_pl_proj()，驱动真实 HLS IP
```

纯 PS 模式不初始化或访问 PL 寄存器。切到 PL 模式时首次初始化驱动。PL 前向前会 flush 输出缓冲，防止上一轮纯 PS 留下的脏 cache line 回写旧结果；PL 完成后再 invalidate，CPU 才读取硬件新结果。

两种方式在正式 10 次基准中都启用 CPU cache、关闭分段计时回调，计时范围相同。PL 模式的寄存器操作、cache 维护和等待硬件完成都计入整网时间。

额外诊断前向开启 `tt_clock=board_clock`，开始前 `tt_profile_reset()` 清零，结束后关闭回调并打印两张表：

- `segment (12 layers)`：归一化、量化、QKV、反量化、注意力、MLP、残差的 12 层累计时间和占完整前向比例。
- `layer / total ms / normalize / quant / qkv / dequant / attention / mlp / residual`：第 0～11 层各自的总时间与各阶段时间，全部以 ms 显示。

`normalize` 和 `quant` 每层各含两次调用；`dequant` 合计 Q/K/V/MLP 四个输出；`residual` 含两次残差。纯 PS 模式的阶段名显示 `PS software qkv/mlp`，PL 模式显示 `PL qkv/mlp`。`embed/head/overhead` 是本次诊断完整前向减去 12 层分段合计，包含嵌入、分类头和未归入阶段的计时/调度开销。诊断表的分母是该次 `Profile forward`，不与前 10 次均值混用。

## 3. 已构建的 ELF 与使用方法

串口切换版程序在：

```text
D:\TT_HSI_FPGA\vitis\benchmark_build\tt_bench_switch.elf
```

本次程序内置当前 `vitis/src/tt_data.c/.h`，即 `(20,20)` 的 patch 和参考 logits。

在 Vitis 调试/运行配置中，把应用 ELF 指向上述文件，沿用现有 Zynq 初始化及匹配 `tucker_proj` 的 bitstream，然后下载并运行。串口出现 `TT serial benchmark` 和 `[1] ... [2] ... [3] ...` 菜单后发送命令即可。PL 模式要求已有正确 bitstream；本次没有修改 HLS 算子或重新构建硬件。

默认构建复用 `vitis/tsam` 导出的 standalone BSP 和 `vitis/tsamapp/src/lscript.ld`。构建输出：

| 文件 | 内容 |
|---|---|
| `vitis/benchmark_build/tt_bench_switch.elf` | ARM 可执行程序，内含两种后端和串口菜单 |
| `vitis/benchmark_build/tt_bench_switch.map` | 链接地址及内存使用 |
| `vitis/benchmark_build/build.log` | 编译和链接命令、诊断信息 |
| `vitis/benchmark_build/build_manifest.json` | 编译器、选项、输入数据标识、源文件与 ELF 哈希 |
| `vitis/benchmark_build/host_switch_test.log` | 主机上的切换回归日志，PL 用桩替代 |

从项目根目录重新构建：

```powershell
D:\pytorch\python.exe tools\build_board_benchmarks.py
```

要减少每组选定后的正式计时次数，例如改为 3 次：

```powershell
D:\pytorch\python.exe tools\build_board_benchmarks.py --runs 3
```

若换像素，先执行 `export_golden.py --pixel 行 列` 和 `export_c_arrays.py`，再执行上述构建脚本并下载新 ELF。构建脚本不修改现有 `tsamapp` 应用源码或平台。

## 4. 如果在现有 Vitis GUI 应用里编译

当前 `vitis/tsamapp/src/main_benchmark.cpp`、`tt_net.cpp`、`tt_net.h` 已直接更新为带逐层统计的版本，应用现有 `-DTT_HW_RUNTIME_SWITCH -std=c++11` 保持即可。选中 `tsamapp` 刷新（F5）、Build，再使用原来的 Run As。已检查 `vitis/tsamapp/Debug/tsamapp.elf` 包含新计时函数和打印表格，不需要改选独立 ELF。

以后从外层源码重新集成时，步骤为：

1. 用 `vitis/main_benchmark.cpp` 替换应用原 `main.cpp` 的内容，确保只编译一个 `main()`。
2. 同步 `vitis/src/` 的 `tt_net.cpp/.h`、`tt_hw.h`、`tt_data.c/.h`、`tt_hw_sim.cpp`、`tt_hw_xil.cpp`、`tt_hw_switch.cpp/.h`。不要加入 `host_test.cpp` 或 `test_backend_switch.cpp`。
3. 在应用 C++ 编译器的预处理器定义中添加 `TT_HW_RUNTIME_SWITCH`，对所有上述 C++ 文件生效；两种后端必须同时链接。
4. 使用 `-O2`、C++11，以及现有 `-mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard`；链接 `libm` 和现有 BSP。
5. 重新编译应用并下载。无需修改 Vivado block design 或重新综合 HLS。

未定义 `TT_HW_RUNTIME_SWITCH` 时，原来单独选择 `tt_hw_sim.cpp` 或 `tt_hw_xil.cpp` 的构建方式仍可使用。原 `vitis/main.cpp` 保留原有串口输出形式。

## 5. 如何判断结果和加速比

每次输出包含 `forward run ... ms`、`argmax` 和 PASS/FAIL，最后汇总 mean、median、min、max。PASS 要求所有 logits 为有限数，预测下标与参考相同，最大绝对误差小于 `1e-4`。

命令 `3` 的加速比公式是：

```text
同一块板、同一个 patch 的整网加速比
    = 纯 PS 的平均完整前向时间 / PS+PL 的平均完整前向时间
```

仅当两组结果都通过、两组最终 logits 也相符、计时有效时才打印加速比。大于 1 表示该实现使用 PL 后更快；小于 1 表示此比较条件下更慢。这里对比的是现有标量整数参考实现，不代表经过 NEON 等优化的最快 ARM 基线。

**已验证**：电脑逐层/最终对照 PASS；PS→PL→PS→PL 分派与失败初始化回归 PASS（PL 使用软件桩）；实际 Cortex-A9 编译器 GCC 9.2.0 编译和链接成功，ELF 包含软件投影、硬件驱动、串口接收和启动入口。

**新增验证**：开启/关闭详细计时都与 golden 一致；各层阶段时间合计与全局阶段合计相符，重置不残留上一轮数据。用户实际 `tsamapp` 已构建并上板运行，串口日志确认 PL、纯 PS 两组均 PASS；两组整网均值之比为 `8.609×`。命令 `3` 的自动比较输出未在此次日志中出现。

**测量边界**：上述加速比只针对当前 `(20,20)` patch、N=6、10 次正式前向和当前 bitstream；纯 PS 后端是标量整数实现，不是经过 NEON 优化的 ARM 极限基线。

## 2026-09-19 dual IP（v1.3）板上结果与 PS 软件轮 3

新 PL 投影 IP（`vivado/tt_soc_fm64_wt32_df_dual.xsa`，见 [HLS_7020_OPTIMIZATION](HLS_7020_OPTIMIZATION.md)）上板，用户实测：

| 口径 | 旧 IP（09-16） | dual IP（09-19） |
|---|---:|---:|
| 串口 1，profile 单 patch | 57.637 ms | **38.807 ms**（max\|dlogit\| 4.226e-04 不变） |
| 串口 5，顺序 ms/像素 | 57.692 | **38.903** |
| 串口 5，双 patch 流水 ms/像素 | 37.296 | **29.055**（ratio 1.339×） |

分段（12 层合计，ms）：norm+quant 9.839 / PL qkv 10.488 / attn scores 5.685 / attn ctx+resid 5.471 / PL mlp 4.453 / mlp resid 2.070。每层 PL qkv 0.874 = cosim 0.600 + 驱动 cache 维护 0.274。构成：PS 内核 23.1（59%）、PL 计算 9.9（26%）、驱动 cache 维护 5.0（13%）。流水吞吐 = max(PS, PL) = PS，所以流水收益从 1.55× 缩到 1.34×，后续只压 PS。原始记录 `results/board_uart_20260919_dual_profile.txt`。

PS 软件轮 3（只需重新 Build 应用）：驱动不再逐次 flush 权重和输出缓冲（输入仍每次 flush，输出仍每次 invalidate；契约见 `tt_hw_xil.cpp` 文件头），估 −2 ms；scores / ctx / mlp 残差 / normalize 内核加 `pld` 预取（q/k/v/mlp 是 PL 刚写 DDR 且已 invalidate 的数据，每行都在等 DDR），收益待测。主机回归全部 PASS，交叉编译 `vitis/benchmark_build/ps_round3/`。

串口 4 整块（dual IP，09-19）：4096/4096 与 PC 一致、OA 98.8123% 不变；Network only **29.068 ms/pixel，119.063 s**（旧 IP 37.307 / 152.810），含取窗 29.459，墙钟 120.668 s。

### PS 软件轮 3 板上结果（09-19，只重新 Build 应用，同一 dual bitstream）

| 口径 | dual IP + PS 轮 2 | dual IP + PS 轮 3 |
|---|---:|---:|
| 串口 1，profile 单 patch | 38.807 ms | **35.334 ms**（max\|dlogit\| 4.226e-04 不变） |
| 串口 5，顺序 ms/像素 | 38.903 | **35.401** |
| 串口 5，双 patch 流水 ms/像素 | 29.055 | **25.940**（ratio 1.365×） |

分段（12 层合计，ms）：norm+quant 8.352 / PL qkv 9.261 / attn scores 5.507 / attn ctx+resid 5.438 / PL mlp 4.042 / mlp resid 1.935；embed/head 0.799。每层 PL qkv 0.772 = cosim 0.600 + 驱动 0.172（原 0.274），PL mlp 0.337 = 0.227 + 0.110（原 0.144）。收益：驱动少 flush −1.64 ms；`pld` 预取 −1.83 ms，其中 normalize −1.49（x 是 CPU 写过、还在 L2 的数据），scores −0.18、ctx −0.03（q/k/v 是 PL 写进 DDR 的数据，预取几乎无效）。构成：PS 内核 21.2、驱动 cache 3.4、PL 计算 9.9、其它 0.8；PS 侧 25.4 ≈ 流水 25.94，吞吐仍由 PS 决定。原始记录 `results/board_uart_20260919_ps_round3.txt`（10 次正式均值与串口 4 未提供）。

## 2026-09-20 IP v1.4（归一化进 PL，int16 层间激活）+ PS 轮 5：终态 24.3 ms/像素

动机：轮 3 后流水吞吐完全由 PS 决定，PS 里 normalize+quant 占 8.35 ms；用户要求"尽量减少数据交互"。主机实验（`tools/exp_norm_fixed.py`，4096 像素）证明层间激活可以用 int16 Q3.12 存 DDR（|x| 最大 5.82，0 饱和，标签 4096/4096，max|dlogit| 0.0086）。于是 IP v1.4（`fm64_wt32_df_norm`）在片上做 token 归一化，`in` 口仍是 int16，多一个 `stats` 输出（每 token mean_q24 / inv_q24），PS 残差用 stats 复原归一化值后原地写回 int16 x。IP 细节见 [HLS_7020_OPTIMIZATION](HLS_7020_OPTIMIZATION.md)。

同一 v1.4 bitstream 上三次只 Build 应用的板上结果（用户实测，记录 `results/board_uart_20260920_norm_v14.txt`、`results/board_uart_20260920_ps_round5.txt`）：

| 口径 | 轮 3（v1.3 dual） | v1.4 首次 | v1.4 + 轮 5 | **v1.4 + 轮 5b（终态）** |
|---|---:|---:|---:|---:|
| 串口 1，10 次均值单 patch | 35.334 ms | 41.662 | 41.228 | **37.486 ms** |
| max\|dlogit\| vs PC 定点 | 4.226e-04 | 8.049e-04 | 9.170e-04 | 1.149e-03（阈值 0.01） |
| 串口 5，顺序 ms/像素 | 35.401 | 41.675 | 41.347 | **37.495** |
| 串口 5，双 patch 流水 ms/像素 | 25.940 | 27.593 | 27.303 | **24.304**（ratio 1.543×） |

终态分段（12 层合计，ms）：PL norm+qkv 13.585 / attn scores 5.503 / attn ctx+resid 6.447 / PL norm+mlp 6.501 / mlp resid 4.649 / embed+head 0.809。每层 PL qkv 1.132 = cosim 0.969 + 驱动 0.163；PL mlp 0.542 = 0.441 + 0.101。

三次结果说明了什么：

- v1.4 首次：PL 段与 cosim 一致（归一化每 patch +7.1 ms，单 patch 模式全暴露），但 PS 残差内核变慢 7.5 ms，把省下的 8.35 ms 吃光。
- 轮 5（指令减半）无效、clean-only 驱动无效：残差内核的时间 = 最长 NEON 依赖链 × 约 6 拍（A9 顺序发射，GCC 不交错独立链），与指令数、与 x 是否在 cache 无关。
- 轮 5b（6 条链按阶段手工交错 + 魔数量化把链从 8 缩到 4）：ctx 0.732 → 0.537 ms/层，mlp 残差 0.469 → 0.387，剩余部分是 PL 写进 DDR 的 v/mlp 每层 992 行 miss。
- 终态构成：PS 侧每 patch ≈ 内核 16.6 + 驱动 3.5 + embed/head 0.8 = 20.9，PL 16.9，两边接近持平后双 patch 交替调度的重叠效率下降，实测 24.3。**从这里起 PL 时间也直接影响吞吐。**

累计（09-16 → 09-20）：单 patch 57.6 → 37.5 ms（−35%），流水 37.3 → 24.3 ms/像素（−35%），4096 像素标签与 PC 定点一致率始终 100%，OA 98.81%。

决定到此收口。再往下的三条路（`.claude/progress.md` 09-20 条目有预期与代价）都要换平台且收益递减：PL 读时归一化（流水约 21～22）、ACP 让 PL 输出留在 L2（约 15～17，成败需实验）、注意力进 PL / 全 PL（约 12～14，DSP 已 180/220）。
