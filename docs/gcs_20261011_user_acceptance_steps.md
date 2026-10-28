## 2026-10-12 09:08 当前状态：v7 服务已切换，直接进入用户上板步骤

- **已完成**：用户授权切换；新 PID 13872 在 <http://127.0.0.1:8765> 运行，页面/关键 JS 与冻结 v7 一致，生产门禁 PASS；两条历史任务保留、无加载错误。旧服务已退出，日志和原证据保留。
- **你现在做**：浏览器 **Ctrl+F5** → 在 Vitis 下载并运行 `gcs_r1_abi4_app/Debug/gcs_r1_abi4_app.elf`。**不需要再同步或 Build，先不要开始整图任务**；启动完成后再确认新版身份/连接并逐项验第一轮。
- 新服务初始仍板卡锁定；本次无下载/复位、UART 打开/TX、板卡 UDP、SD 操作或图片读取。物理板卡尚不因此成为新版，不能把换地面站等同已部署固件。
- 运行树为 `C:/Users/86187/.codex/worktrees/3716/HSI_AgriEdge`，不要再当作可随意改动的开发候选树；主树未合入新运行代码。服务启动命令和日志见 `D:/HSI_AgriEdge/build/host/gcs_r1_abi4_user/service_switch_v7_01`；证据 `../report/gcs_roi/20261012_v7_service_switch/review.md`。
- 以下 **08:56 是切换前历史**，其中“等待服务切换许可”已由本条取代；旧 Build/备份/ELF 路径继续有效。

## 2026-10-12 09:06 独立复验补充（不接管部署）

最终v7完整离线119/119命令PASS：46模块/322个Python执行用例、96+48浏览器检查、15个实际BSP A53语法及C++/SD/管道检查；204源码及顶层日志SHA无漂移。旧118项后发布工具发生变更，本次119覆盖最终候选。详 `gcs_20261012_round1_verification.md`。已只读核实另一会话的v7同步、用户Build和新ELF批准，**不要重复同步/Build**；部署仍按 `gcs_20261012_v7_sync_handoff.md` 由原会话协调。09:02原20352/8765仍在，此后以最新回执为准；完整A～G/T实机欠项不缩减。后续不读图、不重复输入未变的验证。

## 2026-10-12 08:56 当前停点：v7 已同步、用户 Build 与 ELF 核验 PASS

**不要再次同步或 Build。** 尚未下载/切服务，下一先取得 v7 地面站切换窗口，再由用户下载运行。详见 [v7 交接](gcs_20261012_v7_sync_handoff.md)。已通过且输入未变的检查不重复，不读图；以下仅保留历史。

# 第一轮用户建平台与逐项验收步骤（2026-10-11）

## 2026-10-11 23:18 当前先确认新批次范围，不继续旧Build/下载步骤

v5已正式批准、用户JTAG和服务切换完成；原task1只是82000前缀后停止，task2无START的预检超时已修为v6本地候选。尚无v6同步/Build/批准，不让用户原样重复Build或点击重连接管已用boot。新步骤与许可边界见`gcs_20261011_v6_acceptance_handoff.md`，其他UI需求见`gcs_20261011_v5_ui_issue_handoff.md`；建议集中后一次新绑定，原全A～G/T仍保留，不能把离线回归当第一轮完成。

## 2026-10-11 21:25 当前请从 v4 专用交接开始，不重做下方历史步骤

用户已完成v4源码同步后的App Build，完整日志/ELF已保留；**尚不能下载**：正式门禁把非加载.debug_info副本计成第二份身份，原FAIL保留。唯一加载态身份已只读核实，但没有批准或服务切换。详细卡点、修复边界及后续逐项验收见 `gcs_20261011_v4_acceptance_handoff.md`。

本轮97/97完整离线门禁、35源/105资产/45本地输入、既有平台与XSA、授权源码同步及14绑定语法均通过。当前不原样重复Build、不再同步v4、不重建平台，不从旧段落重拷初始journal；JTAG不能冒充SD独立启动。新版本工具变更后的再绑定/Build需重新解释并许可。以下17:46及更早记录保留历史，UART命令不是当前以太网必需入口。

