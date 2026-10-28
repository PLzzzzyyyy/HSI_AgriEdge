> **版本替代：以下为关闭版历史清单。** 2026-10-10当前联网源码已接通，用户13:49新版Build及ELF审查通过。
> 用[联网版首次运行清单](s2b_connected_build_run.md)，不用再Build；不按旧“不输入身份/门禁关闭”指引操作。
> 旧检查器/manifest仅适用历史提交，本轮不重跑/不自动重锁；设备/实际输入/在线仍另授权。

# S2b 上板前集成与用户手动检查清单

2026-10-10，基线 `01462f4a9d17b69206708568ac24dcb990a14cae`。
**本轮交付是仓库内集成准备，不是 App Build／板端验收。身份与网络均关闭。**

最新结果：用户已完成关闭版App Build，日志/ELF只读审查通过；[本次证据](../report/system_s2b/20261010_user_app_build/review.md)。
**本版不必重复Build或为补map重建。** 现有ELF布局已核，但门禁false优化掉的初始化路径不算未来开门版链接验证；未运行/联网。

后续更新：用户已新建 `s2b_idle_app` 并确认没有自动Build，授权Codex放入7源码、由用户自行Build。
7文件已放好，配置/lscript未改；实际O2/lwip4已具备，不需要重复添加库。
**当前直接操作按[源码放置报告](../report/system_s2b/20261010_app_source_placement/review.md)执行**；Codex没有Build，设备/身份/网络权限不变。

## 1. 现在能执行的唯一集成入口

在仓库根目录 PowerShell：

```powershell
& D:\pytorch\python.exe -B tools/check_s2b_integration.py --record
$LASTEXITCODE
```

也可使用 Python 3.9+；不需要第三方包。脚本由自身位置定位仓库，与当前目录无关。
不加 `--record` 只向 stdout 输出 JSON，不写文件；加上后仅在新建的
`build/host/s2b_integration_<UTC时间>/receipt.json` 写回执，不覆盖旧文件。
退出码 **0=静态预检 PASS，1=检查 FAIL，2=参数或读写错误**。本次使用 Python 3.12。

入口：[`check_s2b_integration.py`](../tools/check_s2b_integration.py)，
锁定清单：[`s2b_integration_manifest.json`](../tools/s2b_integration_manifest.json)。
它只读取固定白名单的7份源码、5份历史证据锚及自己的清单/脚本，并列出私有App目录顶层源文件名；
不打开 `vitis/`、BSP、用户工程，不启动子进程/编译器、旧测试、终端、串口、设备、服务或网络。

**PASS 的含义**：7文件逐字节SHA、4编译单元/3头文件平铺映射、include清单与本地依赖闭合、
门禁与启动顺序、默认关闭测试宏、历史证据锚/源码版本一致。include核对覆盖源码各条件分支，
不是预处理、语法检查、实际BSP头解析或链接；正则也不是通用C++解析器，任意源码变更由SHA锁拒绝。
BSP历史配置只引用原归档，不宣称当前工作区BSP未变。所有路径/哈希均为可审查的版本锁，不是签名防篡改系统。

**FAIL 就停**：保留完整JSON，报告失败项；不要自动改锁、补依赖、重跑已通过套件或操作工程。
锁采用历史实测工作树的原字节SHA，换行转换也会FAIL；先核差异及原始证据，不为绿灯统一换行。
后续生产源码若变化，只补受影响验证，审查证据后更新锁；不能把旧主机PASS覆盖到新版本。

本轮新增检查器测试复现（不是旧C++测试）：

```powershell
& D:\pytorch\python.exe -B sim/host/test_s2b_integration.py
```

已经通过的 boot_id 102例与日志308场景只做证据/版本关联，没有重跑。
完整本轮回执与差异范围见[集成准备报告](../report/system_s2b/20261010_integration_prep/review.md)。

## 2. 授权矩阵——集中确认，不把预检绿灯当许可

| 后续动作 | 当前状态与边界 | 到哪一步必须停 |
|---|---|---|
| 本仓库静态集成核对 | 本轮授权，已完成；无真实BSP/工具/设备动作 | 交付回执与清单 |
| 新建独立 App + 离线 App Build | 用户已创建App并明确自行Build；7源已由Codex放入，Codex不代Build；两个门禁保持关闭 | Build完提交日志/ELF/map等回执，先审查，不Run |
| BSP/公共接口/平台改动 | **不在本轮范围**，原BSP和公共接口保留 | 编译发现不匹配先报，不绕过保护/重建平台 |
| 当前门禁版首次冷启动/下载/设备接入 | **另授权**，与Build许可分开；必须明确匹配的PS初始化与平台产物 | 仅观察门禁停车，不输入身份、不联网验收 |
| 生产身份接通 + 带外约定落地 | **另授权**；PC CSPRNG→人工UART0来源路线及r1契约已批准，不重复选型 | 未授权不生成身份、不取数、不注入，不用常量/计时器顶替 |
| 网络放行/UDP/PING/PC网卡或防火墙操作 | **另授权**；身份接通不自动授权网络；IP/MAC沿用、不重验C3 | 未放行不启动客户端、服务或gcs适配 |

