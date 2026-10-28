# Vitis/Vivado 2026.1 迁移说明（2026-10-16，随迁移推进更新）

本文件记录 HSI_AgriEdge 从 Vivado/Vitis/Vitis HLS 2020.2 迁移到 AMD 2026.1 工具链
（D:\AMD\2026.1）后的构建环境、脚本变化、已处理问题与剩余阻塞。项目既有证据
（XSA/ELF/manifest/板端日志）保持原样，不因迁移被覆盖。

## 1. 环境与项目位置

- 工具链：`D:\AMD\2026.1`（Vitis 2026.1 / Vivado 2026.1 / Model Composer）。
  - Vivado：`D:\AMD\2026.1\Vivado\bin\vivado.bat`
  - Vitis（Python 批处理）：`D:\AMD\2026.1\Vitis\bin\vitis.bat -s <script.py>`
  - Vitis HLS：`D:\AMD\2026.1\Vitis\bin\vitis-run.bat --mode hls --tcl <script.tcl>`
  - aarch64 编译器：GCC 13.4（`Vitis\gnu\aarch64\nt\aarch64-none\bin`）
- 项目实体：`F:\HSI_AgriEdge`。为兼容历史脚本里的 `D:/HSI_AgriEdge` 引用并提供纯 ASCII
  构建路径，建有两个目录联接（junction）：
  - `D:\HSI_AgriEdge` → `F:\HSI_AgriEdge`（构建主路径）
  - `F:\夸克\FPGA项目\HSI_AgriEdge\HSI_AgriEdge` → `F:\HSI_AgriEdge`（原始浏览路径）
  原始下载包 `F:\夸克\FPGA项目\HSI_AgriEdge.zip` 未动。
- Python（工具脚本）：`D:\Anaconda\python.exe`（3.14，numpy 2.x）。主机 C++ 回归所需
  的 mingw g++ 本机暂缺（待装或以其他方式补齐）。

## 2. 必须遵守：ASCII 构建路径

2026.1 组件在非 ASCII 路径（中文目录）下工作异常：
- HLS：`open_solution` 后报 `command 'set_msg_logfile' returned error code`；junction 指向
  中文目标无效（工具会解析出真实路径）。
- Vitis 客户端：`create_client` 报 `'utf-8' codec can't decode byte 0xd5 ...`（见 4.2）。
因此所有 HLS/Vitis 构建从 `D:\HSI_AgriEdge`（或 `F:\HSI_AgriEdge`）发起。`build/hls/run_*.tcl`
已加非 ASCII 拦截（`string is ascii $ROOT`），报错信息指向本文件。

## 3. 工具链调用变化

| 2020.2 入口 | 2026.1 入口 |
|---|---|
| `D:\xilinx\Vitis_HLS\2020.2\bin\vitis_hls.bat -f x.tcl` | `D:\AMD\2026.1\Vitis\bin\vitis-run.bat --mode hls --tcl x.tcl`（`build/hls/run_*.bat` 已更新，`TT_VITIS_ROOT` 可覆盖工具根） |
| `xsct x.tcl`（平台/应用流程） | Vitis Python API：`vitis -s tools/vitis_py/*.py`（XSCT 在 2026.1 被禁用） |
| `D:\xilinx\Vivado\2020.2\bin\vivado.bat` | `D:\AMD\2026.1\Vivado\bin\vivado.bat`（Vivado 侧构建待许可证，见第 6 节） |

### 3.1 HLS（脚本已迁移，兼容性验证到 set_part 为止）
- `run_variant.tcl` / `run_tt_engine.tcl` / `run_tt_attn.tcl`：逻辑不变（快照、变体表、
  csim/csynth/cosim/export），仅增加 ASCII 路径防护。
- `run_zu5ev_export.bat` / `run_tt_engine.bat` / `run_tt_attn.bat`：改调 `vitis-run`，保留
  日志/`.done`/ERROR 扫描语义；2020.2 命令在注释中保留。
- 已验证：`fm64_wt32_df_norm_zu5ev` 的 csim 正常执行到 `set_part xazu5ev-sfvc784-1-i`，之后
  因许可证停止（open_project/open_solution/add_files 全部正常）。许可解决后可直接重跑。

### 3.2 Vitis 平台与应用（XSCT→Python API，脚本在 tools/vitis_py/）
- `tt_vitis_client.py`：客户端启动修复（4.2）+ lwip220 覆盖仓库准备（4.3）。
- `build_periph_platform.py`（对旧 build_periph_platform.tcl）：periph_plat =
  XSA + xilffs + lwip220 + dppsu，成功打印 `PLAT PASS`。2026.1 差异：
  dppsu 已是默认驱动（不再需要 setdriver）；xilffs 参数带前缀（`XILFFS_use_lfn`）；
  PMUFW 需 `is_pmufw_req=True`；lwip 参数名运行时按后缀匹配设置；KSZ9031 仍定死 1000 Mbps。