## 17:46 当前实机停点：不是继续等待SD，GCS已因BUILD截断停止采集

用户已经JTAG启动：新boot228ce0e9、generation1已在原字出现，初始journal不能再恢复。main.log_line上限160B截断本版242B BUILD行，GCS严格身份解析失败并释放COM6/TX0，未观察READY。证据`report/gcs_roi/20261011_first_boot_identity`；没有改代码/服务、没有代发INFO或重Build。

MODEL_SCAN只读约6.47MiB权重，不加载三个大cube；cube按场景激活读取，同景DDR复用已存在。串口已非身份输入，但仍是当前启动/细分计时取证路径。现有“SD以太网接入”确认要求独立SD启动，当前JTAG不能假确认。下一须用户允许后成组修日志/真实JTAG或SD的以太网接入，再由用户仅Build App一次；平台/HLS/XSA无需重建。PMU-FW警告另待核，所有实机欠项保留。

## 17:30 最新停点：SD已具备JTAG首测配套，直接进入用户操作

45必需文件、保留旧cube_i16及两64B初始journal均已写卡并完成PC回读；journal字段/配对/CRC也通过，原件与安装回执在`build/host/gcs_r1_abi4_user/sd_identity_01`。按本次已授权重建和继续准备要求作为新安装，仅生成/安装一次；板卡使用后不能还原这些初始文件。

用户现在安全弹出F并在断电时插回板卡；继续JTAG流程，GCS先点“连接板卡”再下载运行已通过新平台/v3 ELF，保留BUILD、SD IDENTITY、READY原字。先不跑整景，不再Build/同步，不重启已有8765服务。当前不要求BOOT.BIN；它和真正SD独立启动仍属于后续F验收。全部A～G/T必需实机不删、不提前置PASS。

## 17:20 历史停点：SD容量和模型/数据就绪，身份与实机仍待

用户明确改为授权助手处理本张SD，并允许用已核电脑原件替代旧卡不可读的cube_f32。现F为单active MBR/FAT32（0x0C、HSI_SD），卷29.110GiB、余27.924GiB、Windows Healthy/OK；45必需文件1150149380B已复制且PC大小/SHA/CRC回读全PASS，额外保留匹配旧cube_i16。旧第一分区镜像和4个可读文件备份保留，原FAIL也保留，见`gcs_20261011_sd_capacity_handoff.md`顶部及`../report/gcs_roi/20261011_sd_prepare/review.md`。

**下一先确认这张重建卡作为新安装介质，再生成一次本地双journal；当前boot/jrn0.bin、boot/jrn1.bin和BOOT.BIN仍不存在。** 不恢复/覆盖已用身份，不把PC复制/回读当板端冷扫或持久化通过。用户下载/启动模式/上下电及全部A～G/T实机按下方矩阵继续，全部通过才第二轮。GCS35444/8765保持空闲锁定，ELF/XSA/发布身份未变，不再Build/同步；本轮备份与改盘进程均已退出。

以下16:30及更早条目作为历史保留；其中“未备份/未改盘/未复制45文件”和“改盘仅用户执行”已由本轮明确授权及实际回执更新，不外推其他权限。

## 16:30 最新停点：SD小分区已查明，用户要求交接

用户已给F盘。只读确认F FAT32卷0.992GiB，整盘报告29.119GiB，另有28.072GiB无盘符分区（0x83，文件系统/内容未识别），无大块未分配空间；F HealthStatus Warning。当前容量不能放完整45文件1.15GB。未备份SD、未改盘/修复/写卡/provision。**停止在备份/容量方案确认前，不自动删分区或格式化。** 恢复先读`gcs_20261011_sd_capacity_handoff.md`，重新核F实际映射，再由用户决定方案；软件/新GCS已就绪，不再Build或重复起服务。

## 16:10 历史停点：新版地面站已切换，待核SD

用户已同意窗口，新GCS在127.0.0.1:8765运行（最后观察PID35444，恢复须重新核）；旧38476已停止且旧任务/串口原字已备份。默认板卡锁定、UART TX0、无UDP owner、GET/首页200，尚未连接板卡。**不再重复切服务、同步源码或Build**。

