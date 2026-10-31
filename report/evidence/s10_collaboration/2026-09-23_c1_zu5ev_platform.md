# 2026-09-23 C1：ZU5EV 硬件平台（出厂 PSU 配置 → v1.4 IP 重导 → Vivado 实现 → XSCT 平台检查）

工具：Claude Code（Fable 5.1）。提交：a22428a。本条据会话记录、提交与构建日志补写。

## 任务

PLAN §17 C1：ZU5EV 工程，PS 配置取自厂商 factory_vivado；v1.4 IP 接 HP 口（非一致口）；导出 XSA；`tools/check_xsa_platform.tcl` 建裸机平台；修驱动 Makefile。"hello world 串口输出"等板子，本条只到平台生成。

## 提示与回答要点

- 用户："继续" → 模型开 C1，发现 `factory_file.zip` 还在下载（24.9 GB），先看目录不动手。
- 用户："下载好了" → 只解 `factory_vivado.zip`。grep 抓 `.bd` 里的 PSU 参数抓不全（多行 JSON 对象），改写 `tools/extract_psu_cfg.py` 解析 JSON 直接导 tcl，1013 项全抽，格式与 7020 的 `ps7_cfg.tcl` 一致。
- 模型自主完成：v1.4（fm64_wt32_df_norm）按 xazu5ev 重跑 csim + csynth + export（`build/hls/run_zu5ev_export.bat`），IP 源码不改；`build/vivado/build_zu5ev.tcl` 把出厂配置原样 source 再覆盖 5 项；XSA 导出后就地修驱动 Makefile；XSCT 建临时平台自检。长任务脱离进程跑，日志落文件。
- 用户："这个是构建的什么平台完全copy7020的那个吗" → 不是。PS 侧 1013 项配置全部来自出厂工程，7020 的 ps7 配置一项没用，只覆盖 PL0 100 MHz、HP0/HP1 64 位、关 EMIO GPIO 与 UART1；PL 侧结构与 7020 相同（一个 tucker_proj v1.4 IP，CTRL 走 HPM0_LPD，FM/WT 走 HP0/HP1），IP 按 ZU5EV 器件重新综合导出，另加风扇常量输出。

## 失败与纠错

- Edit 工具替换 `docs/ABSTRACT.md` 几百字中文段落对不上，写入还混入 U+FFFD 乱码，三轮返工；改脚本按标题切分整节替换，写完查乱码计数。已记 pitfalls 09-23 条。
- HLS csynth 估计与 Vivado 实现差得远（见验证表）。按规则只看趋势，没有据此做决策。

## 人工判断

会话前，人定的：
- 证据规则：板上数字只认串口或地面站输出；设计决策以 Vivado 实现为准，HLS 估计只看趋势；HLS 改动攒批再导 IP、再建平台；Vitis Build 与上板由用户做。C1 全程照此执行。
- 材料：厂商 factory_file.zip 由用户下载到位，模型才开工。
- 手册 DDR4 型号不一致、SD_CLK 引脚写错，定"以出厂工程 PSU CONFIG 为准"（PLAN A3）；板子按 AXU5EVB-E 准备、上板看丝印定。C1 据此把器件做成 `PART`、风扇极性做成 `FAN_LEVEL` 变量。

会话中，模型定、用户未干预：
- 器件默认跟出厂工程 xazu5ev-sfvc784-1-i，不跟手册的 XCZU5EV-2，等丝印。
- 只覆盖 5 项 PSU 配置，psu_init 与厂商一致。
- IP 接非一致口 HP0/HP1，HPC 留到 C4。
- 内部简介按用户要求改成连贯叙述、500～600 字、含演示画面。

会话后，人做：
- 用 `build/vivado/tt_zu5ev.xsa` 在 Vitis 建平台、上板跑串口；看丝印定 `PART`、`FAN_LEVEL` 与网口 PHY。

## 验证

PC，Vivado / Vitis HLS / XSCT 2020.2。板子未到，无板上数字。

| 项 | HLS csynth 估计（只看趋势） | Vivado 实现（作数） |
|---|---|---|
| 时钟 | 估计 7.30 ns，目标 10 ns | WNS +1.856 ns，TNS 0，119986 个端点全部满足 |
| LUT | 54615 (46%) | 30442 (26.0%) |
| FF | 35164 | 22517 (9.6%) |
| BRAM | 108 × 18K (37%) | 53 tile (36.8%) |
| DSP | 163 | 180 (14.4%) |
| URAM | 0 | 0 |

- HLS csim（xazu5ev-sfvc784-1-i）：`PASS NORM_IN: bit-exact stats + Q/K/V/MLP vs tt_ref, Python replica, N=10 clamp/saturation`，`CSim done with 0 errors`。日志 `build/hls/optimization_build/fm64_wt32_df_norm_zu5ev.log`（不入库）。
- Vivado：`IMPL DONE  PART=xazu5ev-sfvc784-1-i  WNS=1.856084`，`All user specified timing constraints are met`。报告 `build/vivado/impl_zu5ev_{utilization,timing}.rpt`（入库），日志 `build/vivado/build_zu5ev.log`（不入库）。
- 驱动 Makefile：`tools/fix_xsa_driver_makefile.py` 就地去掉 3 行 `#echo`，原件留 `tt_zu5ev.xsa.orig`。
- XSCT：`CHECK PASS: platform generated with tucker_proj driver`，`xtucker_proj.h` / `xtucker_proj_hw.h` 生成，`libxil.a` 编出；`chk_zu5ev.err` 只有 BSP 自带的 unused-parameter 警告，无 error。
- PSU 抽取：`1013 parameters -> build/vivado/psu_cfg_factory.tcl`；MIO 与 `docs/BOARD_AXU5EV_E.md` §2 手册表逐项一致，核对表在 §6。

命令：
```
D:/pytorch/python.exe tools/extract_psu_cfg.py <factory_vivado 工程>/design_1.bd build/vivado/psu_cfg_factory.tcl
build\hls\run_zu5ev_export.bat
D:\xilinx\Vivado\2020.2\bin\vivado.bat -mode batch -source D:/HSI_AgriEdge/build/vivado/build_zu5ev.tcl
xsct D:/HSI_AgriEdge/tools/check_xsa_platform.tcl build/vivado/tt_zu5ev.xsa build/vivado/chk_zu5ev
```

→ 候选 skill：`factory_psu_extract`（从厂商 .bd 抽 PSU 配置 + 少量覆盖 + XSCT 平台自检）、`resource_summary`（HLS 估计 vs Vivado 实现对照表）。