不包含Build/打包/下载/设备/UDP的一键流程；脚本没有 `--build`、工程路径或接通门禁选项。
若要把身份接通、网络放行、真实首次运行合并为后续一轮，先明确一次性授权与停止点；
当前门禁清单不能直接用于该版本验收。

## 3. 用户手动 Build（用户已明确自行Build，Codex只放入源码）

### A. 创建前

- [ ] 保存已有工具/工程状态，保留原IDE/XSCT/hw_server、`s1b_roi_app`、`test_c3`、平台；不在原App内替换文件。
- [ ] 控制自动Build后，新建**独立** `s2b_idle_app`，Vitis **2020.2**，**Empty Application (C++)**。
- [ ] 选择已有 `s1b_m3a_plat` → `psu_cortexa53_0` → `standalone_domain` **应用域**。不是FSBL域，不选其他处理器/平台、lwIP echo模板。
- [ ] 向导若要求更新平台、BSP regenerate、实际平台编译或未知硬件配对，停止报告，不借新App许可扩大范围。
- [ ] 对照本次预检JSON/锁定清单确认源版本。没有配置/源码变化则沿用已通过回执，不机械重跑。

### B. 7文件映射（后续已按用户授权放入，不必重复复制）

| 仓库来源 | 新App文件 | 属性 |
|---|---|---|
| `src/ps/s2b_idle_app/main.cpp` | `src/main.cpp` | 唯一入口，身份/网络顺序门禁 |
| `src/ps/s2b_idle_app/boot_id.cpp` | `src/boot_id.cpp` | 生产恒false，候选休眠 |
| `src/ps/s2b_idle_app/boot_id.h` | `src/boot_id.h` | 既有私有签名不变 |
| `src/ps/net/idle_lwip.cpp` | `src/idle_lwip.cpp` | 既有S2a适配，不改公共接口 |
| `src/ps/net/idle_lwip.h` | `src/idle_lwip.h` | 既有头 |
| `src/ps/net/idle_protocol.cpp` | `src/idle_protocol.cpp` | 既有空闲协议子集 |
| `src/ps/net/idle_protocol.h` | `src/idle_protocol.h` | 既有头 |

- [ ] 使用复制，不建指向旧工程的可写链接；按锁定清单逐文件SHA核对副本。
- [ ] 恰好4个 `.cpp`、3个 `.h`，不导入整个目录、`sim/host/`、`platform.c`、C3/ROI/旧driver/模型/DP/旧对象。
- [ ] **不要定义** `S2B_BOOT_ID_HOST_TEST` 或 `S2B_LOG_HOST_TEST`；默认0。不要用编译宏伪造 `__aarch64__` 或绕过 `#error/static_assert`。
- [ ] 保留 `acquire_boot_id` 恒false和 `kLabNetworkConfirmed=false`；这不是Build前必须打开的开关。

### C. 编译、库和链接布局

- [ ] G++计划选项：`-std=c++11 -O2 -mcpu=cortex-a53 -Wall -Wextra -Werror`；保留Vitis启动/ABI与平台include设置。
  **本次未验证这组A53编译/链接选项**。旧主机g++15.2/C++14通过不等价于Vitis2020.2通过。
- [ ] 平台自动导出的应用域include/lib优先。历史路径为
  `vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/{bspinclude/include,bsplib/lib}`。
  由用户检查实际Build命令，不由本轮工具读取目录。
- [ ] 添加 **lwip4**，保留 `xil/gcc/c` 和C++默认支持；用默认链接group/正确引用顺序，不额外链接 `xilffs/dppsu` 或旧App对象。
- [ ] 不在App重定义 `NO_SYS/LWIP_*`。历史BSP：raw IPv4/UDP、`NO_SYS=1`、`NO_SYS_NO_TIMERS=1`、`LWIP_TIMERS=0`，
  TCP/IP重组仍开启，由main单主循环维护ARP/IP重组/TCP；强制1000；GEM3别名 `0xFF0E0000`、UART0 stdout。
  这些只是既有审查依据；当前BSP未重新读取。如不一致先停，不改BSP或新加ISR定时器。
- [ ] 使用**新App自己生成**的 `lscript.ld`，代码/数据/栈/堆/BD相关段低DDR `psu_ddr_0_MEM_0`，不复制S1b大型数值布局，不用高DDR/OCM。
- [ ] 历史模板主栈/堆默认均 `0x2000`，先保留但不能宣称运行足够；既有 `MEM_SIZE=524288`/pbuf池不改。
  用实际ELF/map核段地址/大小与目标DDR范围、重叠/溢出；本轮不虚填地址范围或余量。

### D. Build一次，回执审查后即停

