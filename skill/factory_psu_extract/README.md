# factory_psu_extract：厂商出厂工程 PS 配置 → 可 source 的 tcl，少量覆盖，再核对初始化代码与平台

## 1. 适用范围

- 问题：新板卡的 PS 配置（DDR 型号与时序、MIO 分配、外设 IO、时钟）手册常有错（本项目手册 DDR4 型号不一致、SD_CLK 引脚写错），在 GUI 里照手册重配容易错。厂商出厂工程的 .bd 是在板上跑通过的配置，直接拿来用最稳。
- 做法四步：
  1. `extract_ps_cfg.py`：解析 .bd（JSON），抽 PS 单元全部 CONFIG 成 tcl（`create_bd_cell` + `set_property -dict`），构建脚本原样 `source`。
  2. 构建脚本在 source 之后只 `set_property` 覆盖本项目要改的少数几项。`extract_ps_cfg.py --diff` 对比出厂 .bd 与自己工程的 .bd，确认改动只有这几项。
  3. `diff_xsa_init.py`：对比两个 XSA 里 Vivado 生成的 `psu_init.c` / `ps7_init.c` 寄存器写，确认覆盖项没有改到 DDR、MIO 等不该动的寄存器。
  4. `check_xsa_platform.tcl`：用命令行 XSCT 拿 XSA 建临时裸机平台并 generate，确认 BSP 和自定义 IP 驱动能编过。HLS IP 的驱动 Makefile 在 Windows 下编不过时，先跑 `fix_xsa_driver_makefile.py`。
- 支持 ZU+（`zynq_ultra_ps_e`，`psu_init.c`）与 Zynq-7000（`processing_system7`，`ps7_init.c`）。PS 单元按 vlnv 自动找。
- 前提：Python 3（只用标准库）；Vivado / Vitis 2020.2 生成的 .bd、XSA；XSCT 2020.2。

## 2. 用法

```
# 1 抽取：出厂 .bd → tcl（打印参数个数和 DDR / 外设 IO / PL 时钟 / AXI 口等关键项）
python extract_ps_cfg.py <出厂工程>/<prj>.srcs/sources_1/bd/design_1/design_1.bd psu_cfg_factory.tcl
```

构建脚本里：

```
source psu_cfg_factory.tcl            ;# 建出 zynq_ultra_ps_e_0，变量同名
set_property -dict [list \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {64} ] $zynq_ultra_ps_e_0
```

```
# 2 .bd 级对比：出厂 vs 自己的工程，--expect 给期望差异项数，不等时退出码 1
python extract_ps_cfg.py <出厂 .bd> --diff <自己工程的 .bd> --expect 15

# 3 初始化代码对比：两个 XSA 的 PS 寄存器写序列，--expect 给期望差异块数
python diff_xsa_init.py <出厂.xsa> <自己的.xsa> --expect 9

# 4 平台自检（HLS IP 先修 Makefile；fix 会就地改写 XSA，原件留 .orig）
python fix_xsa_driver_makefile.py <自己的.xsa>
xsct check_xsa_platform.tcl <xsa> <临时目录> [psu_cortexa53_0 | ps7_cortexa9_0] ["x<ip>*.h" ...]
```

`check_xsa_platform.tcl` 只看输出里的 `CHECK PASS` 行，它的退出码不能用（见失效条件）。

## 3. 失效条件

- .bd 只存非默认值。7020 的例子：TT_HSI_FPGA 构建时 source 的 `ps7_cfg.tcl` 有 139 项，由它建出的 .bd 只存 83 项。少掉的 56 项是分频系数、PLL、DDR 时序这类由 Vivado 按用户设置重新算出的派生值。所以抽取结果不是逐项复刻，只能用第 3 步的初始化代码对比证明等价。
- `*_ACT_FREQMHZ` 是 Vivado 算出的实际频率，改任何时钟都会连带变化；`--diff` 会把这类项标成"派生"。
- 改 PL 时钟会重新规划共用的 PLL，改动不只落在 PL 时钟寄存器上。本项目 PL0 从 150 MHz 改到 100 MHz 后，RPLL 以及挂在 RPLL 上的 IOU_SWITCH、DP 音频 / STC、PL1 的分频都跟着变了（见第 4 段）。这些是否影响你的外设，要自己判断。
- 厂商 .bd 的 Vivado 版本与你的不同，vlnv 版本号不同时 `create_bd_cell` 会失败或升级 IP。本项目厂商工程与构建都是 2020.2 的 `zynq_ultra_ps_e:3.3`；厂商教程是 2020.1。
- 块设计里有多个 PS 单元或 PS 在子层级里时，要用 `--cell` 指定（只找顶层单元）。
- `diff_xsa_init.py` 只比 `PSU_Mask_Write` / `EMIT_MASKWRITE` 序列，不比 `mask_poll`、延时、SERDES 校准函数的控制流；两个 XSA 的 PS 类型不同时直接报错。
- xsct.bat 的退出码恒为 0：platform generate 失败、脚本 `error` 都不改退出码。自动化时要 grep `CHECK PASS`。
- PS 配置对不对，最终以上板为准（DDR 能跑内存测试、串口有输出）；这里的检查全在 PC 上。

