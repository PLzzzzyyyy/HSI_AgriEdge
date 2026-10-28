# board/m2：ZU5EV M2（tt_engine PROJ 模式替换 v1.4，PLAN §17 D2）

## 2026-10-16 Vitis 2026.1 构建入口（迁移后）

```powershell
$ws = 'D:/HSI_AgriEdge/build/board/chk_m2_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/check_xsa_platform.py D:/HSI_AgriEdge/build/vivado/tt_m2_zu5ev.xsa $ws psu_cortexa53_0 tt_engine
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/build_zu5ev_app.py $ws tt_m2_zu5ev m2
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/build_zu5ev_app.py $ws tt_m2_zu5ev_chk m2chk
```

- 平台检查对应旧 `tools/check_xsa_platform.tcl ... tt_engine`；两个 App 对应旧
  `build/vivado/run_m2_app.bat` 的两次 `build_zu5ev_app.tcl` 调用（2020.2，保留为参考）。
- ELF 留在 `$ws/`，不自动覆盖 `board/m2/`；flags 与 0 告警门禁同 m1。
- 本轮构建结果（2026-10-16）：平台 `build/board/chk_m2_20261016b/chk_plat` 生成通过（tt_engine_v2_0
  驱动源码就位）；`tt_m2_zu5ev`（m2）与 `tt_m2_zu5ev_chk`（m2chk）均 BUILD PASS、0 告警。
  HLS 驱动应用内导入 + `xtt_engine_g.c` 补生成见 `docs/vitis2026_migration.md` §4.6。


板上数字只来自用户的串口输出。日志放本目录 `board_uart_<日期>_<模式>.txt`，数字进 `report/perf_m2.md`（上板后建）。

## 2026-10-07 正式3完整复测已补齐

用户独立复测正式3：PS357.136/PL15.774ms、22.640×、差0，两组各10次全PASS，完整应用测试段见 `20261007_acceptance/mode3_repeat_user.txt`。不含FSBL；首轮15.776ms及独立流水/自检记录保留，不混算。G-M2 PASS，无需再重跑，下一步D4a。

## 2026-10-07 真板验收已通过

G-M2 PASS：正式3均值15.776ms、PS/PL差0；正式5流水10.876ms/像素、两patch十次逐位一致；自检累计288调用零mismatch。原始片段/配置/哈希见 `20261007_acceptance/manifest.json`，范围与实际编译选项差异见 `../../report/perf_m2.md`。不再要求重跑；SYSMON仍暂缓FAIL。下面步骤作为复现入口，不代表待测。

## 2026-10-07 当前手工上板入口（优先于下方历史工作区说明）

M1 和 C3 SD/UDP/DP/KEY-LED 已通过，不重跑；SYSMON 暂缓且保留 FAIL。用户负责 Vitis Build 和下载，不重跑 HLS/Vivado，不修改既有 test/c3_plat。

