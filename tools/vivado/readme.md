# tools/vivado + tools/vitis —— 在本机打开 Vivado / Vitis 工程

工具安装位置：`D:\AMD\<版本>`（本机是 `D:\AMD\2026.1`）：

| 工具 | 可执行文件 |
|---|---|
| Vivado | `D:\AMD\2026.1\Vivado\bin\vivado.bat` |
| Vitis（统一 IDE / Python 批处理） | `D:\AMD\2026.1\Vitis\bin\vitis.bat` |
| Vitis HLS | `D:\AMD\2026.1\Vitis\bin\vitis-run.bat` |

脚本会在 `D:\AMD` 下**按版本号从新到旧自动查找**，所以升级到 2026.2 之类不需要改脚本；
装在别处时用 `TT_AMD_ROOT`（指向 `D:\AMD` 这一层）或 `TT_VIVADO_ROOT` / `TT_VITIS_ROOT`
（直接指向 `...\Vivado` / `...\Vitis`）覆盖。

## Vivado

仓库里的工程是 2020.2 建的，而且记录的是车规器件 `xazu5ev-sfvc784-1-i`
（本机器件库里没有）；实物板卡是 XCZU5EV-2SFVC784I，对应 `xczu5ev-sfvc784-2-i`。

另外本机 Xilinx 许可证文件里同时有 `ALVEO` 与 `BASIC` 两层，Vivado 默认挑 ALVEO，
结果只认 Alveo 板卡，打开工程会报 `Specified part could not be found`。

| 文件 | 作用 |
|---|---|
| `make_basic_license.py` | 从本机 license 里挑出 BASIC 层，写一份副本到 `build/host/lic/vivado_basic.lic`（**不改原文件**） |
| `launch_vivado.bat` | 找 Vivado → 设 `XILINXD_LICENSE_FILE` → 启动；可带一个 `.xpr` 直接打开工程 |
| `prepare_project_copy.ps1` | 把 `build/vivado/<名字>` 复制到 `build/host/vivado2026/<名字>`，升级到 2026.1 并把器件改成 `xczu5ev-sfvc784-2-i`（原件不动） |

```powershell
# 打开已经准备好的工程副本（推荐）
tools\vivado\launch_vivado.bat "build\host\vivado2026\tt_zu5ev\tt_zu5ev.xpr"

# 重新做一份副本（例如换工程或换器件）
pwsh -File tools\vivado\prepare_project_copy.ps1 -Name tt_m2_zu5ev -Force

# 手工验证许可证层（Vivado Tcl Console）
get_parts -quiet *zu5ev*      # 应列出 26 个 ZU5EV 器件
```

说明：

- 副本只保留 BASIC 层，不影响 Alveo 使用：不设 `XILINXD_LICENSE_FILE`、直接开 Vivado 就是 ALVEO 层。
- `build/host/` 已在 `.gitignore` 里，工程副本和许可证副本都不会进仓库。
- 已验证：四份副本都能在 2026.1 打开（`open_project` 成功、器件为 `xczu5ev-sfvc784-2-i`）；
  综合/实现/生成比特流的耗时以实际运行结果为准。

## Vitis

```powershell
tools\vitis\open_workspace.bat M1        # M1 / C3 / M2 / M3A，或直接写工作区目录名
```

等价于 `"%VITIS%" -w D:\HSI_AgriEdge\build\board\chk_m1_20261016b`。

能直接打开的只有 `build/board/*_20261016*` 四个 2026.1 工作区；`vitis\` 与
`build/host/gcs_r1_abi4_vitis\` 是 2020.2 建的经典工作区，2026.1 的 IDE 打不开，只能看源码。