SD卡先由用户安全断电后取出接电脑，告知实际盘符；助手只读对照，不写卡、不格式化、不删旧数据：
- 必需持久身份：根目录`boot/jrn0.bin`、`boot/jrn1.bin`，各64B。当前尚未生成/检查实卡，确认新安装后才生成本地初始记录，已用journal禁止覆盖/恢复。
- 模型/数据：`scenes/longkou`、`scenes/honghu`、`scenes/hanchuan`，完整45文件/1150149380B，清单`build/host/gcs_r1_abi4_user/sd_required_layout_v3.txt`；卡上匹配文件无需重拷。PC本地核验不证明卡上已有。
- JTAG首测不需先制作BOOT.BIN；真正SD独立启动时再用本次XSA/bit、同平台FSBL/PMUFW和批准ELF生成新BOOT.BIN，由用户写卡。不得沿用旧镜像充当新系统。

## 15:48 历史停点：新ELF已正式通过，待服务窗口与SD准备

用户v3 Build及正式ELF门禁、生产入口只读门禁均PASS；当前ELF SHA `a41bbdad9ce05d27dfcda817442b8ec37affe3d510598c0bcc04cd1c336e4d66`，批准文件`build/host/gcs_r1_abi4_release_v3/approved_elf.json`。**不再同步/改参数/Build**。下一先获得8765旧服务切换窗口许可，再确认实际SD双槽身份及配套文件；用户负责下载/写卡/启动，尚未实际接入或板测。没有本轮SD provision回执，不据此推断物理卡内容，更不能覆盖已有journal。下方§3～§7实机流程继续适用。

## 15:46 历史停点：刷新已完成，待用户Build

新绑定包已按本轮许可刷新到现有新App：34源/14新BSP语法PASS，旧ELF/15个构建产物已备份并保留，配置/链接脚本/平台未改。**不要再次同步或改参数**。用户选中`gcs_r1_abi4_app`按F5，选择Debug并Build Project；只Build App，不重建平台/HLS/XSA。助手自动查找完整日志，冻结后用v3包正式审查ELF；此之前不下载/接入。回执`source_refresh_v3_01`，当前仍无新发布approved_elf.json。

## 15:38 历史准备步骤（当前状态以上方15:46为准）

用户新平台、首次34源同步及首次App Build已经完成；**不要重新创建平台或重跑首次同步**。首次ELF因验收器的空Debug lastBuildOptions/旧DP符号要求停止，严格修正后33回归及真实只读检查通过；但工具属于release资产，必须更新绑定身份，不能拿旧ELF直接注册。

- 最新候选：`build/host/gcs_r1_abi4_release_v3`；release `ed01ef29a3e36893dc87ef342e27e325d906b9ef98a3e26dce5e6448d4824e0c`，34源/103资产。
- 原包 `gcs_r1_abi4_release`、首个ELF与v2失败候选均保留；App尚未再次同步。现有源码/配置/链接脚本正确，**不需重设参数或改.prj**。
- 当次确认自动Build关闭及允许刷新后，助手使用新同步器（先完整ZIP备份，保留旧ELF/对象）：

  ```powershell
  D:/pytorch/python.exe -X utf8 -B tools/gcs_release_platform.py --platform-log build/host/gcs_r1_abi4_user/platform_review_01/platform_build.log --out build/host/gcs_r1_abi4_user/source_refresh_v3_01 --sync --auto-build-off --refresh-from build/host/gcs_r1_abi4_release
  ```

  此命令**已于15:46执行通过，不重复运行**。只允许3验收工具资产修正、固件/XSA/数据不变且唯一内容变化为绑定头；参数漂移、非空新增构建选项、额外用户源码均拒绝。复制完整34源使用户下一次Build产生14条完整编译记录，旧ELF保留但不是新发布的可用ELF。