- [ ] **仅Build新App**，不Run/Debug/Program FPGA/打包/下载；不要Clean或重建平台。
- [ ] 保存本次完整G++与链接命令/日志，不以旧Console或平台 `Nothing to build` 代替新App4单元的实际记录。
- [ ] 保存 ELF、map、`lscript.ld`，7份副本SHA，实际使用的应用域BSP头/库SHA和配置截图/文本。
- [ ] 验收：目标AArch64、正确域、4单元且一个main、无测试宏/对象混入、lwip4符号解析、低DDR布局及无新增未解释警告。
  默认门禁下某些休眠代码可能未保留，不能凭ELF存在证明候选被执行。
- [ ] 原平台7条历史warning不因新App成功消失。出现实际平台编译、公共接口需求或链接异常，保存首份日志后停止，报最小修正范围。
- [ ] 此步结果最多是 **APP_BUILD_ONLY**，不是输入源/熵、冷启动、GEM/PHY/UDP或长稳PASS。

回执填表（尚无实测）：

| 字段 | 用户实际回执 |
|---|---|
| 授权范围/时间；基线提交与预检回执 | 待填 |
| Vitis版本、App/平台/处理器/域 | 待填 |
| 4单元G++命令、链接命令及日志路径 | 待填 |
| ELF/map/lscript与7源/BSP头库SHA | 待填 |
| 新警告、实际平台任务、链接/段布局审查结论 | 待填 |

## 4. 当前门禁版首次运行（只列未来操作清单，本轮未执行）

前提：上述Build回执已审查，用户另授权设备/下载与门禁版冷启动，确认匹配PS初始化和平台产物。
P2仍暂停，不能借这份清单换用未批准的P2/r9产物。不得热接管正在运行的C3/ROI或有未完成DMA的系统；
热复位、重跑ELF、PC/终端重连不是已支持的新冷启动。

- [ ] 用户按另批准的板级流程完成独立冷启动；不在此清单提供自动下载/注入命令。
- [ ] 仅监听已批准的UART0终端，**不敲回车/粘贴身份**，不运行PING/gcs/C3UT客户端、不更改网卡/防火墙。
- [ ] 当前 `main` 首先尝试打印横幅，随后在 `acquire_boot_id` 恒false处分支到永久停车。
  若日志完整，可见：

```text
S2B PREPARATION ONLY: idle v1 subset; no board acceptance
S2B STOP: boot_id provider NOT CONNECTED; GEM/lwIP/UDP not initialized
```

- [ ] 本版本**不应出现** `S2B BOOT_ID: 8 hex digits...` 提示、network-release STOP或 `S2B UDP PCB bound...`。
  出现说明实际运行版本/控制流不符合当前交付，停止并留证，不顺势输入或联网。
- [ ] 日志是最多96字节/调用的尽力输出，STOP整段上限107字节；可能丢失/截断。
  无日志不证明停车或成功，不在同启动重试、不循环Run/Debug；保存原始串口字节、时间及启动步骤后报告。
- [ ] 当前main自己的停车会禁中断并永久循环；两个门禁之前不调用GIC/GEM/lwIP/UDP初始化、不取XTime或读RX。
  这是源级顺序，不是对CRT/BSP启动或真实线路活动的测量保证。整个App没有60s启动保证。
- [ ] 得到符合当前门禁的现象也只记录 **GATE_ONLY_OBSERVATION**，不称S2b联网验收或完整v1；收集回执后停止。

若未来另授权接通身份，需单独版本与受影响验证：r1严格8hex+LF/CRLF、失败锁闩、不改out/成功缓存、
共用60s预算、64残留/74总读上限等契约保留，但它们不验证PC熵、新鲜性、防重放或绝不碰撞。
`XTime_GetTime` 在现有EL3条件下可能启用计时器；设备授权须覆盖该副作用；MMIO/停钟/BSP内部阻塞仍无硬实时保证。
网络仍必须单独放行，不能仅因身份成功而调用网络初始化。

## 5. 任何阶段的停止与不扩展范围

- 哈希/源文件/域/配置不符：停在本阶段，保留原件/首份失败日志；不补造PASS、不擅自重锁或重建。
- 身份失败/版本异常/终端异常：同启动不重试，不临时改常量，不接其他App。设备恢复方法另确认，不直接下复位命令。
- 任意LOAD_W/FULL超时：不读、不复用、不free DMA，永久停车；外部PL复位后重启的原约定保留。
- C3/IP-MAC成功保留：板 `192.168.1.10/24`、网关 `192.168.1.1`、MAC `00:0a:35:00:01:02`；不重复地址确认，不保证未来无冲突。
  PC地址不固定；未来合法PING来源决定回包目的地。`tools/periph_pc.py` 发C3UT，不是S2a v1客户端，不能借用。
- S1c/S2a不重跑；原5×3有限验收、成功前缀、补卡不追溯，dump/OA/性能/长稳未覆盖、NaN未测/PHY未观测/非完整v1保持。
- P2暂停/G2旧OOC FAIL保留。沿用原分工，不改gcs/旧driver/数值/公共接口/BSP，不接ROI/START/ROW/补传/权重/M2/DP/双缓冲/多核，不修S3。