1. 在当前 `D:/HSI_AgriEdge/vitis` 工作区新建 `m2_plat`。XSA 选 `D:/HSI_AgriEdge/build/board/vitis_sources_20261006_ready/tt_m2_zu5ev/tt_m2_zu5ev.xsa`；A53 `psu_cortexa53_0`、standalone、64 位；生成 boot components。这是不同硬件的独立平台，不是重建 M1/C3。
2. 应用 standalone 域 stdin/stdout=`psu_uart_0`；不添加 lwIP/xilffs/DP 库。FSBL 域保留默认依赖，尤其不要复制 C3 的 lwIP/use_lfn=1。用户 Build 平台，核对 FSBL/PMUFW 生成及应用 BSP 含 `xtt_engine.h`。
3. 新建 `test_m2`，选择 m2_plat 的 A53 standalone 域、Empty Application (C++)。File System 导入包内 `tt_m2_zu5ev/m2/src/` 全部内容到 App/src，不嵌套 src/src。包含 region_f32.bin；保留自动生成的 lscript.ld，不导入 M1 的 tt_hw_xil.cpp。
4. 当前配置（Debug 或 Release）的 GCC/G++ 均加 Symbol `TT_HW_RUNTIME_SWITCH`；优化 `-O2`，其他选项 `-mcpu=cortex-a53 -Wall -Wextra -Werror -ffp-contract=off`。g++ Linker Libraries 加 `m`，保留默认库。链接段放 `psu_ddr_0_MEM_0`，低于 4GB。导入文件不会自动应用 settings.json。
5. 用户只 Build test_m2，查看真实编译命令确认以上参数与 m2_plat include 路径，不以 Debug 文件夹名判断优化。若失败保留首个错误，不扩大内存或替换其他平台头文件。
6. 新建 test_m2 专用的 Single Application Debug/Run 配置，A53 #0、当前 test_m2 ELF、m2_plat 的 bitstream 和启动组件；按 M2 平台完成系统复位和 PS 初始化。沿用已成功的 FSBL 启动方式，但所有启动文件换成 M2 平台配套文件；不要混用其他平台的 PS init 或将 PMUFW ELF 指向 A53。检查 ELF/bitstream 路径，串口115200 8N1，用户下载运行。
7. 正式版只跑菜单 `3`、`5`。保存启动到返回菜单的完整串口；必须有 tt_eng 权重装载、COMPARE PASS/PS-PL差0、PAIR CHECK PASS。模式3包含同轮纯PS对照，不是重跑旧M1验收。模式1可选，不必重复计时。
8. 同一 m2_plat 再建 `test_m2_chk`，导入包内 `m2_selfcheck/src/`，选项与正式版相同，另加 Symbol `TT_ENG_SELFCHECK`（GCC/G++）。独立 Build/下载此 App，菜单 `1`；所有 selfcheck mismatch 为0。自检计时不用于性能结论。
9. 原始日志交回后再判 G-M2：数值通过且性能比已存 M1 改善。M1单patch23.136ms、双patch流水17.437ms/像素；单次延迟与流水吞吐分别比较。先不开始 M3 平台构建。

导入包核查：本次核验 M2 子目录全部 manifest 项的字节数/SHA256，并比对其 source_sha256 与当前仓库来源；未重新编译或上板。后续源码变更须同步用户 App；旧导入包不自动更新。

## 这一版是什么

- PL：`tt_engine`（`src/hls/tt_engine.cpp`，`TT_DB = 16`，`TT_K3 = 7`），PROJ 模式：48 个投影的因子一次装进片上（LOAD_W），之后每次调用给层号 + 投影掩码，做"token 归一化 + 投影"。数值与 v1.4 逐位相同。PL0 = 200 MHz。
- PS：与 M1 同一份 `main_benchmark.cpp` / `tt_net.cpp`，只把 PL 后端 `tt_hw_xil.cpp` 换成 `src/ps/tt_hw_engine.cpp`（同名 `tt_pl_*` 符号）。驱动按权重指针相对已装载权重的偏移算层号，`tt_net.cpp` 不改。
- 平台：`build/vivado/tt_m2_zu5ev.xsa`（不入库，`build/vivado/build_m2_zu5ev.tcl` 重建，约 40 分钟）。与 M1 平台同一套 PSU / 连线（CTRL → HPM0_LPD，FM → HP0，WT → HP1），IP 单元名 `tt_engine_0`。
- 两个 ELF（`tools/build_zu5ev_app.tcl` 在检查平台上编，aarch64-none-elf-g++ 9.2，0 warning）：
  - `tt_m2_zu5ev.elf`：正式版，模式 1 / 3 / 5 计时用它。
  - `tt_m2_zu5ev_chk.elf`：加 `-DTT_ENG_SELFCHECK`，每次 PL 调用后用纯 PS 逐位实现重算，逐元素比对 q / k / v / mlp / stats，每次完整前向打印一行累计结果。只用来查"逐层逐位"，它的计时没有意义。

## 上板前已有的证据（都不是板上数字）

