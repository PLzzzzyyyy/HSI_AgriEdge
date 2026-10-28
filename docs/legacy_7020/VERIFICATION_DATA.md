# 仿真、对照数据与结果

本文记录 TT_HSI_FPGA 各验证环节使用的脚本、输入数据、参考数据、输出位置和结果。
项目中的二进制文件分为两类：模型运行参数，以及固定测试样例的 golden 参考数据。

## 一、总体验证链

```text
官方 checkpoint
    -> tt_model.py / audit_model.py：确认模型结构
    -> fixed_point_sim.py：确认定点路径
    -> export_golden.py：生成固定 patch 和各阶段参考数据
    -> HLS C 仿真 / RTL cosim：确认 PL 算子
    -> host_test.cpp：确认 PS + PL 仿真的整网流程
    -> Vitis 板上程序：确认真实 PL、PS 和 DDR 协作
```

## 二、模型结构对照

### 使用的脚本和数据

| 项目 | 内容 |
|---|---|
| 当前项目模型 | `model/tt_model.py` |
| 上游模型源码 | `D:/FPGAlearn/Tensor-Transformer-for-HSIC-master/Tensor-Transformer-for-HSIC-master/TensorTransformerFramework.py` |
| 官方权重 | `TensorTransformerHSI_unoverlapping_LK.pth`、`TensorTransformerHSI_overlapping_LK.pth` |
| 对照脚本 | 上游目录 `analysis/audit_model.py` |
| 详细报告 | 上游目录 `analysis/audit_results.json` |

运行当前项目自检：

```powershell
D:\pytorch\python.exe model\tt_model.py
```

该命令检查 `mode_dot` 约定、官方 checkpoint 的严格加载和参数数量；结果主要打印在终端。

重新执行上游模型结构对照：

```powershell
D:\pytorch\python.exe `
  D:\FPGAlearn\Tensor-Transformer-for-HSIC-master\Tensor-Transformer-for-HSIC-master\analysis\audit_model.py `
  --tensorly-path D:\FPGAlearn\tmp\tensor_transformer_audit_deps
```

报告重点字段：

```text
strict_load_missing: []
strict_load_unexpected: []
vectorized_fp32_batch2_max_abs: 4.76837158203125e-07
vectorized_fp64_batch1_max_abs: 6.66133814775094e-16  (非重叠模型)
vectorized_fp64_batch1_max_abs: 9.99200722162641e-16  (重叠模型)
```

FP32 的约 `4.8e-7` 是单精度运算误差；FP64 的约 `1e-15` 接近双精度舍入误差。

注意：此审计脚本比较的是上游原始类与它在内存中构造的向量化实现，没有直接导入本项目 `model/tt_model.py`。`strict=True` 只验证参数名称和形状匹配；它本身不能证明 forward 行为相同。

## 三、定点仿真

脚本：`model/fixed_point_sim.py`

```powershell
D:\pytorch\python.exe model\fixed_point_sim.py
```

它使用官方 checkpoint，生成随机 patch，比较纯浮点路径和定点路径，扫描候选定点格式。
结果默认打印在终端，不自动写单独的日志文件。

定点路径中：

- PS 部分按浮点逻辑执行；
- Tucker 投影按 `model/quant.py` 的整数运算执行，模拟 PL；
- 当前格式为激活 Q3.12、权重 Q1.14、中间量 Q3.14。

## 四、黄金数据导出

脚本：`model/export_golden.py`

```powershell
D:\pytorch\python.exe model\export_golden.py `
  --model unoverlapping `
  --pixel 224 158
```

`--pixel` 的两个数是原图的行、列坐标，从 0 开始。脚本使用：

- 官方 checkpoint；
- `model/preprocess.py`；
- LongKou 原始数据 `WHU_Hi_LongKou.mat`；
- 标签数据 `WHU_Hi_LongKou_gt.mat`。

