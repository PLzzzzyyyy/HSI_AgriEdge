# 2026-09-28 技能包 factory_psu_extract：出厂 PS 配置抽取、对比、初始化代码核对与平台自检

## 任务
把 C1 的 `tools/extract_psu_cfg.py`、`tools/check_xsa_platform.tcl`、`tools/fix_xsa_driver_makefile.py` 通用化成 `skill/factory_psu_extract/`，README 五段，在本项目外验证后入库。

## 提示与回答要点
- 通用化：PS 单元按 vlnv 自动找（ZU+ `zynq_ultra_ps_e` / 7000 `processing_system7`）；新增 `--diff` 对比两个 .bd 的 PS 配置；新增 `diff_xsa_init.py` 对比两个 XSA 的 `psu_init.c` / `ps7_init.c` 寄存器写；平台自检的驱动名改成参数，不再写死 tucker_proj。
- 回归：新脚本在出厂 .bd 上的输出与已入库的 `build/vivado/psu_cfg_factory.tcl` 逐行相同（1013 项，只有首行注释不同）。
- 本项目外验证对象：`D:\TT_HSI_FPGA`（7020 的 .bd、`ps7_cfg.tcl`、两个 XSA）、`D:\FPGAlearn\pose6d_fpga`（7020 .bd）。

## 失败与纠错
- `diff_xsa_init.py` 第一版正则要求逗号紧跟数值：`ps7_init.c` 写成 `0x...U ,0x...U`（逗号前有空格），一次都匹配不上；改成 `\s*,\s*`。
- 改完后 `psu_init.c` 解析 740 次，数调用得 756 次；少的 16 次是 SERDES 校准函数里值为变量（`ill12_val[i]`）的写。改成值可为任意表达式，照原文比，得 756。
- XSCT 平台自检在 7020 原 XSA 上失败，退出码仍是 0，只能看输出里有没有 `CHECK PASS`，已写进 tcl 头注释和 README 失效条件（与 pitfalls 09-23 "XSCT 失败也不报错"同类）。
- README 写入后又出现 U+FFFD（"技能包"的"能"），按 pitfalls 09-26 的办法用码位替换修复。

## 人工判断
- `tools/` 下的原脚本不改，技能包里放通用化版本；`fix_xsa_driver_makefile.py` 原样复制进技能包，让技能包单独可用。
- 对比结果只陈述事实：PL0 改频率后 RPLL 连带重规划（IOU_SWITCH、DP 音频 / STC、PL1 分频变化），PROTECTION__SLAVES 少了 FPD_GPV、CCI_GPV 两个条目，原因未查明，不下结论。

## 验证（全部为 PC 上的工具输出，非板上）
- 出厂 .bd vs 本项目 `tt_zu5ev` .bd：15 项不同，全部来自 5 项覆盖及其派生项。
- 出厂 `top.xsa` vs `tt_zu5ev.xsa`：`psu_init.c` 756 / 751 次写，9 个差异块，分属 RPLL 重规划、UART1 关闭、AFIFM2/3 宽度；DDR、MIO 写完全相同。
- 7020 `tt_soc` .bd：83 项，与 `ps7_cfg.tcl` 共有项只差 HP2/HP3 使能（`build_tt_soc.tcl` 有意覆盖）；`ps7_cfg.tcl` 多出的 56 项都是派生值（分频、PLL、DDR 时序）。
- 7020 `tt_soc` vs `tt_soc_fm64_wt32_df_norm`：.bd 差 2 项，`ps7_init.c` 432 次写 0 个差异块（阳性对照）。
- pose6d `conv_soc_cam` .bd：162 项。
- XSCT 2020.2：出厂 `top.xsa` PASS；7020 `tt_soc.xsa` 原件驱动 Makefile `Error 2`；副本经 fix（去 3 行）后 PASS，`xtucker_proj.h` / `xtucker_proj_hw.h` 生成；要求不存在的驱动头文件时 `CHECK FAIL`。

## 关联
- 技能包：`skill/factory_psu_extract/`；索引 `skill/README.md`。来源记录 `2026-09-23_c1_zu5ev_platform.md`。