## 4. 已验证效果

全部是 PC 上的工具输出，不含板上结果。

| 算例 | 步骤 | 结果 |
|---|---|---|
| 本项目：ALINX AXU5EV-E 出厂 `factory_vivado` 的 .bd | 1 | 1013 项；与 C1 用旧脚本抽出、已入库的 `build/vivado/psu_cfg_factory.tcl` 逐行相同（1017 行，只有首行注释里的脚本名不同） |
| 本项目：出厂 .bd vs `build/vivado/tt_zu5ev` 的 .bd | 2 | 15 项不同，全部来自 5 项覆盖：PL0 100 MHz、HP0/HP1（SAXIGP2/3）128→64 位、关 EMIO GPIO、关 UART1，再加上它们连带的 4 个 ACT_FREQMHZ 与派生列表 PROTECTION__SLAVES（UART1 条目 1 → 0，另少了 FPD_GPV、CCI_GPV 两个条目，原因未查明） |
| 本项目：出厂 `top.xsa` vs `build/vivado/tt_zu5ev.xsa` | 3 | 756 / 751 次写，9 个差异块：RPLL 重规划（RPLL_CFG / CTRL / TO_FPD、IOU_SWITCH、PL0 / PL1、DP 音频 / STC 分频）、UART1 的时钟 / 复位位 / 4 个寄存器消失、AFIFM2/3 读写宽度。DDR、MIO 寄存器写完全相同 |
| 本项目外：`D:\TT_HSI_FPGA` 的 7020 `tt_soc` .bd | 1 | 自动识别 `processing_system7:5.5`，83 项；与该工程 source 的 `ps7_cfg.tcl` 共有项中只有 HP2 / HP3 使能不同，正是 `build_tt_soc.tcl` 里有意的覆盖 |
| 本项目外：`D:\FPGAlearn\pose6d_fpga` 的 `conv_soc_cam` .bd | 1 | 162 项 |
| 本项目外：7020 `tt_soc` vs `tt_soc_fm64_wt32_df_norm`（同 PS、不同 PL） | 2、3 | .bd 差 2 项（HP0/HP1 位宽，默认 → 64）；`ps7_init.c` 432 次写，0 个差异块（阳性对照：只改 PL 和 HP 位宽不动初始化代码） |
| 出厂 `top.xsa`（无自定义 IP） | 4 | `CHECK PASS` |
| 本项目外：7020 `tt_soc.xsa` 原件 | 4 | `xtucker_proj.h` 的驱动 Makefile `Error 2`，无 `CHECK PASS`（xsct 退出码仍为 0） |
| 同一 XSA 的副本经 `fix_xsa_driver_makefile.py`（去掉 3 行） | 4 | `CHECK PASS`，`xtucker_proj.h` / `xtucker_proj_hw.h` 生成 |
| 同上，要求不存在的驱动 `xnonexistent*.h` | 4 | `CHECK FAIL: no driver header matching` |

## 5. 提炼来源

- `report/llm_log/2026-09-23_c1_zu5ev_platform.md`：C1 用 grep 抓 .bd 里的 PSU 参数抓不全（多行 JSON 对象），改成解析 JSON，1013 项全抽；出厂配置原样 source 再覆盖 5 项；XSA 修驱动 Makefile；XSCT 临时平台自检。对应本项目 `tools/extract_psu_cfg.py`、`tools/check_xsa_platform.tcl`、`tools/fix_xsa_driver_makefile.py`，本技能包是它们的通用化（自动找 PS 单元、支持 7000、加对比与初始化代码核对、驱动名可配）。
- `report/llm_log/2026-09-28_skill_factory_psu_extract.md`：本技能包的通用化与验证记录。
- 对应 pitfalls：`[继承] HLS 导出的驱动 Makefile 含 "TAB+#echo" 行，Windows make 报错`、`[2026-09-23] XSCT app build 的编译输出不进 stdout，失败也不报错`、`[继承] 厂商教程基于 2020.1，我们用 2020.2`。