输出目录：`model/data/` 和 `model/data/golden/`。

### 正式模型参数

| 文件 | 用途 |
|---|---|
| `weights_all.bin` | 12 层 × 4 个 Tucker 投影的合并定点权重，部署使用 |
| `w_L{layer}_{query,key,value,mlp}.bin` | 每层单独权重，便于检查和调试 |
| `cls_token.bin` | 初始 cls token |
| `pos_embed.bin` | 位置编码 |
| `classifier_w.bin`、`classifier_b.bin` | 最后的 9 类全连接分类头 |

### 固定测试样例和参考结果

| 文件 | 含义 | 主要使用环节 |
|---|---|---|
| `golden/patch_f32.bin` | 指定像素的预处理后 patch，float32 | C++ 整网测试、板上测试 |
| `golden/in_qkv.bin` | 第 0 层 Q/K/V 投影输入，int16 | HLS C/RTL 仿真 |
| `golden/w_q.bin`、`w_k.bin`、`w_v.bin` | 第 0 层 Q/K/V 权重，int16 | HLS C/RTL 仿真 |
| `golden/out_q.bin`、`out_k.bin`、`out_v.bin` | Q/K/V 正确输出，int16 | HLS C/RTL 仿真 |
| `golden/in_mlp.bin` | 第 0 层 MLP 投影输入，int16 | HLS C/RTL 仿真 |
| `golden/w_mlp.bin` | 第 0 层 MLP 权重，int16 | HLS C/RTL 仿真 |
| `golden/out_mlp.bin` | MLP 正确输出，int16 | HLS C/RTL 仿真 |
| `golden/layer_out_fixed.bin` | 12 层每层完成后的参考输出，float64 | C++ 整网测试 |
| `golden/logits_fixed.bin` | 混合定点路径最终的 9 个 logits，存储类型 float64 | C++ 整网和板上最终对照 |
| `golden/logits_float.bin` | 最终 9 个纯浮点 logits，float64 | 浮点/定点误差参考 |
| `golden/meta.txt` | 模型、坐标、定点格式、标签和 logits 的说明 | 测试索引和 C 数组生成 |

`golden` 文件不是手动填写的，都是 `export_golden.py` 根据官方权重和指定 patch 自动生成的。

## 五、C 数组生成

脚本：`model/export_c_arrays.py`

```powershell
D:\pytorch\python.exe model\export_c_arrays.py
```

读取 `model/data/` 和 `model/data/golden/`，自动生成：

```text
vitis/src/tt_data.c
vitis/src/tt_data.h
```

这些文件把模型参数、黄金 patch 和最终参考 logits 编译进 Vitis 应用。换测试像素后，必须先重新运行 `export_golden.py`，再运行本脚本，然后重新编译 Vitis 应用。

## 六、HLS C 仿真和 RTL 协同仿真

### C 仿真

脚本：`hls/run_csim.tcl`

```powershell
cd hls
D:\xilinx\Vitis_HLS\2020.2\bin\vitis_hls.bat -f run_csim.tcl
```

测试平台：`hls/tb/tb_tucker_proj.cpp`。

它读取 `golden/in_qkv.bin`、`golden/w_q.bin` 等输入，运行 `hls/src/tucker_proj.cpp`，并逐元素比较：

```text
PL Q 输出 vs golden/out_q.bin
PL K 输出 vs golden/out_k.bin
PL V 输出 vs golden/out_v.bin
PL MLP 输出 vs golden/out_mlp.bin
```

已保存的历史日志：`hls/csim_run.log`。该名字不是 Tcl 自动指定的输出路径；需重定向/保存终端输出才会更新它。历史结果为：

```text
Q/K/V/MLP mismatches 0
PASS: bit-exact
```

### RTL 协同仿真

脚本：`hls/run_cosim.tcl`。它使用综合后的 RTL，再由同一个测试平台进行 C 后处理比较。