- `build_periph_app.py`（对旧 build_periph_app.tcl）：periph 应用，-O2 -mcpu=cortex-a53
  -Wall -Wextra -Werror；ELF 留在工作区，不自动覆盖 `board/periph/`。
- `check_xsa_platform.py` + `build_zu5ev_app.py`：M1/M2 检查平台与 m1/m2/m2chk 应用。
- 旧 `tools/*.tcl` 保留为 2020.2 参考（2026.1 无法运行 XSCT）。

## 4. 2026.1 工具问题与项目内应对

### 4.1 XSCT 被禁用
`xsct.bat` 直接报 "XSCT is disabled in Vitis 2026.1 release"。平台/应用脚本已全部移植。

### 4.2 Vitis Python 客户端在中文用户名/计算机名下启动失败
- 现象：`Vitis Create Client failed, 'utf-8' codec can't decode byte 0xd5 in position 4`。
- 根因：`vitis/_server.py` 启动服务器后逐行读其 stdout 找端口并 `str(line,'utf-8')` 硬解码；
  本机用户名（启航）/计算机名（航の拯救者）使服务器输出含 GBK 字节，解码崩溃。
- 处理：`tt_vitis_client.create_client()` 显式传自选空闲端口（跳过该读取循环）+
  `VITIS_SERVER_START_TIMEOUT=300`（避开超时分支中同样的解码）。已连续两次验证通过。

### 4.3 安装自带 lwip220.yaml 带 UTF-8 BOM，lwip 全库不可用
- 现象：vitis-server 启动日志 `Failed to read ...lwip220_v1_4\data\lwip220.yaml, lwip220
  ... will not be available`；`get_applicable_libs()` 无任何 lwip*。
- 根因：安装的 `lwip220.yaml` 带 BOM（embeddedsw 全库唯一），工具仓库加载器拒绝。
- 处理（不改 AMD 安装）：`tt_vitis_client` 把 lwip220_v1_4 复制到
  `build/board/vendor_patches/embeddedsw_overlay`、去掉副本 BOM，再用
  `client.add_embedded_sw_repo()` 注册为工作区附加仓库；`build_periph_platform.py` 自动执行。
  次序要求（2026-10-16 探针结论）：必须在**创建平台之前**注册覆盖仓库，之后普通
  `set_lib('lwip220')` 即成功（带 path 反而失败；对已建平台的域事后补加无效）。

### 4.4 其他差异
- PMUFW：2020.2 GUI 隐式生成；2026.1 需 `is_pmufw_req=True`。
- 厂商 BSP 告警（dppsu 结构体初始化、xemacps 缺省初始化、xbasic_types.h 弃用）属厂商阶段
  告警，沿用旧口径单独记录，不计入应用的 0 告警。

### 4.5 经典 XPAR 宏与 lwIP 改名兼容层

2026.1 平台改走 SDT，BSP 不再导出经典 XPAR 宏族。构建脚本以 -D 补回旧源码所需
常量（tools/vitis_py/tt_vitis_client.py 的 bsp2026_compat_defines），并在调用点处理
SDT API 的参数语义变化。旧宏值与 2020.2 BSP（periph_formal_20260928）一致，
不表示这些值可直接用于所有新驱动的 LookupConfig：

| 旧宏（2020.2 值） | 2026.1 处理与依据 |
|---|---|
| XPAR_CPU_CORTEXA53_0_CPU_CLK_FREQ_HZ (1066656005) | 定义为 XPAR_CPU_CORE_CLOCK_FREQ_HZ（同值 1066656005，新 xparameters.h） |
| XPAR_SCUGIC_0_DEVICE_ID (0U) | 定义为 0U（新 xparameters_ps.h 只有 XPAR_SCUGIC_SINGLE_DEVICE_ID=0U） |
| XPAR_PSU_DP_DEVICE_ID / XPAR_XDPDMA_0_DEVICE_ID（均 0） | 仅保留旧 DeviceId 常量；dppsu/dpdma 的 SDT LookupConfig 按物理 BaseAddr 匹配，调用必须分别传 XPAR_XDPPSU_0_BASEADDR / XPAR_XDPDMA_0_BASEADDR |
| XPAR_XGPIOPS_0_DEVICE_ID / XPAR_XSYSMONPSU_0_DEVICE_ID（均 0） | 保留旧源码兼容定义；不能由单实例或配置表段推断驱动接受数组索引，具体调用须按对应 SDT 驱动接口核对 |