| 项 | 结果 | 来源 |
|---|---|---|
| HLS csim / cosim（12 层 QKV + MLP、n_patch = 3 批、错误码） | 对 `sim/golden/n6_real` 逐位 PASS | `build/hls/optimization_build/tt_engine_k7_{synth,cosim}.log`（09-27，当前源码） |
| cosim 拍数 | LOAD_W 119,538；QKV 一次 62,406；MLP 一次 27,918；一次前向 PL 合计 1,083,888 拍 ≈ 5.42 ms @200 MHz | `tt_engine_k7/sol/sim/report/verilog/result.transaction.rpt` |
| Vivado 系统级实现 | PL0 199.998 MHz，WNS +0.023 ns（满足，余量很薄）；LUT 43,200（36.9%）、FF 53,630、BRAM 63.5 / 144、URAM 14、DSP 530 | `build/vivado/impl_m2_zu5ev_{utilization,timing}.rpt` |
| 驱动主机测试（驱动 + HLS C 模型，32 位地址，异步 start / wait） | 12 层逐段、tt_forward、tt_forward_pair、PS ↔ PL 切换、单投影、非法调用拒绝，全部对 n6_real 逐位 PASS | `sim/host/test_hw_engine.cpp`（编译命令在文件头） |
| XSCT 平台 + 应用编译 | 平台生成、`xtt_engine` 驱动在 BSP 里；两个 ELF 0 warning | `build/vivado/chk_m2_zu5ev.log`、`app_m2*_zu5ev.log` |

## 复用已有 Vitis 工程（09-28 接手核查）

**可以复用，不必先手动重建；尚未连板验证下载。**

1. 用 Vitis 2020.2 的 File → Switch Workspace → Other 打开 `D:/HSI_AgriEdge/build/vivado/chk_m2_zu5ev`，不要两个 IDE 同时打开。已有 `chk_plat`、`tt_m2_zu5ev`、`tt_m2_zu5ev_chk` 和对应 system 工程。若未显示，用 Import → Existing Projects into Workspace 导入已有工程，不复制回原目录。
2. 已核实存在：`chk_plat/export/chk_plat/chk_plat.xpfm`、`chk_plat/hw/tt_m2_zu5ev.bit`、`chk_plat/hw/psu_init.tcl`、`chk_plat/export/chk_plat/sw/chk_plat/boot/fsbl.elf`，以及应用工程元数据、链接脚本、Release ELF 和 `_ide/psinit/psu_init.tcl`。
3. 首次仍需建立/核对 Debug Configurations → Single Application Debug（界面以 2020.2 为准）：A53 #0、对应 Release ELF、Program FPGA 使用 **M2 bitstream**，系统复位与 PS 初始化配置来自本 M2 平台。不能沿用 M1/C3 的 bitstream，不能只下 ELF 跳过 DDR/PS 初始化。
4. 本次未找到保存的 `.launch`，未验证 JTAG、拨码、初始化执行或真实下载。如工作区不能恢复，按下节新建即可，不必重跑 Vivado。

不要为打开工程重跑 `check_xsa_platform.tcl`：它会删除传入的输出目录再重建，可能清掉后来保存的 Debug 配置。

告警说明：应用外层日志有 `WARNING: [Hsi 61-9]`（模板 MSS 被忽略），平台另有厂商库告警。原交接称应用源码 0 warning，但外层日志未保留完整编译输出，本次未独立复核，不能称整个构建无 WARNING。下节手动新建是备用方案。

## Vitis IDE 建平台与应用（用户做）

1. 平台：File → New → Platform Project，XSA 选 `build/vivado/tt_m2_zu5ev.xsa`，处理器 psu_cortexa53_0，standalone，Build。**新建平台**，不要在 M1 平台上 Update Hardware Specification（pitfalls 继承条目）。
2. 应用：Empty Application (C++)，导入 `src/ps/` 下这些文件：`main_benchmark.cpp`、`tt_net.cpp/.h`、`tt_hw.h`、`tt_hw_sim.cpp`、**`tt_hw_engine.cpp/.h`**、`tt_hw_switch.cpp/.h`、`tt_ref_int.h`、`tt_data.c/.h`、`tt_block_app.cpp/.h`、`tt_block_data.c/.h`、`tt_block_render.cpp/.h`，再加 **`src/hls/tt_engine_regs.h`**。**不要**导入 `tt_hw_xil.cpp`（与 `tt_hw_engine.cpp` 符号重复，而且 M2 平台里没有 `xtucker_proj.h`）。
3. C/C++ Build Settings（g++ 与 gcc 两处都设），与 M1 相同：Symbols 加 `TT_HW_RUNTIME_SWITCH`；`-O2`；Miscellaneous 加 `-mcpu=cortex-a53 -ffp-contract=off`；Linker Libraries 加 `m`。
4. 逐层检查版：同一个应用再加 Symbol `TT_ENG_SELFCHECK` 另 Build 一次（对应本目录的 `tt_m2_zu5ev_chk.elf`）。
5. SW1 拨 JTAG，PS_UART 115200 8N1，Debug 下载。本目录的两个 ELF 是同样源码、同样选项在检查平台上编的，用于对照，不必直接下载。