- 刷新PASS后用户在新App按F5，选择Debug并Build App；无需Clean/Build平台。助手自动定位完整App日志并冻结，再按新包做ELF审查，正式PASS前不下载/接入。
- 平台原完整日志已冻结到 `build/host/gcs_r1_abi4_user/platform_review_01/platform_build.log`；自动日志在workspace的 `.metadata/.plugins/org.eclipse.cdt.ui/`。不用用户手填路径或为补日志重Build。
- 证据与失败说明：`../report/gcs_roi/20261011_user_platform/review.md`。所有SD、服务切换、训练及A～G/T实机步骤继续适用，尚未开始。

## 0. 当前停点与权限

以下原创建流程保留作复现参考；当前进展以上方15:38停点为准。新平台及首次App已经由用户Build，但当前尚无正式批准的新版ELF、没有新版实机验收，第一轮未完成。

- 用户亲自：创建/Build 新平台（含 BSP、FSBL、PMUFW）、创建/Build App、下载、写卡、启动模式、上下电、实机操作。Codex 不运行平台生成脚本。
- Codex：只读核验，得到当次“自动 Build 已关闭”的确认后可按新同步器同步**本任务新 App 的源码**；不改用户旧工程/项目配置，不 Build，不下载。
- 真实训练须用户显式发起；具体故障注入方案先确认。禁止直接使用旧24源 prepare/sync/audit。
- 旧 HTTP 38476/8765 保留，Python 未加载新版，`bb6bd8e3` 禁复用。最终服务切换要另约窗口；刷新静态页面不等于升级后台。
- 无 goal、无 token 预算。用户已要求第一轮全部验收通过后再进入第二轮；未通过前不启动 USB、提速优化或旧 P2。

### 本次交付定位

| 内容 | 路径/身份 |
|---|---|
| 新硬件 XSA | `build/vivado/tt_gcs_r1_abi4_zu5ev.xsa`，3,376,874 B |
| XSA SHA256 | `bc7dfb43856d2ce2fddbd727aedc91daa091cec7ac7b8f64f6ea7773f8a2d380` |
| 完整源包 | `build/host/gcs_r1_abi4_release/`，App ID `gcs_r1_abi4` |
| release_id | `b01ce7b5a6efcc2ad402612a920341f9f2745428b3eac45f32c1613a79cbc3a2` |
| 包 manifest SHA256 | `a8bba61defbc22a0eaa4d3cff117ba91d1c4ff55106c9b6cc3b469a8f1a4faf6` |
| 完整验收范围 | `docs/gcs_20261011_acceptance_matrix.md`（A～G/T，不能删项） |
| 本轮报告/原回执 | `report/gcs_roi/20261011_round1_xsa_ready/`；`build/host/gcs_round1_20261011_continue/` |

本地源包包含34源、103配套文件与45数据文件清单。45数据文件共1,150,149,380 B只核验本地来源，**没有复制到SD、没有生成BOOT.BIN**。包中 `app_src/roi_release.h` 已绑定本次源码/XSA；仓库同名文件是故意不能启动的 UNBOUND 模板，不能绕过源包直接导入。

## 1. 用户创建新平台（下一对话先做这一段）