- **2026-10-17 DP 黑屏修复：** 原迁移版给 DP/DPDMA LookupConfig 传入 0，而实际配置表
  基址为 `0xFD4A0000` / `0xFD4C0000`，两次查询均返回空指针，应用报告 `DP init_rc=1`。
  `roi_display.cpp` 现以 `#ifdef SDT` 选择基址参数，旧工具链分支保留 DeviceId。
  `build_abi4_app.py` 对冻结源码的暂存副本执行同样适配，不改冻结包。
  依据是厂商 `dppsu/src/xdppsu_sinit.c` 与 `dpdma/src/xdpdma_sinit.c` 的 SDT 实现，
  不是配置表数组下标。详见 [本次诊断记录](dp_black_screen_20261017.md)。
- `XAVBuf_CfgInitialize` 在 SDT 下使用两参形式，旧分支保留第三参 DeviceId。
- XPAR_CPU_CORTEXA9_CORE_CLOCK_FREQ_HZ 只在 #if defined(A53) 的备选分支（main_benchmark.cpp:34），A53 宏补回后不触发。
- src/ps/reference/qspi_io.cpp 引用的 XPAR_XQSPIPS_0_DEVICE_ID 在旧 2020.2 BSP 里也不存在（旧为 QSPIPSU），该文件从未参与编译。
- 计时：新 xtimer_config.h 中 COUNTS_PER_SECOND = XSLEEPTIMER_FREQ = XPAR_CPU_TIMESTAMP_CLK_FREQ = 33333000，与旧 XPAR_CPU_CORTEXA53_0_TIMESTAMP_CLK_FREQ 一致，时间换算不变。
- 函数改名：is_tx_space_available → xemacps_is_tx_space_available（lwip220 = lwIP 2.2，netif/xemacpsif.h，签名不变）；periph_net.cpp 按 LWIP_VERSION_MINOR 条件切换，lwip211（2.1）与 lwip220 两代都能编。

### 4.6 HLS 自定义驱动的导入方式（应用内编译）

2026.1 SDT BSP 不再把 XSA 里的 HLS 自定义驱动并入 BSP：bsp.yaml 中 tucker_proj_0 /
tt_engine_0 为 None，bsp/include 与 bsp/libsrc 里都没有驱动头文件，libxil.a 里也没有符号；
驱动源码被放在 bsp/hw_artifacts/drivers/<drv>_v*/src。项目做法（tools/vitis_py/build_zu5ev_app.py
的 stage_hls_driver）：

1. 把 hw_artifacts 里的驱动源暂存到 <ws>/_drvgen（跳过 *_linux.c），导入应用 src 一起编译；
2. 补生成 2026.1 不再生成的 <stem>_g.c 配置表：单实例 { 0, XPAR_<DRV>_0_BASEADDR }；
3. 以 -D 补回驱动源码引用的经典宏：XPAR_XTUCKER_PROJ_NUM_INSTANCES=1、
   XPAR_XTUCKER_PROJ_0_DEVICE_ID=0、
   XPAR_XTUCKER_PROJ_0_S_AXI_CTRL_BASEADDR=XPAR_TUCKER_PROJ_0_BASEADDR（tt_engine 同理
   XPAR_XTT_ENGINE_*）。旧值 0x80000000 与新 xparameters.h 的 XPAR_TUCKER_PROJ_0_BASEADDR 一致。

periph 平台不涉及自定义驱动；check_xsa_platform.py 的平台检查相应改为核对 hw_artifacts
下驱动源码是否就位（不再要求 bsp/include 里有驱动头文件）。

### 4.7 E 正式系统（ABI4）在 2026.1 的重建方式

E（`gcs_r1_abi4_plat` + `gcs_r1_abi4_app`，DP 画面 + 网口）原本只有 2020.2 流程：
用户在 Vitis GUI 建平台、同步 34 源、Build，再由 `tools/gcs_release*.py` 做身份审计与
发布登记（其规则明确"平台由用户创建""工具永不 Build App"）。2026.1 侧的并行重建：

- 脚本：`tools/vitis_py/build_abi4_platform.py`（平台）、`build_abi4_app.py`（应用）。
- 输入一律取冻结发布包 `build/host/gcs_r1_abi4_release_v6`（35 源、已 bound
  `S2C_RELEASE_BOUND 1`、`host_assets/vitis/s2c_roi_app/src/lscript.ld` 低 DDR 链接脚本、
  冻结 XSA；与 `build/vivado/tt_gcs_r1_abi4_zu5ev.xsa` 同 SHA），不读在途工作树，
  不改冻结包字节。
- 暂存副本只做 2026.1 必需适配：`roi_display.cpp` 的 DP/DPDMA LookupConfig 在 SDT 下
  改传物理基址、`XAVBuf_CfgInitialize` 在 SDT 下改为两参（见 §4.5）、`xtime_l.h` 垫片、
  `tt_engine`（ABI4/v4）驱动按 §4.6 导入。显示适配支持重复执行，并拒绝缺失或重复的
  已知调用形状，避免遗漏适配后继续生成黑屏固件。
