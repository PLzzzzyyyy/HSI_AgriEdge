# C3 外设上板准备

## 2026-10-16 Vitis 2026.1 构建入口（迁移后）

periph_plat 构建已从 XSCT/tcl 迁移到 Vitis Python API（XSCT 在 2026.1 被禁用）。
在仓库根执行（构建路径必须 ASCII，见 `docs/vitis2026_migration.md`）：

```powershell
$ws = 'D:/HSI_AgriEdge/build/board/periph_ws_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/build_periph_platform.py $ws
# 确认 PLAT PASS 后再执行应用阶段
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/build_periph_app.py $ws
& D:/Anaconda/python.exe tools/test_periph_pc.py
```

- 平台 `periph_plat`（xilffs + lwip220 + dppsu）；工作区脚本拒绝已存在目录；ELF 留在
  `$ws/periph_zu5ev/`，不自动覆盖 `board/periph/` 下载副本。
- 2026.1 差异（dppsu 默认驱动、`XILFFS_use_lfn`、lwip220 覆盖仓库、PMUFW `is_pmufw_req=True`）与
  许可证状态见 `docs/vitis2026_migration.md`。
- 旧 XSCT/tcl 入口（`tools/build_periph_platform.tcl`、`build_periph_app.tcl`）保留为 2020.2 参考。
- 本机 2026-10-16 复跑：`tools/test_periph_pc.py` 8 项 OK、`tools/test_periph_build.py` 5 项 OK
  （后者仍测旧 tcl 逻辑）；`periph_pc.py crc` 需 SD 场景文件（E:/scenes），本机缺。
- 本轮构建结果（2026-10-16）：平台 PLAT PASS（`build/board/periph_ws_20261016`：xilffs+lwip220+
  dppsu、FSBL/PMUFW、XPFM 齐全）；应用 BUILD PASS、0 告警（`periph_zu5ev.elf`）。XPAR 兼容宏、
  lwIP 2.2 函数改名、XAVBuf 新签名三处修复见 `docs/vitis2026_migration.md` §4.5。


## 当前状态（2026-09-28，正式构建验收完成）

**当前源码正式构建通过，仍未上板。** 在新工作区从 XSA 生成 FSBL、PMUFW 和 BSP，再经 XSCT 创建/构建应用；使用其生成的 Release Makefile 强制重编 6 个源码文件，`-Wall -Wextra -Werror -O2 -mcpu=cortex-a53`，编译/链接 0 warning。

## 最终下载 ELF 与平台配对

- 下载 ELF：`board/periph/periph_zu5ev.elf`，已包含 UDP 去重修复；1937960 字节。
- SHA256：`7b7d2c1ac47bebeaa485775563c8c5a0b7c19c77c91877f7df2fe34ea92990d0`。
- 同字节构建原件：`build/board/periph_formal_20260928/periph_zu5ev/Release/periph_zu5ev.elf`。
- 对应 XSA：`build/vivado/tt_zu5ev.xsa`，SHA256 `1fbcf068ca6577d2d0b21da417e21d360e893802562a3e6a45a8fd0c524f13bd`。**不要配 M2 XSA/bitstream。**
- 已验证工作区：`build/board/periph_formal_20260928/`；平台 `periph_plat`，处理器 `psu_cortexa53_0`，standalone。
- 配套文件均在工作区：`periph_plat/hw/tt_zu5ev.bit`、`periph_plat/hw/psu_init.tcl`、`periph_plat/export/periph_plat/periph_plat.xpfm`、`periph_plat/export/periph_plat/sw/periph_plat/boot/fsbl.elf`。bitstream 和初始化脚本已与 XSA 内文件逐字节核对。
- 6 个导入源码与头文件均与仓库相同；ELF 为 AArch64，加载段结束于 `0x21215080`，位于链接脚本的低 DDR 范围内。
- 完整源码、平台、BSP 库、ELF 与日志哈希见 [build_manifest_20260928.json](build_manifest_20260928.json)。这是构建证据，不是板上验收记录。
- 13:55 旧 ELF 已先备份到 `build/board/periph_legacy_20260928_1355.elf`（SHA256 `d2ffe071b7f56708b50b77a7ae416f77cf962157ef27404353b066f9e832a511`），再更新下载副本；旧版不能代表当前源码。

## 构建证据与告警边界

