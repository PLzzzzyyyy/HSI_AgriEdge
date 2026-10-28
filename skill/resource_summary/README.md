# resource_summary：Vivado / Vitis HLS 报告 → 资源与时序汇总表

## 1. 适用范围

- 问题：设计报告和优化对比里要反复写 LUT / FF / BRAM / URAM / DSP、WNS、HLS latency，手抄容易抄错口径（BRAM 36 Kb 与 18 Kb 混用、把 HLS 估计当实现结果、综合报告里 OOC IP 是黑盒只剩 0）。
- 输入（按文件内容识别，不看文件名）：
  - Vivado `report_utilization`（整板或 OOC；UltraScale+ 与 7 系列；综合 / 布局 / 布线）
  - Vivado `report_timing_summary`
  - Vitis HLS `<top>_csynth.rpt`；2020.2 的 `csynth.rpt` 汇总表会自动改读同目录的 `<top>_csynth.rpt`
  - Vitis HLS `export_design -flow syn/impl` 的 `<top>_export.rpt`：与同阶段 Vivado 报告交叉核对，缺 Vivado 报告时当数据源
- 前提：Python 3（只用标准库）；验证过的工具版本是 Vivado / Vitis HLS 2020.2。
- 输出：Markdown 表（每个设计每个阶段一行）、同名设计的"HLS 估计 vs Vivado"比值表、核对与提示、来源文件清单；可选 CSV（UTF-8 带 BOM）。

## 2. 用法

```
python skill/resource_summary/resource_summary.py <报告文件或目录> [...] [--label 名字 ...] [--md out.md] [--csv out.csv]
```

- 给目录时自动发现：`*.runs` 只进 `synth_N` / `impl_N`（IP 的 OOC 子运行跳过）；HLS 导出工程读 `impl/verilog/report`，跳过 `project.runs` 里的黑盒 wrapper；`syn/report` 只取 `csynth.rpt`。
- `--label` 按顺序对应每个输入；同名的输入并成一个设计，才会出 HLS vs Vivado 比值表。
- 退出码：有任一输入报错（路径不存在、不认识的报告、表被截断）返回 1，否则 0。

最小例子（HLS 导出工程目录，一次拿到 HLS 估计、Vivado 综合、Vivado 实现三行和比值表）：

```
python skill/resource_summary/resource_summary.py build/hls/optimization_build/tt_engine_k7/sol
```

HLS 估计与 IP 的 OOC 综合对照（两个输入同名）：

```
python skill/resource_summary/resource_summary.py <hls>/sol/syn/report <prj>.runs/<ip>_synth_1/<ip>_utilization_synth.rpt --label ip --label ip
```

## 3. 失效条件

- 不支持分层利用率报告（`report_utilization -hierarchical`），会跳过并提示；要看子模块资源得另查。
- 整板工程的综合报告里，单独 OOC 综合的 IP 是黑盒，资源显示为 0 或偏小。脚本会标"含 N 个黑盒"，整体资源以实现报告为准。
- 比值表只在同名设计之间算。把 IP 的 HLS 估计和整板实现取同名，比值会混进 PS、互联等其他逻辑，没有意义。
- 同一设计同一阶段有多份报告时，只取一份（布线优先于布局），其余在提示里列出"忽略"。
- 时序报告有多个时钟时，达成周期按 WNS 所在时钟计算；找不到该时钟的周期记 n/a。
- 数字全部来自工具报告，不是板上测量；HLS 估计只看趋势。
- 只在 2020.2 的报告格式上验证过；其他版本表头变化时会报"找不到某行"，不会静默出错数。

## 4. 已验证效果

全部是工具报告数字（非板上），逐项与原报告人工核对一致。

| 算例 | 器件 / 版本 | 输入 | 结果 |
|---|---|---|---|
| 本项目外：`D:\TT_HSI_FPGA` 整板工程 `vivado/tt_soc` | 7z020，Vivado 2020.2 | 目录自动发现 | 实现：LUT 13,012（24.5%）、FF 13,804、BRAM36 85、DSP 160，WNS +0.374 / WHS +0.031 ns；8 个 OOC IP 子运行被跳过；综合行正确标出"含 8 个黑盒"；URAM 列 7 系列显示 — |
| 本项目外：`D:\TT_HSI_FPGA` 的 `tucker_proj` HLS + IP OOC 综合 | 7z020，Vitis HLS 2020.2 | 两个输入同名 | HLS LUT 29,365 / BRAM18 109 / DSP 156 / 7.300 ns；OOC 综合 LUT 13,406、BRAM18 170（= 24 × 2 + 122）、DSP 160；比值 LUT 0.46、BRAM 1.56、DSP 1.03 |
| 本项目外：同一整板的 `vivado/impl_utilization.rpt` + `impl_timing.rpt` 副本 | 同上 | 单文件 | 与 `impl_1` 目录结果完全相同 |
| 本项目外：`drc_opted.rpt`（非支持格式） | 同上 | 单文件 | 报"不认识的报告格式"，退出码 1 |
| 本项目：`build/hls/optimization_build/tt_engine_k7/sol` | xczu5ev，Vitis HLS / Vivado 2020.2 | 目录自动发现 | 实现 LUT 42,722（36.5%）、FF 53,003、BRAM36 63.5、URAM 14、DSP 530，WNS +0.039 ns @5 ns；HLS LUT 81,172（实现 / HLS = 0.53）；export.rpt 与利用率报告、达成周期 3.729 / 4.961 ns 交叉核对均一致 |

复现：上表命令在两台工程的原始目录上直接运行即可（`D:\TT_HSI_FPGA` 为只读来源工程）。

## 5. 提炼来源

- `report/llm_log/2026-09-25_vivado_ooc_d3_attn.md`：HLS 对 LUT 的高估比例随并行度变化（K7 30%、K14 11%），不能按固定比例折算，需要每次把 HLS 估计与 Vivado 并列。
- `report/llm_log/2026-09-26_d2_k7_resource.md`：D2 多轮资源迭代里反复手抄 HLS / 综合 / 实现三组数字。
- `report/llm_log/2026-09-27_skill_resource_summary.md`：本技能包的外部验证记录。
- 对应 pitfalls：`[继承] HLS 资源估计不可信，Vivado 实现结果才算数`。