## 串口顺序与看什么

先正式版 `tt_m2_zu5ev.elf`：

1. 发 **3**（先纯 PS 再 PL，同一 patch、同一计时边界）。
   - 切到 PL 时出现一行 `tt_eng: weights loaded (48 projections, ncls 9), engine contract v3, M2 int16`；整个过程不得出现 `tt_eng: ERROR`。
   - 两组都 `Warmup PASS`；最后 `COMPARE PASS`，其中 `PS-only vs PS+PL max|dlogit|` **应为 0.000e+00**（M2 与纯 PS 参考逐位相同；不是 0 就是没过）。
   - 串口开头那行 banner 仍写 "PL normalize+projection v1.4"，是 `main_benchmark.cpp` 的固定文字，M2 下不改；以 `tt_eng:` 行为准。
   - 记下 PS+PL 的 mean / median ms、分段表（PL qkv / PL mlp 两栏含驱动与 cache 开销）。
2. 发 **5**：`PAIR CHECK PASS`（顺序 / 双 patch 流水逐位一致）与 `PAIR BENCH` 的两个 ms/像素。
3. 发 **1**：可选，与 3 里的 PS+PL 组相同，多一组计时。

再换 `tt_m2_zu5ev_chk.elf`，发 **1**：每次前向后一行 `tt_eng selfcheck: <n> calls, 0 mismatching calls, 0 mismatching values -> PASS`（预热 + 10 次 + 分段各一次，n 依次 24、48 …）；任何 `selfcheck: layer L mask M mismatches ...` 行都是逐层不一致，把整段日志贴回。

## PASS 条件（G-M2 的板上部分）

- 正式版：`tt_eng:` 无 ERROR；`COMPARE PASS` 且 PS / PL max|dlogit| = 0；`PAIR CHECK PASS`。
- 检查版：所有 selfcheck 行 0 mismatching。
- ms/像素比已验收的 M1 改善：单patch23.136ms、双patch流水17.437ms/像素（report/perf_m1.md）。不重跑M1；正式版单次与流水分别比较，自检版不计性能。
- 预期（不是结果）：PL 部分每 patch ≈ 5.4 ms（cosim 拍数折算），外加 PS 胶水与 cache 维护；M2 只换投影、不减 PS 那条腿，双 patch 流水时 PS 与 PL 较慢的一边决定 ms/像素。

## 失败时先查

- `tt_eng: ERROR LOAD_W returned ...`：err = 8 是权重包头不对（驱动拼包的 magic / 位宽），version 不是 3 是 IP 与 `tt_engine_regs.h` 不配套——平台是不是用 `tt_m2_zu5ev.xsa` 新建的。
- `tt_eng: ERROR call rejected ...`：驱动没认出权重指针（应用改过 `TTNet.weights` 却没调 `tt_eng_load_weights`），或者 N ≠ 6。
- `tt_eng: ERROR PL buffers must be 8-byte aligned and below 4 GB`：链接脚本把缓冲放到了高地址。
- 卡死不返回：`XTt_engine_IsDone` 一直 0。先用检查版看是不是第一次调用就卡，再用 XSCT `mrd` 读 CTRL 寄存器（地址见平台 `xparameters.h` 的 `XPAR_TT_ENGINE_0_S_AXI_CTRL_BASEADDR`，偏移见 `xtt_engine_hw.h`）。