- 平台差异：2020.2 用 lwip211，2026.1 用 lwip220（同一套 RAW_API/1000M/描述符参数，
  见 §4.3 覆盖仓库）；发布审计链里针对 lwip211 的 BSP 校验只适用于 2020.2 平台。
- 边界：该脚本产出的是 2026.1 开发/验证 ELF，不进入 ABI4 发布审计链（审计要求用户
  GUI Build 的回执与身份字符串登记）；板端部署仍走
  `docs/gcs_20261011_user_acceptance_steps.md` 的原验收流程。结果见
  `report/llm_log/20261016_vitis2026_migration.md`。

## 5. 构建入口速查（2026.1）

```powershell
# HLS（需许可证解决后才能通过 set_part；入口已迁移）
D:\HSI_AgriEdge\build\hls\run_zu5ev_export.bat            # tucker_proj v1.4 → ZU5EV IP
D:\HSI_AgriEdge\build\hls\run_tt_engine.bat synth 7 16    # tt_engine M2（M3a 用 18）
# Vitis 平台与应用（工作区必须是不存在的新目录）
D:\AMD\2026.1\Vitis\bin\vitis.bat -s D:\HSI_AgriEdge\tools\vitis_py\build_periph_platform.py D:\HSI_AgriEdge\build\board\periph_ws_<新名>
D:\AMD\2026.1\Vitis\bin\vitis.bat -s D:\HSI_AgriEdge\tools\vitis_py\build_periph_app.py D:\HSI_AgriEdge\build\board\periph_ws_<新名>
# E 正式系统（ABI4，DP+网口；输入 = 冻结发布包，见 §4.7）
D:\AMD\2026.1\Vitis\bin\vitis.bat -s D:\HSI_AgriEdge\tools\vitis_py\build_abi4_platform.py D:\HSI_AgriEdge\build\board\abi4_ws_<新名>
D:\AMD\2026.1\Vitis\bin\vitis.bat -s D:\HSI_AgriEdge\tools\vitis_py\build_abi4_app.py D:\HSI_AgriEdge\build\board\abi4_ws_<新名>
```

## 6. 许可证阻塞（Vivado 与 HLS 全流程）

现状（2026-10-16）：D:/AMD/2026.1 装的是 Vivado ML **Enterprise**，本机没有任何许可证，
因此 vivado.bat 拒绝启动、Vitis HLS 的 set_part 全部件失败（含 xc7z020）。Vitis（软件侧）
不受影响，平台/应用构建已全部走通。

决策（用户 2026-10-16）：安装免费版 Vivado ML **Standard**。注意：Standard 是**永久免费、
无需许可证文件**（不是 60 天试用）；"60 天"指 Enterprise 的免费评估许可证，会过期，不适合
比赛周期。Standard 覆盖 Zynq UltraScale+（含本项目的 xczu5ev），Vitis HLS 综合在其许可范围内。

操作（需用户手动执行，GUI 安装器需要 AMD 账号登录）：
1. 运行 D:/AMD/.xinstall/2026.1/xsetup.exe（2026.1 统一安装器仍在磁盘上，无需重新下载）；
2. 选 "Add Design Tools or Devices"（添加设计工具/器件）；
3. 勾选 Vivado ML **Standard**（Vitis 保持不动；若安装器弹出选择版本，直接选 Standard）；
4. 完成后验证：vivado.bat -mode batch 能正常启动、不再要求许可证。

之后（迁移侧脚本已就绪，无需再改代码）：
- HLS：build/hls/run_*.bat 已迁到 vitis-run --mode hls --tcl，可跑 csynth/export 并重导 IP/XSA 验证；
- Vivado：build/vivado 下各工程 tcl（如 build_m2_zu5ev.tcl）用 vivado.bat -mode batch -source 调用。

若 Standard 对本板 xczu5ev 覆盖有问题（装好后第一次 HLS set_part 即可实测判定），
备用方案是申请 AMD 官网的 Enterprise 评估许可证临时解锁（不推荐长期使用）。

## 7. 迁移期间证据

- 关键运行日志（探针/构建）：`build/board/_migrate_logs/`（仓库内，git 忽略）。
  原迁移工作区 `F:\夸克\FPGA项目\_migrate_scratch` 已于 2026-10-17 被清理；其要点均已落入
  本文件、`.claude/pitfalls.md`、`.claude/progress.md` 与 llm_log，无内容损失；原先计划的
  `build/board/vitis2026_migration_20261016/` 归档不再需要。
- 平台探针工作区：`build/board/periph_probe_*`（平台构建通过，platform.build()=0）。
- 新脚本沿用 2020.2 的成功标记：`PLAT PASS` / `BUILD PASS` / `CHECK PASS`。
