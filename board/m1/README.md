# board/m1：ZU5EV M1 基线（PLAN §17 C2）

## 2026-10-16 Vitis 2026.1 构建入口（迁移后）

```powershell
$ws = 'D:/HSI_AgriEdge/build/board/chk_m1_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/check_xsa_platform.py D:/HSI_AgriEdge/build/vivado/tt_zu5ev.xsa $ws
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/build_zu5ev_app.py $ws tt_bench_zu5ev m1
```

- 等价于旧 `tools/check_xsa_platform.tcl` + `tools/build_zu5ev_app.tcl`（2020.2，保留为参考）。
- 检查平台名 `chk_plat`；ELF 留在 `$ws/tt_bench_zu5ev/`，不自动覆盖 `board/m1/`。
- 脚本会从构建日志核对必需 flags（-O2 / -mcpu=cortex-a53 / -ffp-contract=off），并扫描
  应用源告警（0 告警才 BUILD PASS）。
- 本轮构建结果（2026-10-16）：平台 `build/board/chk_m1_20261016b/chk_plat` 生成通过
  （tucker_proj_v1_4 驱动源码就位于 hw_artifacts/drivers）；`tt_bench_zu5ev`（m1）BUILD PASS、
  0 告警（`tt_bench_zu5ev.elf`）。HLS 自定义驱动改为应用内导入并补生成 `xtucker_proj_g.c`，
  见 `docs/vitis2026_migration.md` §4.6。


## 2026-10-06 用户真板首测

用户自建 `vitis/test` 平台和 `vitis/test_m1` App，实际运行 `Debug/test_m1.elf`（目录名Debug，编译实际-O2，见 `20261006_first_run/manifest.json`），不是下方板前ELF。模式1完整10次均值23.136ms/误差1.149e-03 PASS；模式3汇总PS356.957/PL23.135ms、15.429×、PS/PL差0，COMPARE PASS；模式5流水17.437ms/像素、顺序23.130、1.326×，10次两patch逐位一致。

原始文本：`20261006_first_run/mode1_user.txt`（含被重新启动打断的前缀，正式统计只取后段10次）、`mode2_user.txt`（完整10次PASS，均值356.782ms，后段profile356.844ms另计）、`mode3_user_excerpt.txt`（仅用户提供后段，未补造缺失内容）、`mode5_user.txt`。报告 `report/perf_m1.md` 已更新；**C2/G-M1 PASS**，无需再测M1。模式3成对加速比仍为15.429×，不混入独立mode2均值；模式4/6未测。下一步PMUFW/风扇核对后C3→D2。

以下为板前产物与复现说明，不代表此次运行的ELF路径。

- `tt_bench_zu5ev.elf`：串口基准程序（`src/ps/`，模式 1/2/3/5，4/6 是 7020 的块推理，未在 ZU5EV 验证）。由 `tools/build_zu5ev_app.tcl` 在 C1 的检查平台（`tools/check_xsa_platform.tcl` 从 `build/vivado/tt_zu5ev.xsa` 生成）上编译：aarch64-none-elf-g++ 9.2，`-O2 -mcpu=cortex-a53 -ffp-contract=off -DTT_HW_RUNTIME_SWITCH`，链接 libm。与在 Vitis IDE 里用同样源码、同样选项 Build 出的 ELF 等价。
- 串口日志：`board_uart_<日期>_<模式>.txt`，115200 8N1，发 ASCII 1 / 2 / 3 / 5。数字进 `report/perf_m1.md`。

## Vitis IDE 建应用（用户做）

1. 平台：File → New → Platform Project，选 `build/vivado/tt_zu5ev.xsa`，处理器 psu_cortexa53_0，standalone，Build。换 IP 版本后删掉平台从 XSA 重建，不用 Update Hardware Specification（pitfalls 继承条目）。
2. 应用：Empty Application (C++)，导入 `src/ps/` 下 17 个文件（`main_benchmark.cpp`、`tt_net.*`、`tt_hw.h`、`tt_hw_sim.cpp`、`tt_hw_xil.cpp`、`tt_hw_switch.*`、`tt_ref_int.h`、`tt_data.*`、`tt_block_app.*`、`tt_block_data.*`、`tt_block_render.*`），不含 `reference/`。`tt_block_data.c` 的 `.incbin` 是绝对路径 `D:/HSI_AgriEdge/model/data/block/region_f32.bin`。
3. C/C++ Build Settings（g++ 与 gcc 两处都设）：Symbols 加 `TT_HW_RUNTIME_SWITCH`；Optimization `-O2`；Miscellaneous 加 `-mcpu=cortex-a53 -ffp-contract=off`；Linker Libraries 加 `m`。
4. Build，Debug 下载，串口发 1、2、3、5，日志贴回。

## 板上先看什么

- 开头 `tt_hw:` 行：不得有 `WARNING unaligned` 或 `ERROR PL buffer above 4 GB`。
- 模式 1 `Warmup PASS`、`max|dlogit|` 量级与主机一致（1e-3）；模式 3 `COMPARE PASS`；模式 5 `PAIR CHECK PASS`。
- A53 cache 清理用 `dc cvac`，PL 输出 invalidate 按 64 字节行，都是板上第一次验证（pitfalls 继承条目"ARM 侧 cache"）。
