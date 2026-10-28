> **最新2026-10-10：用户基础通信冒烟已通过，40/40 PONG、41 STATUS，身份e86a03b1匹配。**
> 独立客户端`tools/s2b_ping_smoke.py`已提供；[用户证据与边界](../../../report/system_s2b/20261010_udp_smoke/review.md)。
> 不重复Build/本次成功测试；下一另授权业务闭环。下文“下一上板/尚无板测”为此前交接状态，历史保留。

# S2b 联网源码 r1：用户新版Build通过，下一另授权上板

2026-10-10，起点4a602e3。生产provider复用原r1，网络源码开关true；**身份失败仍在网络初始化前永久停车**。
PC CSPRNG→人工UART0来源/带外契约已批准并落地；5新增生产入口主机PASS，r1主体/日志/net/公共接口/UDP不变。
已同步现有App两cpp，7源匹配、配置/lscript保留。用户13:49增量Build通过，0error/0warning、2note；新ELF provider非stub，网络初始化已链接、低DDR。
**无需再Build。** [首次运行清单/已用Build参数](../../../docs/s2b_connected_build_run.md)、[新Build/ELF证据](../../../report/system_s2b/20261010_connected_source/review.md)。
设备/实际取数输入/在线运行仍另授权；尚无板测。先通信闭环，完整业务链路后续另接，不修S3；原限制/P2/G2/分工保持。
旧关闭版检查器/manifest/boot-log入口保留历史，不用于接通版，不自动重跑/重锁。新差异复现tools/test_s2b_connected.py（已过不重复）。

---
以下全部为**关闭版历史**，其中“当前/下一/门禁未开”不是本版本指引；旧13:30 ELF已由用户13:49新Build替换，历史证据不抹去。

# 历史：S2b 独立空闲 App：上板前集成准备完成，两个门禁仍关闭

2026-10-10，起点 `01462f4`。**用户关闭门禁版App已Build/链接成功，仍未运行**；身份/网络不接通。
最新：用户已按参数完成4单元严格AArch64编译/链接，0error/0warning、3pragma note；ELF低DDR、provider恒false。
见[Build回执](../../../report/system_s2b/20261010_user_app_build/review.md)。不需重复Build；部分休眠初始化被优化掉，开门版链接/运行不由此次通过覆盖。
后续用户已创建 `vitis/s2b_idle_app` 并授权放入源码、由用户自行Build；Codex已复制7文件，未改配置/BSP、未Build。
最新实际参数见[源码放置报告](../../../report/system_s2b/20261010_app_source_placement/review.md)：现有O2/lwip4/低DDR保留，只追加G++语言/告警选项。
当前交付：[离线集成入口](../../../tools/check_s2b_integration.py)、[7文件锁定清单](../../../tools/s2b_integration_manifest.json)、
[用户手动Build/首次运行/失败停止清单](../../../docs/s2b_integration_checklist.md)。

实际boot_id候选已有102主机用例PASS，实际main有限日志已有308场景/1966调用PASS，均为历史主机证据，不是目标App验证；本轮未重跑。
新增仓库级预检29项通过，检查器23个新增用例逐项通过；原源码7文件不变。
[本轮报告](../../../report/system_s2b/20261010_integration_prep/review.md)记录首份测试失败及仅补跑的修正例、版本与权限边界。

历史源码/契约记录保留：[初始准备](../../../report/system_s2b_preparation.md)、[r1候选源审](../../../report/system_s2b/20261010_uart_source_r1/review.md)、
[身份输入契约](../../../report/system_s2b_identity_plan.md)。不把其中的“尚无主机验证”作为当前状态。

## 1. 当前交付及两个门禁