1. 打开 Vitis 2020.2。建议选新的独立 workspace：`D:/HSI_AgriEdge/build/host/gcs_r1_abi4_vitis`。不要升级/覆盖 `vitis/s1b_m3a_plat` 或旧 App。若想用别的路径/名字，先在新对话说清楚，核对工具映射后再同步，不自行套用命令默认值。
2. **先关闭 Project → Build Automatically**，防止导入部分源时自动 Build。此状态需在真正同步前再次确认。
3. File → New → Platform Project，名称 `gcs_r1_abi4_plat`，选择上表新 XSA；目标 `psu_cortexa53_0`、64-bit A53、`standalone`、域 `standalone_domain`。需要 SD 启动的 FSBL/PMUFW，应在这个新平台生成，不能借用旧 ELF。
4. 平台 BSP 按以下既有业务配置核对，不引入新 BSP 补丁：

   | 项目 | 必需值 |
   |---|---|
   | standalone | 7.3；stdin/stdout 均 `psu_uart_0` |
   | xilffs | 4.4，`use_lfn=1` |
   | lwip211 | 1.3，RAW_API，DHCP关闭 |
   | PHY | `CONFIG_LINKSPEED1000`，沿用原厂源码；板上 KSZ9031 地址1 |
   | 收/发描述符 | `n_rx_descriptors=256`、`n_tx_descriptors=256` |
   | pbuf / mem | `pbuf_pool_size=2048`、`mem_size=524288` |
   | DP/DPDMA | `psu_dp → dppsu 1.3`、`psu_dpdma → dpdma 1.3` |
   | 新引擎驱动 | `tt_engine_0 → tt_engine 4.0`，CTRL `0x80000000` |

   Vitis 2020.2 的 GUI 驱动表可能不可用/不反映最终设置，**不反复要求找不到的表**。内置XSCT Console跟随当前IDE workspace，**不执行setws**（本轮真实报Command not supported from XSCT console in SDK，已纠正）。由用户执行 `platform active gcs_r1_abi4_plat`、`domain active standalone_domain`、`bsp setdriver -ip psu_dp -driver dppsu -ver 1.3`，DPDMA同样绑定dpdma 1.3，再regenerate/Build。以生成的 `.mss`、`xdppsu.h` 和库为准；不由Codex执行平台生成脚本。
5. **用户 Build 平台**，保存完整 Console 到新文件，例如 `build/host/gcs_r1_abi4_user/platform_build.log`。出现 ERROR 就停，不创建替代库、不清失败日志。
6. 把实际 workspace、平台名、日志路径告知新对话。Codex 只读核：导入/导出 XSA SHA、新驱动寄存器、BSP与原profile差异、DP头/库、PHY源码、FSBL/PMUFW来源。默认路径命令：

   ```powershell
   D:/pytorch/python.exe -B tools/gcs_release_platform.py --platform-log build/host/gcs_r1_abi4_user/platform_build.log --out build/host/gcs_r1_abi4_user/platform_review_01
   ```

**通过判据**：`USER_PLATFORM_READ_ONLY_PASS_NOT_SYNCED_OR_APP_BUILD`。此命令尚未对真实新平台运行；工具候选测试不能替代本步。失败时保留平台/日志，请新对话定位实际差异，不自动更换旧 XSA。

## 2. 用户建空 App → 核验 → 统一同步 → 用户 Build

1. 用户在该新平台创建 `gcs_r1_abi4_app`，Empty Application (C++)，A53 / `standalone_domain`；保持自动 Build 关闭。不要导入旧 boot_id.cpp/旧24源或“Hello World”源码。
2. 用户设置 Debug 配置：`-O2 -std=c++14 -mcpu=cortex-a53 -ffp-contract=off -ffunction-sections -fdata-sections -Wall -Wextra -Werror`；链接 `m`，增加 `-Wl,--gc-sections -Wl,-Map=gcs_r1_abi4_app.map`。禁 `-Ofast`/`-ffast-math`。
3. 用户核对低DDR链接脚本与包内 `host_assets/vitis/s2c_roi_app/src/lscript.ld` 一致。若新模板不同，先给新对话看差异；不要静默改栈/堆/内存分区。项目配置由用户维护。
4. 用户明确回复“新 App 已创建，自动 Build 已关闭，可以同步”。Codex 才可运行下面新工具（只写34源，不改项目配置）：

   ```powershell
   D:/pytorch/python.exe -B tools/gcs_release_platform.py --platform-log build/host/gcs_r1_abi4_user/platform_build.log --out build/host/gcs_r1_abi4_user/source_sync_01 --sync --auto-build-off
   ```

   它先备份新空 App，核对无已Build App/原有用户源码，再复制全部34源并用**新BSP**作14入口语法检查。若部分写入后失败，不自动回滚或再次覆盖，保留备份/当前差异后定位。
5. 只有 `SYNC_ALL_SOURCES_PASS_NOT_APP_BUILD_NOT_BOARD` 后，**用户 Build App**。保存完整逐源编译和链接输出为 `app_build.log`；不能只保留“Build Finished”。本次第一次完整 Build 应覆盖14个`.cpp`。
6. Codex 对用户 ELF 做只读审查，不重新链接：

   ```powershell
   D:/pytorch/python.exe -B tools/gcs_release_elf.py --build-log build/host/gcs_r1_abi4_user/app_build.log --out build/host/gcs_r1_abi4_user/elf_review_01 --register
   ```