- 平台日志：`build/board/periph_formal_20260928_platform.log`，PLAT PASS，178 秒。
- XSCT 应用日志：`build/board/periph_formal_20260928_app.log`，BUILD PASS，36.9 秒（含生成 Makefile 的强制全量复编）。
- 完整编译/链接日志：`build/board/periph_formal_20260928/periph_zu5ev/application_build.log`，UTF-8，6 次编译、1 次链接；0 application warning。
- 厂商阶段仍有 7 条编译告警：PMUFW unused parameter 4 条，xilfpga 指针/整数比较 1 条，lwIP/xemacps 可能未初始化 2 条；应用创建外层有 1 条 Hsi 61-9 模板提示。未消除或隐藏这些告警，**不称全流程零告警**。
- Vitis 2020.2 `app build` 返回空值，不能扫描其返回值声称零告警。修复后的脚本先调用 XSCT 构建，再以 Vitis make 对生成的 Makefile 执行 `-B all`，检查退出状态和实际日志；不自动覆盖下载副本。
- 原 `periph_ws` 的启动/恢复停滞底层原因仍未确认；本轮通过新工作区恢复正式构建，不删除或宣称修好了旧工作区。

## 可复现入口

在仓库根执行，`$ws` 每次使用尚不存在的新目录；不要将已验收工作区删掉重跑：

```powershell
$ws = 'D:/HSI_AgriEdge/build/board/periph_rebuild_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
& D:/xilinx/Vitis/2020.2/bin/xsct.bat D:/HSI_AgriEdge/tools/build_periph_platform.tcl $ws
# 确认 PLAT PASS 后再执行应用阶段；xsct.bat 退出码不能替代成功标记。
& D:/xilinx/Vitis/2020.2/bin/xsct.bat D:/HSI_AgriEdge/tools/build_periph_app.tcl $ws
& D:/pytorch/python.exe tools/test_periph_build.py
& D:/pytorch/python.exe tools/test_periph_pc.py
& D:/pytorch/python.exe tools/periph_pc.py crc
```

平台脚本拒绝覆盖已有目录；应用脚本会重建指定工作区中的 `periph_zu5ev`，只用于专用生成目录。新 ELF 留在 `$ws/periph_zu5ev/Release/`；核对 BUILD PASS、完整日志与源码/平台配套后，再手动更新下载副本和哈希清单，脚本不会自动覆盖它。

## Vitis 打开与上板

1. Vitis 2020.2 打开 `D:/HSI_AgriEdge/build/board/periph_formal_20260928`，不要同时用两个 IDE 打开。应有 `periph_plat`、`periph_zu5ev`；若未显示，导入此目录里的现有工程，不重建平台。
2. 使用 `periph_plat` 的硬件/初始化文件和 `periph_zu5ev/Release/periph_zu5ev.elf`，或上面同哈希的下载副本；配置 A53 #0、系统复位、PS 初始化及对应 bitstream。
3. 尚未建立/验证真板 Debug launch、JTAG 下载或运行；不能只下 ELF 而跳过必要的 PS/DDR 初始化。
4. 按 [../CHECKLIST.md](../CHECKLIST.md) 执行 C2 → C3 → D2。C3 首次逐项运行，不直接发 `a`。C3 UDP 是外设测试协议，不是地面站协议 v1。

本轮 5 项构建脚本回归、8 项 PC mock 回归、5 个本地 SD 文件 CRC 均已复跑通过，不证明板上驱动或 UDP 吞吐。下一步由用户完成 SD、UDP、DP、SYSMON、按键/LED 五项真板取证，串口/JSON/照片按日期存放。

## 历史与版本

- B 原源码/脚本/清单已提交 `3839f20`；本轮构建验收修复与资料收尾的本地提交用 `git log -1 -- tools/test_periph_build.py` 定位，不 push。2026-09-29 已再次核验28项manifest记录及导入源码，产物未变，三平台不上电核对见 [检查清单 §0.1](../CHECKLIST.md)。
- 原独立验证目录 `build/board/periph_verify_20260928_164506/`（ELF SHA256 `226BE2C663257F9121C11639910A4FB16F029BB955A9A3F2B3E637CDDB20BE58`）及 `periph_verify/` 只保留为历史。旧独立脚本混合编码日志问题不属于本轮正式构建结果，新应用日志为 UTF-8。
- 带日期的协作记录：[2026-09-28_c3_formal_build.md](../../report/llm_log/2026-09-28_c3_formal_build.md)。