- `main.cpp`：独立 A53 standalone 冷启动入口；拟复用现有 `s1b_m3a_plat` **应用域** BSP。不是可以拼入 ROI/C3 的函数。
- `boot_id.{h,cpp}`：签名不变，生产 `acquire_boot_id` **仍恒 `false`、不写输出、不调用候选代码**；程序在 GIC/GEM/lwIP/UDP 初始化前停车。新增的是未接通的外部身份输入候选，**不是已验证随机身份生成器**；不可用固定值、`rand()`、XTime/RTC/MAC 哈希或编译时间骗过门禁。
- `kLabNetworkConfirmed=false`：**地址沿用已定，网络放行未授权**。C3 成功保留，不重验、不再次要求确认地址；此开关不是 Build 必须改为 true 的开关。
- 沿用配置：板 `192.168.1.10/24`、网关 `192.168.1.1`、MAC `00:0a:35:00:01:02`。保留原配置及用户确认，不新增出厂值/持续无冲突保证。不固定 PC 地址，合法 PING 的来源 IP/端口决定回包目的地。

### r1 候选已通过私有主机定向验证，生产仍未接通

- `boot_id.cpp` 匿名命名空间内的 `Uart0BootIdCandidate` 包含一次性状态、解析、时间预算及 UART0 适配。没有生产调用、全局硬件初始化或生产接通开关；`boot_id.h`、net公共接口、BSP、用户工程不改。
  已有默认关闭的私有 `S2B_BOOT_ID_HOST_TEST` 适配，同翻译单元复用实际候选；`main.cpp` 对应 `S2B_LOG_HOST_TEST`。
  两个宏均不得用于目标App；不复制 `sim/host` 测试文件。主机结果不证明真实UART/时钟/来源或目标链接。
- 恰好8位 ASCII hex（大小写均可），随后 LF 或 CRLF；0 合法。不裁剪/纠错/重同步，非法、截断、额外行、UART overrun/framing/parity 错误及超时均失败。候选首次失败锁闩，成功才提交局部 u32 并缓存；同一初始化生命周期重复成功只返缓存，不访问 UART/时钟。生产入口不受这些候选成功分支影响。
- 共用 **60s** 总截止点；残留最多 **64字节/100ms**，从实际观察到空 RX 开始静默 **20ms**；提示不超过 **64字节/1000ms**，TX 满轮询同时核总预算，提示期间观察到 RX 即失败；帧最多 **10字节**，尾部静默 **20ms** 并做提交前复查。相等即超时、不因进展续期，失败不写外部 `out`；总 FIFO 读取最多 **74次**。这些是源码限额，不是实测结果。
- 候选仅轮询现有 UART0 状态、逐字节操作 FIFO，不调用阻塞 `SendByte/RecvByte/printf`，不清错误、不复位、不改波特率。固定提示仅为休眠候选文本，并非获准执行的注入步骤。TX 入 FIFO 不证明终端显示；静默窗口不能识别延迟旧帧、未来第二行或合法 hex 之间的误码。
- 来源路线仍为 PC CSPRNG → 人工 UART0，板端自主后续；本轮没有生成随机数、访问串口或注入。板端候选只验证输入，不验证熵质量、来源、新鲜性、防重放或绝不碰撞。仅匹配 PS 初始化后的独立冷启动；无活动 C3/ROI/DMA，热复位、重跑 ELF、终端/PC 重连不作为已支持的新启动，失败不能同启动重试。
- **身份接通、网络放行、带外约定/来源表述落地分别另授权**。`docs/protocol.md` 不改；UDP 字节格式未变不等于外部来源约定已正式落地。Codex执行目标编译/链接/Build、设备/取数/注入/下载/在线仍需授权，不由预检推导；用户现已明确自行Build。

## 2. 启动顺序与边界（未执行）

身份来源成功 → 网络放行授权 → cache/GIC → lwIP → `xemac_add` → netif administrative up → `LwipIdle::open(5010)` → 单主循环 `xemacif_input`、栈定时器、`idle.poll()`。