已保存的历史日志：`hls/cosim_run.log`，同样需保存终端输出来更新。历史结果为：

```text
Q/K/V/MLP mismatches 0
C/RTL co-simulation finished: PASS
```

综合报告和中间文件位于：

```text
hls/tt_prj/sol_100mhz/syn/report/
hls/tt_prj/sol_100mhz/sim/
```

## 七、C++ 主机整网仿真

编译和运行：

```powershell
D:\mingw64\bin\g++ -O2 -std=c++11 `
  -o vitis\host_test.exe `
  vitis\host_test.cpp vitis\src\tt_net.cpp vitis\src\tt_hw_sim.cpp
vitis\host_test.exe *> vitis\host_test.log
```

这里：

- `tt_net.cpp` 执行 PS 端整网流程；
- `tt_hw_sim.cpp` 用整数运算模拟 PL Tucker 投影；
- `host_test.cpp` 读取 `golden/patch_f32.bin`、`golden/layer_out_fixed.bin` 和 `golden/logits_fixed.bin`。

对照内容：

```text
每层 C++ 输出        vs golden/layer_out_fixed.bin
最终 C++ logits      vs golden/logits_fixed.bin
```

结果默认打印到终端。使用上面的 `*>` 后，结果保存为 `vitis/host_test.log`。2026-09-15 新增完整前向计时：预热一次后测 10 次，排除文件读写、验证及打印。当前 `(20,20)` 样例的逐层最大误差 `3.997e-15`，最终 logits 最大误差 `1.776e-14`，10 次 PASS；平均完整前向 **17.730 ms/patch**。测试范围、记录和板上对照见 [CPU_PL_BENCHMARK.md](CPU_PL_BENCHMARK.md)。

## 八、Vivado 和板上结果

Vivado 实现结果保存在：

```text
vivado/impl_utilization.rpt
vivado/impl_timing.rpt
vivado/tt_soc.xsa
```

这些文件记录实际资源占用、时序和导出的硬件平台，不记录具体 patch 的 logits。

板上程序为 `vitis/main.cpp`。它将 `tt_data.c` 中的 `tt_patch` 送入真实 PS/PL 系统，最终比较：

```text
板上 logits vs tt_ref_logits[]
             即 golden/logits_fixed.bin
```

板上当前主要通过串口输出结果；代码没有把串口内容自动写入仓库文件。输出若需保存，应在串口工具中导出，或由终端工具记录。

新增 `vitis/main_benchmark.cpp` 可在同一程序中通过串口 `1/2/3` 选择 PL、纯 PS、连续对比，已同步到用户的 `vitis/tsamapp/src/main_benchmark.cpp`。2026-09-15 用户提供的串口日志记录：同一 `(20,20)` patch，PS+PL 平均 140.102 ms、纯 PS 平均 1206.110 ms，两组均 PASS，由均值计算整网加速比 8.609×。原始记录在 [board_uart_20260915_pixel20_20.txt](results/board_uart_20260915_pixel20_20.txt)。操作、逐层计时和测量边界见 [CPU_PL_BENCHMARK.md](CPU_PL_BENCHMARK.md)。

## 九、换测试像素后的更新范围

如果只切换同一模型的测试像素：

```powershell
D:\pytorch\python.exe model\export_golden.py --model unoverlapping --pixel 100 200
D:\pytorch\python.exe model\export_c_arrays.py
```

然后重新编译 Vitis 应用即可。需要更新的是：

- `model/data/golden/*`；
- `model/data/golden/meta.txt`；
- `vitis/src/tt_data.c`、`vitis/src/tt_data.h`；
- Vitis 应用中的编译产物。

不需要重新训练模型、重新综合 HLS 或重新生成 Vivado bitstream。`model/visualize.py` 生成的 `lk_golden.png` 和 `lk_golden_zoom.png` 只是位置可视化；换点时需同步修改其中的坐标后单独运行该脚本。
