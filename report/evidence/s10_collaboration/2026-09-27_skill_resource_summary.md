# 2026-09-27 技能包 resource_summary：README 五段与本项目外验证

## 任务
把 `skill/resource_summary/resource_summary.py`（Vivado / Vitis HLS 报告 → 资源与时序汇总表）补齐 README 五段，在本项目外的工程上验证一次后入库，作为第一个交付的技能包。

## 提示与回答要点
- 验证对象选 `D:\TT_HSI_FPGA`（7z020、7 系列、整板工程带 8 个 IP OOC 子运行），与本项目的 ZU5EV / UltraScale+ 报告格式不同，能测到 7 系列行名（Slice LUTs）、无 URAM、OOC 子运行过滤、黑盒提示。
- 跑了四组：整板目录自动发现；HLS `tucker_proj` 与该 IP 的 OOC 综合同名对照；同一整板的报告副本单文件输入；不支持的 `drc_opted.rpt`（应报错、退出码 1）。
- 本项目内再跑一次 `tt_engine_k7/sol`，覆盖 UltraScale+ 与 export.rpt 交叉核对。

## 失败与纠错
- README 初稿把 `2026-09-23_c1_zu5ev_platform.md` 列为"综合报告里 IP 是黑盒"的来源；grep 该记录没有相关内容，删掉，只保留确有依据的两条（09-25 OOC 定档、09-26 D2 K7 资源）。

## 人工判断
- 比值表只在同名设计之间算：IP 的 HLS 估计与整板实现同名会混进 PS 和互联，README 写成失效条件，不在脚本里强行合并。

## 验证（全部为工具报告数字，非板上）
- TT_HSI_FPGA 整板实现：LUT 13,012 / FF 13,804 / BRAM36 85 / DSP 160，WNS +0.374、WHS +0.031 ns，与 `impl_utilization.rpt`、`impl_timing.rpt` 原文逐项一致。
- tucker_proj：HLS LUT 29,365 / BRAM18 109 / DSP 156 / 7.300 ns / latency 30,543～252,527，与 `tucker_proj_csynth.rpt` 一致；OOC 综合 LUT 13,406、BRAM36 85（RAMB36 24 + RAMB18 122）、DSP 160，与原报告一致。
- 不支持格式报错、退出码 1。
- 本项目 K7：实现 LUT 42,722（36.5%），与 D2 第 5 轮记录一致；export.rpt 资源与达成周期（3.729 / 4.961 ns）交叉核对一致。

## 关联
- 技能包：`skill/resource_summary/`；索引 `skill/README.md`。