**通过判据**：`ELF_CANDIDATE_PASS`；核绑定release/source/XSA、全部源和编译参数、低DDR、cube/4槽/模型暂存/注意力DMA/DP互不重叠及必要符号。`approved_elf.json`是后续连接门禁，不是下载或板测通过。实际新平台/ELF未生成，本审查工具的真实目标布局仍须本步验证，不能为过门禁删必要符号/缩小缓冲要求。

## 3. 约定服务切换窗口和首次新启动

1. 新对话先只读核旧HTTP进程、8765端口和GET `/api/state`；确认旧任务完成、UART released、无旧UDP owner。不得用历史PID杀进程。
2. 用户明确同意切换窗口后，保留旧服务日志/任务记录，才停旧服务并启动已审查候选；不同时起两个8765服务。GET/刷新应保持被动，无串口/UDP/START。默认板卡，不出现PC推理回填。
3. JTAG下载及冷启动由用户操作；只用新XSA对应bit和审查后的新ELF。当前App必须有预置SD双槽身份及配套文件，缺少就拒绝启动，不回退到串口输入。
4. 串口路径：用户显式点击“连接板卡”，**先连接再启动**，保留从`S2C BUILD`、`IDENTITY source=sd-journal`到`READY app=gcs_r1_abi4`的完整原始流，TX必须0。release/source/XSA必须匹配ELF审查。
5. 无串口SD路径：用户完成真实SD启动后点击“SD以太网接入”，确认空闲新启动；只发INFO，ABI4 INFO含release前128位、boot/session/task，拒绝旧boot/错误版本/错误release/非空owner。不能凭INFO认定物理冷启动/SD持久化已验；无UART时内部计时仍缺证据。

## 4. 第一轮A/B/C/E/T联合实机顺序

每个任务都保存实际 boot/session/task、scene/model/tag/CRC、ROI、UART、packets.jsonl、CLASS+seen、summary/CSV和浏览器导出；不要手填固定身份。以下是操作顺序，完整判据仍以矩阵为准。

1. **小ROI/尾批**：LongKou v2从左上5×3和右下1×1开始，验证绝对坐标、≤4尾批、零边输入；非法/越界ROI应拒绝不截短。然后HongHu v1/HanChuan v1各做对应边界小ROI。
2. **控制/连续任务**：选择足够高的ROI，运行中暂停/继续/停止，检查仅完整行边界生效，ACK不等于状态已切换；只保留成功前缀。终态同连接显式新任务，旧结果/身份不覆盖。
3. **补传/恢复/四槽**：记录缺行/ROWREQ和原字；断开/显式恢复须同boot/session/task，INFO→PING/PONG→STATUS，不自动START/RESUME。四槽保留，第五任务只回收最旧。具体断线/损包试验先确认安全方式，不随意拔线/复位或制造DMA故障。
4. **三景显示**：PC中央主图/原配色/图例/缩放/框选保持，切scene/model/history清旧；用户真实目视DP与同任务CLASS一致，包括暂停/停止/新任务清图和9/22/16类图例。离线截图不能代替DP照片/目视记录。
5. **真实注意力**：每景至少左上/中心/右下各自的坐标记录，运行中和终态按约定探查；原LOGITS及两片ATTENTION、432个Q0.24、全CRC/12层CRC、原模型恢复均一致。丢片/冲突/错误时必须清旧，不能补PC重算结果。只做6次同点不算覆盖边角。
6. **计时**：终态读取折叠计时/导出，核TASK_PHASE/TASK_DETAIL/TASK_ENGINE与committed pixels、compute_us一致。PS validate/extract/normalize/embed、driver cache/submit/wait/complete分别核；wait_service是wait子集，PL cycles又是独立计数，禁止重复相加。配置频率199,998,000Hz，名义200MHz分列，不宣称晶振实测频率。
7. **整景/业务**：三景按矩阵完成受影响整景测试。统计只用真实CLASS+seen；台账revision、面积/置信度、HTML/PNG/JSON/CSV/原字与mask一致。固定Test100只从真板预测评估，ROI必须标部分覆盖；未全Test覆盖不称整景成绩。
8. **独立核验**：浏览器“核验任务并下载证据包”不补跑任务；也可用

   ```powershell
   D:/pytorch/python.exe -B tools/gcs_task_verify.py <实际task目录> --uart <实际采集目录/uart.txt> --out <新的核验json>
   ```

   新版必须带采集时保存的`elf_audit.json`；报告的data_acceptance只证明该任务证据，不等于第一轮通过。错误/缺失保持原样，不重跑旧`bb6bd8e3`。

