# 同板单像素 PS 与当前 PL 实测

## 可直接填写的主结果

| 字段 | 实测值 |
| --- | --- |
| 纯 PS 单像素均值 | 357.731842 ms，PPT 可显示 357.732 ms |
| 当前 PL 方案单像素均值 | 3.632565 ms，PPT 可显示 3.633 ms |
| 加速比 | 357.731842 ÷ 3.632565 = 98.479122，PPT 可显示 **98.48 倍** |
| 测试日期 | 2026-10-26，20:47，Asia/Shanghai |
| 开发板 | 本项目同一块 AXU5EV-E，Cortex-A53 #0 |
| 场景与像素 | Longkou，零基行51、列358，batch=1，每次一个中心像素 |
| 模型及权重 | unoverlapping，12层，9类，Longkou v2，weights_engine CRC32=27231983 |
| 输入 | normalized_patch_f32.bin，float32 CHW [270,7,7]，两端复用同一板上内存 |
| 输入 SHA256 | aa1ea9a584845785aec950e0b9071f57c407a9659302284bc30b10795b1e00ce |
| PS 频率 | BSP记录 1066656005 Hz，约1066.656 MHz |
| PL 频率 | 驱动核对PLL/分频配置，199998000 Hz，约199.998 MHz |
| 计时器 | 33333000 ticks/s |
| 预热与重复 | 每种路径各预热1次，随后10次计时，使用单输入延迟算术均值 |
| 输出检查 | 两端11次输出类别均为 3（零基），类别一致 |
| logits最大绝对误差 | 0.002254963，低于项目已有 TT_LOGIT_TOL=0.01，PASS |

倍率使用未舍入均值计算。原始 ticks、每次毫秒值与全部logits见 results.json，samples.csv 提供30条逐次计时记录。

## 计时边界与数值差异

从已取窗、已归一化的输入patch开始，包含PS嵌入、完整12层编码、分类头，直到PS取得logits结束。当前PL方案调用一次FULL LOGITS，包含输入缓存维护、驱动寄存器调用、完成轮询、输出缓存维护和输出拷贝。两端均计算完整网络。

首次权重解析/装载、取窗、归一化、读盘、JTAG下载/读取、网络、显示、输出验证和日志均在计时外。等待服务回调关闭，独立测试程序不运行地面站通信或显示。此结果表示当前硬件方案在该边界下的推理延迟，不表示原地面站任务总耗时或含取窗的ROI累计速度。

主基线复用本项目现有 tt_forward + tt_hw_sim：嵌入和注意力/残差/头包含float32/NEON运算，层间激活int16 Q3.12。当前PL执行W16A18编码和定点分类头，PS嵌入与主基线使用相同函数。两端采用同一v2模型导出文件，原始投影权重与引擎包中的投影段已逐字节核对一致。数值路径不同，误差按项目已有阈值与类别一致检查，不能声称主基线逐位相同。

频率来自BSP和驱动读取的配置，未进行示波器频率测量。倍率仅适用于本项目配套PS实现与当前PL方案，不代表通用CPU或最优CPU实现。

## 补充：同算术整数PS参考

另将项目已有 sim/host/engine_ref.cpp 的整数参考运行在同一Cortex-A53上，复用相同PS嵌入。编码、注意力、残差和分类头采用与PL匹配的W16A18算术，PS中间值用int64保存。

该参考每次从patch开始完成整网，各预热1次并计时10次，均值 417.916257 ms。它与PL在预热及全部10次测量中的9个Q16 logits逐项一致，最大误差0。对应倍率 115.047142 倍。

此项用于数值对拍及额外性能参考。PPT主结果仍采用原配套PS实现的 98.48 倍，不混用两种PS基线。

## 固件与可追溯依据

- 测试ELF SHA256：ad6baf8c1dbd753e358264b2e4b77999829affdfc2db3f00192d6416ad7f6b84
- 测量沿用已编程的当前ABI4引擎，软件回读ABI/位宽/小数位与硬件cycles，未将仿真计时写成板上计时。
- 已部署硬件XSA SHA256：dbf0b52ccbd076c7dae4ed37e5ef6ed48b4f5bbc6ac76a174b8ad339ac282508。
- 已部署位流SHA256：9c0c1732275e941811d110466a16c92d40fe833b1f93b4af27e8a4008b744ce1。
- 测试程序、依赖源哈希、编译选项和命令详见 build_manifest.json。编译使用已安装Vitis 2026.1的AArch64 GCC工具链，-O2 -mcpu=cortex-a53 -ffp-contract=off。
- 原始JTAG采集记录：[measure_jtag.log](D:/FPGA.GAME/HSI_AgriEdge_team_20261017/build/host/single_pixel_pair_20261026/measure_jtag.log)。结果由板端计时器和输出写入DDR，JTAG在完成后读取，读取本身不计时。
- 测试构建及复现脚本目录：[single_pixel_pair_20261026](D:/FPGA.GAME/HSI_AgriEdge_team_20261017/build/host/single_pixel_pair_20261026)。输入构建脚本 prepare_benchmark.py，板卡执行脚本 run_board.py，结果解码 analyze_result.py。
- 执行脚本限定首次测试前boot=228ce12a以防误接其他启动，复测必须先确认新连接身份并显式调整该前置条件，不能直接盲目重放。

## 演示恢复

已恢复原部署的 gcs_keys.elf、配套位流与FSBL，release=2c861dad3ec37fbcbfcd5a08dcc56aae62d1aec2b342007f1bbaf04041b59094。首次重连返回HTTP 409，原失败记录保留在 run_receipt.json，随后真实以太网重连成功，boot=228ce12b，DP初始化返回0，当前无运行任务。106个历史任务目录仍在。

恢复依据：[service_after.json](D:/FPGA.GAME/HSI_AgriEdge_team_20261017/build/host/single_pixel_pair_20261026/service_after.json)、[restore_jtag.log](D:/FPGA.GAME/HSI_AgriEdge_team_20261017/build/host/single_pixel_pair_20261026/restore_jtag.log)、run_receipt.json。原项目源文件与权重在测量前后哈希一致，测试程序保存在独立构建目录。
