# skill/：可复用技能包

对应指南 §3.3.5.2，评分项"大模型协作与技能包"15 分（与 `report/llm_log/` 共用）。PYNQ 通用 skill 是单独加分项，本项目裸机路线不做。

## 每个技能包必须有

`skill/<name>/README.md`，五段：
1. **适用范围**：什么问题、什么前提（工具版本、数据布局）。
2. **用法**：最小输入、命令、预期输出，能直接跑。
3. **失效条件**：什么情况下不该用、已知不管用的场景。
4. **已验证效果**：在哪些算例上验过，数字与来源（主机/仿真/板上分开写）。
5. **提炼来源**：来自 `report/llm_log/` 哪条记录。

脚本或提示词模板与 README 放同一目录。不得只有 README 没有可执行内容。

## 候选清单（从 llm_log 提炼，按优先级）

- `golden_compare`：黄金向量生成 + 逐层/逐位比对（B3 已有 `sim/gen_golden.py`，待包装成通用比对脚本）；排查步骤含"逐位不一致先查饱和"（B2 经验）。
- `fixed_regression`：定点 vs 浮点抽样回归 + 饱和定位（B2 已有 `model/fixed_regression.py`、`model/saturation_stats.py`，待抽象成对任意 float/fixed 两路函数的通用脚本）。
- `layout_check`：DDR 块布局 / 权重打包 / 地址 32 位算术的静态检查（来自 7020 pitfalls）。
- `a9_to_a53_port`：7020 裸机代码搬 ZU5EV 的检查清单（`__arm__`/`__aarch64__`、cache 行 32→64、清理指令、IP 32 位地址、CPU 频率宏）+ XSCT 编译自检（C2 已有 `tools/build_zu5ev_app.tcl`）。
- `toolchain_pitfalls`：Vitis 平台重建、HLS 驱动 Makefile、Vivado exec python 三个排错案例（pitfalls 已有素材）。
- `vendor_manual_diff`：两份厂商手册去空格逐行 diff 找硬件差异。

## 已交付

| 技能包 | 做什么 | 验证 | 来源 |
|---|---|---|---|
| [resource_summary](resource_summary/README.md) | Vivado / Vitis HLS 报告 → LUT / FF / BRAM / URAM / DSP、WNS、latency 汇总表与 HLS vs Vivado 比值（Markdown / CSV） | 本项目外 TT_HSI_FPGA（7z020）+ 本项目 tt_engine_k7（ZU5EV），与原报告逐项一致 | 2026-09-25、09-26 llm_log |
| [factory_psu_extract](factory_psu_extract/README.md) | 厂商出厂 .bd → PS CONFIG tcl（ZU+ / 7000）；两个 .bd 的 PS 配置对比；两个 XSA 的 psu_init / ps7_init 寄存器写对比；XSCT 临时平台自检 + 驱动 Makefile 修复 | 本项目 AXU5EV-E 出厂工程 vs tt_zu5ev（覆盖 5 项，初始化代码 9 个差异块，DDR / MIO 不变）；本项目外 TT_HSI_FPGA、pose6d_fpga（7020） | 2026-09-23 C1 llm_log |