## 5. D：模型、SD持久化与真实训练闭环

1. 核三景cube和对应两种包实际从SD读入，INFO登记不能证明输入/两包持久化；记录启动MODEL_SCAN原字。
2. 用户显式上传候选，保存两包SHA/CRC/checkpoint来源、WBEGIN/CHUNK/COMMIT/ACT事务。两包均持久化，校验续传/重复包/偏移、失败不激活；运行中仍能STOP，切换仅安全终态/下一任务边界。
3. 用户完整关机/上电，真SD冷扫描后再次读CRC/配对；不能使用RAM模拟或DDR缓存代替。模型临时文件、写入/rename/readback失败门禁保留。
4. 真训练必须用户明确发起：旧模型真实ROI任务→官方Train100选点及参数→真实训练日志/checkpoint→新tag配对导出→上传/激活→**相同ROI新板任务**→只在共同真实像素上A/B。不能展示训练参考成绩作为新版板成绩。
5. 模型事务独立核验：`tools/gcs_model_verify.py <实际model目录> --uart <采集目录/uart.txt> --out <新json>`；采集目录保留对应`elf_audit.json`。无UART不会出data_acceptance=true。

## 6. F：真正SD独立启动（用户操作）

1. 用户先确认**新安装介质**和备份，只有新的安装才生成初始journal；绝不覆盖已使用的`boot/jrn0.bin`/`jrn1.bin`，不克隆/恢复旧卡来绕过身份。
2. 本地准备入口 `gcs_boot_provision.py --new-installation --out <新build/host目录>`；这只生成本地初始记录，不写卡。之后用`gcs_boot_bundle.py --help`填入本次审查ELF、同新平台FSBL/PMUFW、XSA、用户平台Build日志、本地数据清单及provision目录。
3. `gcs_boot_bundle.py`依赖真实新版`approved_elf.json`，目前该依赖待用户Build，不提前打包。按输出BIF由用户bootgen、核镜像SHA、选择正确物理卡并写入；不能放进旧平台FSBL/PMUFW。
4. 用户移除调试下载依赖、按板卡手册设SD启动并上下电。观察独立READY/DP/任务入口；UART可RX记录但无输入。保存启动模式、动作记录/照片及原始日志。
5. 再次用户冷启动：nonce同安装，generation前进且boot不重复；用户安全拷出两journal后运行`gcs_sd_boot_verify.py --uart ... --journals ... --previous-uart ... --out ...`。文件关联PASS不证明实际上下电，必须保留用户动作证据。
6. 掉电/坏卡/DMA等具体注入先讨论可恢复介质、停止条件和风险；未经确认不执行。软件不能证明整卡回滚/克隆、或卡声称sync成功但物理未持久化的保证。

## 7. 第一轮关闭与第二轮入口

- A～G/T所有新增/受影响必需项逐条有实机证据；SD冷扫/持久化、安全切换、真实训练后同ROI新任务、PC/DP、注意力和计时不漏。
- 核验原FAIL/缺项未被摘要抹掉，最终包hash/复现入口/llm_log/evidence与双方记忆同步；未获提交授权则仍待提交，不自动push。
- **只有上述全部通过才宣布第一轮完成**。用户已提出随后启动第二轮；届时先总结真实瓶颈、固定基线/范围和授权，再进入第二轮。当前不自动启动USB/提速/旧P2，不将“XSA已出”作为第二轮触发条件。