- 用户本轮追加允许修正相关问题后，`main.cpp` 横幅、停车和绑定日志改为每次最多96字节的尽力输出：TX 满立即放弃，不等待、不重试、不读 RX、不取时；绑定 ID 用固定8位格式化。日志可能截断或丢失，不能以“没有 STOP 文本”推断启动/身份/联网成功。停车仍永久循环，不因日志失败继续初始化。此修改只消除 App 自己打印的无界 TX 等待，**不承诺整个 App 启动60s内完成**；BSP 内部打印/MDIO、MMIO挂死等边界仍在。
- 仅本 App 从匹配 PS 初始化后的独立冷启动拥有 GIC。BSP 的 GEM3 适配层自行登记/使能 IRQ95，App 不重复连接 GEM 中断，不在 `xemac_add` 后重新初始化 GIC；不接管现有 C3/S1b 的中断或活动 DMA。
- 现有 `NO_SYS=1/NO_SYS_NO_TIMERS=1` 推导 `LWIP_TIMERS=0`，不能指望 `sys_check_timeouts()`。本 App 准备以 A53 64位 XTime 在主循环维护 ARP 1000ms、IPv4重组 1000ms、TCP 250ms（BSP启用TCP，但App不建TCP连接）。无额外定时中断、不另加频率/计数配置、不在 ISR 调 lwIP 核心；每种定时器每轮最多处理一次到期。**现有 EL3 `XTime_GetTime` 在计数器停用时可能写频率/控制寄存器启用它，并非无条件纯读**；本轮未调用、不改 BSP，未来设备授权须包括该副作用。候选时间换算检查乘法溢出并向上取整；时间约束以计时器持续递增、正确 PS 初始化和 MMIO 正常返回为前提，不覆盖计数器重置/停摆或总线挂死。间隔是配置，不是实测周期或时延保证。
- 当前 BSP 的 standalone `xemacpsif_input` 一次最多一包；不外加“收空队列”为止的循环。输入/回调、栈定时器、协议 `poll` 同一主循环独占。
- 不额外读取 PHY/SYSMON、不做掉线重协商或 RX 复位维护。`xemac_add` 本身仍会做 BSP 的 GEM/PHY 初始化和 MDIO 访问；原 BSP 无界 MDIO 等待风险保留，不能声称启动有超时保障。`netif_set_up` 只代表管理状态，非PHY观测；状态包 PHY bit1 仍未提供观测。
- 协议首个合法 PING 前不发应用 UDP；栈可能产生 ARP/ICMP/TCP拒绝等帧，**不是整张网卡静默**。没有自己的 TCP 服务、DHCP、任务、ROI、权重或 DP。
- 成功 bind 不等于网线UP/PC收到/真板通过。未知 ms/temp/power 保持 qNaN；旧协议及 gcs 未改。

## 3. 集成检查与用户手动入口

```powershell
& D:\pytorch\python.exe -B tools/check_s2b_integration.py --record
```

在仓库根运行；脚本不启动编译器/旧测试、不读取当前BSP/用户工程、不执行网络/设备动作。
PASS只表示已审查的7文件、依赖清单、关闭门禁与历史证据版本一致，不是Build或启动许可。
失败留JSON后停，不自动重锁/改BSP/补库/重跑旧测试。

**手动步骤统一维护在[集成清单](../../../docs/s2b_integration_checklist.md)**：含集中授权矩阵、4cpp+3h复制映射、
Vitis2020.2/A53 standalone应用域、编译/链接/低DDR与回执检查，以及关闭门禁版首次运行的期望文本和异常停车。
来源路线和r1已批准、地址沿用已定；用户建App/放源/自行Build已明确，身份接通/网络放行/带外约定、设备/下载/在线仍分别另授权。
当前版首次运行也只可能检查身份门禁停车，不能作为联网验收程序。

## 4. 仍然不覆盖

来源路线/r1/沿用地址的决定不等于实现验证：已通过的仅私有候选/日志主机测试及本轮仓库预检；关闭门禁版目标App编译/链接/Build已通过；仍未做开门版初始化链接、真实UART/计时/熵/启动生命周期验证、GEM中断运行、ARP/PHY恢复、UDP收发或长稳。C3 成功保留、S1c/S2a 不重跑；原5×3有限验收不扩大，dump/OA/性能/长稳未覆盖、NaN未测/PHY未观测/非完整v1不变。成功前缀、LOAD_W/FULL超时不读/复用/free DMA及永久停车/外部PL复位后重启、补卡不追溯、P2暂停/G2旧OOC FAIL保留。不改gcs/旧driver/数值/公共接口，不接ROI/START/ROW/补传/权重/M2/DP/双缓冲/多核，不修S3等待期网络服务。
