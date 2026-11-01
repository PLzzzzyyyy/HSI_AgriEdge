# 64×64 板上块推理和独立预测图

本功能复用现有 Tucker 投影 IP：PS 使用 float32 + NEON，两个独立工作区交错调度，让一个像素的 PS 计算与另一个像素的 PL 投影重叠。64×64 共4096个像素，每个像素仍执行完整12层网络。无需因本功能重建 HLS/Vivado 平台。

用户选择只导出独立预测图。输出为 `D:/TT_HSI_FPGA/board_results/board_prediction.bmp`，64×64分类结果按最近邻放大到512×512，24位BMP，786486字节，颜色沿用PC图。推理与渲染都在板上完成；XSCT仅通过JTAG将DDR字节复制到电脑文件。裸机PS本身不能直接打开Windows的D盘路径。

2026-09-16，用户已完成4096像素真实板上流水推理，分类与PC定点参考100%一致。板上已报告BMP内存地址和长度；用户执行XSCT命令后尚未找到电脑文件，**BMP落盘及打开仍未验证**。当前应继续读取已有DDR结果，避免重新下载程序清掉结果。

## 在现有 Vitis 工程中运行

1. 刷新 `tsamapp` 项目（右键 Refresh 或 F5），让新增 `.cpp/.c` 文件被发现，然后 Build。活动入口仍是 `main_benchmark.cpp`，不要再加入另一个 `main.cpp`。统一保留 `TT_HW_RUNTIME_SWITCH`、`-O2`、`-std=c++11`；NEON仍通过 `tt_net.cpp` 内pragma启用。
2. 使用已有平台/bitstream，按原Debug流程下载程序并运行。不要停在 `main` 入口就等待串口，应先 Resume。
3. 推荐先发送ASCII `5`（关闭HEX发送）：程序用选块的两个不同角点，预热后做10次顺序/流水对照。必须看到 `PAIR CHECK PASS`，同时输出两种方式的平均ms/pixel。该流水数值是两个像素的吞吐，不是单个像素的延迟。
4. 发送ASCII `4`：再次检查两个patch，随后跑完4096个像素，每256个打印进度。发送 `6` 可运行同一块的顺序版本作为吞吐对照；`1/2/3` 的单像素基准仍然可用。
5. 等 `BLOCK COMPLETE` 和 `BMP READY`。在Vitis XSCT控制台选择运行应用的Cortex-A9 #0（可先用 `targets` 查看），必要时先在Debug界面Suspend。复制这次串口打印的完整命令，例如其形式为：

   ```tcl
   mrd -bin -file D:/TT_HSI_FPGA/board_results/board_prediction.bmp -size b <本次打印的地址> 786486
   ```

   地址随重新编译变化，不要照搬旧地址。`-size b`让长度单位为字节；省略时默认是word，会读多。目录已在工程下建立，若拷贝工程到其他位置需调整路径。
6. 在电脑打开 `board_results/board_prediction.bmp`。读取后可以Resume；再次导出会更新同名文件。在下一次块推理前完成读取，避免缓冲正在改写时获取图片。

只有完整推理成功、BMP生成并flush到DDR后才打印导出命令。数值无效或两patch对照失败时不导出新图；如果文件夹中已有旧图，它不会自动被删除。程序标志 `tt_board_prediction_bytes=0` 表示本次尚无可导出图。

## 结果和时间怎么看

- `PAIR CHECK PASS`：板上顺序/流水logits逐位一致，两个检查点分类也匹配PC定点参考。
- `Network only`：4096个像素的网络前向累计时间除以像素数，不含取窗、验证、串口、渲染和JTAG读取。
- `Patch extraction + normalization`：从预处理图块取7×7窗口、转CHW、做patch归一化的PS耗时。
- `Compute incl. extraction`：取窗+网络的有效计算时间；`loop wall`另含分类统计和进度串口。
- `Board vs PC fixed labels`：4096个分类与PC参考的一致率，不是对真值准确率。
- `Ground-truth OA`：仅在真值非零位置计算准确率，黑色未标注像素不计分。预测仍覆盖全部4096个像素。
- BMP生成、cache flush和导出说明打印另行计时；JTAG读文件由电脑执行，不包含在程序计时中。

2026-09-16用户提供命令4的[完整块板上记录](results/board_uart_20260916_block.txt)：

| 项目 | 4096像素实测 |
|---|---|
| 网络前向累计 | 152.810秒，37.307 ms/pixel |
| 取窗与patch归一化 | 0.389 ms/pixel |
| 网络+取窗有效计算 | 37.696 ms/pixel |
| 推理循环墙钟（含统计和进度串口） | 154.406秒 |
| 板上与PC定点参考分类一致 | 4096/4096，100% |
| 有效标注真值OA | 3411/3452，98.8123% |
| 渲染+cache flush+导出说明 | 25.433ms |
| PS报告BMP | 地址0x0070b860，786486字节 |

网络每像素值是整块流水的等效吞吐，不能解释为单个patch的延迟；JTAG读取由电脑执行，不包含在这些板上计时内。本次内存地址只对应这次运行。

同日已确认实际 `board_results/board_prediction.bmp` 成功落盘：786486字节、512×512 BMP，完整解码后的所有像素与PC预测图一致。[文件校验记录](results/board_bmp_validation_20260916.json)保留SHA256和比对结果。用户暂停A9 #0后读取成功，读完以 `con` 恢复；不必重新下载或推理。命令里的地址和长度须用空格分开，mrd成功时通常不自动显示图片，可用 `puts [file size D:/TT_HSI_FPGA/board_results/board_prediction.bmp]` 确认大小。

此前命令5的[真实串口日志](results/board_uart_20260916_pair_check.txt)：10次重复、两个不同patch，顺序/流水logits逐位一致，顺序 **57.692 ms/pixel**，双patch流水 **37.296 ms/pixel**，吞吐提升 **1.547倍**，等效每像素时间减少35.35%。该两patch基准不含取窗、验证和串口，完整块测量应使用上表。

此前用户提供的单次profile为57.637ms，与上述10次pair基准口径不同。20ms仍是后续优化目标；此次没有改PL位宽、HLS流水II，也未实施normalize/quant融合。

## PC 预览文件含义

目录 `docs/results/block_pc_preview/`：

| 文件 | 含义 |
|---|---|
| `block_pc_overview.png` | 整图中选块位置、块真值、PC预测的对照 |
| `ground_truth_64x64.png` | 数据集真值原图，不是推理输出 |
| `ground_truth_512.png/.bmp` | 同一真值图放大8倍，两个格式内容相同 |
| `pc_prediction_64x64.png` | 当前C++代码在PC上生成的4096像素预测 |
| `pc_prediction_512.png/.bmp` | 同一PC预测图放大8倍，两个格式内容相同 |
| `host_labels_u8.bin` | 4096个类别编号，逐行排列，每像素1字节 |
| `metrics.json` | 类别数量、准确率、与参考一致率等统计 |
| `host_validation.json` | 主机回归的数值结果和测试代码SHA256 |

块的零起始坐标为行112..175、列196..259，模型为 `unoverlapping`、N=6。PC顺序与流水的4096个logits和最终激活逐位一致，分类4096/4096匹配PC定点参考；最大logits差0.0042314；真值非零3452个，正确3411个，OA=98.8123%。这是PC验证，不能当作板上运行或板速。

## 开发验证与关键文件

`vitis/src/tt_block_app.cpp` 提供板上入口、两套完整且cache line独立的工作区、计时和导出命令；`tt_block_render.cpp` 直接向内存写BMP；`tt_block_data.c/.h` 嵌入5,292,000字节的70×70×270 float32图块、真值和参考。现有单像素 `(20,20)` 权重/输入数据保留。

`model/export_block.py --c-only` 可从现有块bin重生C文件而不重算参考。当前板上功能只接受64×64非重叠模型；自动选块以stride=4搜索，每类至少50像素，不能理解成所有窗口的全局最优。

独立命令行构建用于检查编译/链接，不运行Vitis IDE或下载板子：

```powershell
D:/pytorch/python.exe tools/build_board_benchmarks.py --source-dir vitis/tsamapp/src --output-dir vitis/benchmark_build/block_integration_synced
D:/pytorch/python.exe tools/test_block_pipeline.py --workers 6
```

主机异步桩延迟到wait执行实际整数投影，检查在飞数据不被覆盖。驱动cache桩检查flush/start/wait/invalidate顺序；这些软件检查不能替代板上真实cache和DDR竞争验证。驱动保留每次必要的输出flush，不以尚未证明的缓存删减宣称性能提升。
