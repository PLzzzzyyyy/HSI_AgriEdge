> **最新：2026-10-10用户已上板并完成基础通信冒烟，PONG40/40、STATUS41，身份e86a03b1匹配；不用重复测试或Build。**
> 独立客户端：[tools/s2b_ping_smoke.py](../tools/s2b_ping_smoke.py)。一条命令：`D:\pytorch\python.exe D:\HSI_AgriEdge\tools\s2b_ping_smoke.py`。
> 默认ID仅适用本次启动；今后新冷启动另按授权流程，用`--boot-id 新的完整8位值`。客户端日志自动存`build/host/s2b_udp_*`。
> [用户实测与只读归档](../report/system_s2b/20261010_udp_smoke/review.md)。现在缺口是业务链路，不是再做S2b准备；Codex未启动实际UDP/操作设备。
> 以下保留Build时的清单及历史状态；其中“尚未运行/客户端待确认”已由本条更新，不抹去历史限制。

# S2b 联网源码 r1：用户 Build 与首次运行清单

2026-10-10，起点 `4a602e3`。**源码已接通并同步；用户13:49新版Build/链接及只读ELF审查通过，尚未运行。**
当前源码：`vitis/s2b_idle_app/src`，仍是原4cpp+3h；仅main.cpp、boot_id.cpp更新。
当前 `Debug/s2b_idle_app.elf` 已由用户本轮Build更新为联网版，SHA256 `5a46010e2eeec4aa83eec4e1b054434f8db4c9c9844301095913f1784725fe6e`。
13:49:25–13:49:27，两cpp重编译+重链接，0error/0warning、2note；新ELF已核低DDR/唯一main/无强未定义符号、provider与网络初始化链接及顺序。
**不用再Build，下一另授权独立冷启动板测。** 源码同步回执是Build前快照，最新Build见`report/system_s2b/20261010_connected_source/user_build/`。
证据：[本轮报告](../report/system_s2b/20261010_connected_source/review.md)、[7源SHA/工程保护](../report/system_s2b/20261010_connected_source/sync.json)。

## 1. 用户手动Build（本轮已完成，以下参数/流程留备查，不重跑）

1. 保持自动Build关闭，Refresh `s2b_idle_app`；只选此App的 **Debug / Build Project**。
   不Clean，不Build All，不重建平台，不Run/Debug/Program FPGA/打包/下载。
2. 不需再调整现有参数。本轮只读核对与旧Build输入一致：
   - Vitis **2020.2**，`s1b_m3a_plat` → `psu_cortexa53_0` → `standalone_domain`，AArch64 standalone。
   - G++有效参数 **`-std=c++11 -O2 -mcpu=cortex-a53 -Wall -Wextra -Werror`**。
   - Debug G++ Other flags原有值：`-c -fmessage-length=0 -MT"$@" -std=c++11 -mcpu=cortex-a53 -Wall -Wextra -Werror`。
     O2在Optimization项，保留默认ABI/include；不重复追加，不定义两个`S2B_*_HOST_TEST`宏。
   - 保留平台应用域include/lib、现有lwip4及xil/gcc/c/C++支持链接group，不改BSP宏/库。
   - 保留现有`lscript.ld`；低DDR `psu_ddr_0_MEM_0`、栈堆各`0x2000`。
     这些是配置，不是联网版内存余量证明。
3. 保存**本次**完整Console及新ELF。增量Build至少应重新编译main.cpp、boot_id.cpp并重新链接；
   idle_lwip/idle_protocol两单元未变，复用同配置旧对象可以，但不能用“Nothing to build”当新版编译。
4. 交回日志后先审查：新时间戳/源码SHA、目标域/参数、唯一main、新增联网初始化符号/链接、低DDR布局。
   旧关闭版中未保留的`lwip_init/xemac_add/XScuGic_CfgInitialize`必须按新ELF实际核查；
   本轮纯主机测试**没有**覆盖这些目标链接依赖。若已有map一并保存，无map不为补map机械重建。
5. 如Build触发平台重编译、参数/源漂移、新warning或error：保存首份完整日志后停止，不自行改BSP/公共接口。
   旧平台7条warning与旧App3条Global timer pragma note保留历史，不预言新Build零告警。

**下一最短路径：新Build/ELF已审通过 → 明确设备及首次在线授权 → 独立冷启动。**
当前没有剩余的身份路线/r1/源码开关审批；不要重复申请这些已批准事项。

## 2. 已落实的带外身份约定（本轮未执行）

这是S2b有人值守的来源补充：每次受支持的独立冷启动，由**PC系统CSPRNG现取随机u32，人工UART0提交**；
板端只获取/校验/缓存，不称板端本地生成器。对应原协议每启动一个新随机boot_id的语义，
UDP字段/偏移/长度/字节序和公共接口不改；`docs/protocol.md`原文保留，S2b来源补充以本节为准。

- 使用既有、PS初始化好的UART0线路参数；provider不配置波特率/流控、不清错误、不复位UART。
  独占一个终端；关闭自动发送/定时发送/自动重连重发/宏，使用一次整帧发送而非逐键编辑。
  发送行尾仅选LF或CRLF，不能自动附加第二行/空格/空行。沿用已确认的串口设置，不另开第二终端争抢。
- 必须先看到本次完整提示 `S2B BOOT_ID: 8 hex digits + LF/CRLF`，再现取并发送一次；不提前排队，
  不从旧日志/历史剪贴板复用。下列是**另获实际取数/输入授权后才执行**的PC命令，本轮未运行：

  ```powershell
  D:\pytorch\python.exe -c "import secrets; print(format(secrets.randbits(32), '08x'))"
  ```

  只复制输出的8位hex，终端提交一次LF或CRLF。PC命令失败/输出异常就不发送、无固定值降级。
  不使用本文测试里的确定性值作真实身份；0本身合法，不能因抽到0而以常量替代。
- 帧恰好8个ASCII hex，大小写均可，随后LF或CRLF；不接受`0x`、空白、单CR、退格、NUL、非ASCII、
  少位/多位/多行，不纠错/重同步。非法、超时、UART overrun/framing/parity均失败，out不变。
- r1预算保持：总60s；提示前残留最多64字节/100ms，观察20ms无RX；提示最多64字节/1000ms；
  有效帧9或10字节；提交前20ms尾部静默及末次状态检查；最多74次RX FIFO读。
  所有阶段共享总期限，到达期限即失败，进展不续期。总时限从provider进入开始，不是从屏幕出现提示开始。
- 同初始化生命周期只尝试一次；失败永久锁闩，main禁中断停车；成功缓存供同启动使用。
  终端重连不是新启动，不能在同启动重试；仅App重跑/热重启不默认支持。
- 板端不能验证CSPRNG来源、新鲜性/人工重放、排除碰撞或合法hex间误码，20ms不是原子隔离。
  不承诺认证、防重放、无人值守；PC未发送与PC取数失败在板端都只会等待超时。

## 3. 首次运行清单——必须另授权后才操作

授权需集中包含：独立冷启动/匹配PS初始化及现有平台下载、UART0独占操作、PC实际CSPRNG取数与一次人工输入、
EL3 `XTime_GetTime`在计数器停用时可能启用它、GIC/GEM/lwIP/UDP初始化及约定的空闲在线收发。
用户当前“尽快上板”表示推进优先级，不撤销本轮明确禁止设备/在线操作的边界。

- [ ] 新Build及新ELF已审，不能拿旧关闭版ELF；保持P2暂停，不换未批准的P2/r9产物。
- [ ] 按另批准的板级流程独立冷启动，匹配PS初始化；不热接管C3/ROI、不在有未完成DMA时Run。
- [ ] UART日志横幅为 `S2B CONNECTED SOURCE r1: idle v1 subset; no board acceptance`。
- [ ] 完整身份提示后按§2现取一次并发送；身份失败预计`S2B STOP: boot_id acquisition FAILED; GEM/lwIP/UDP not initialized`，停止留证。
- [ ] 身份成功后源码允许cache/GIC→lwIP→GEM/netif→UDP bind；GIC/xemac_add/bind失败均永久停车、不自动重试。
- [ ] `S2B UDP PCB bound; boot_id=........; NOT a link/PING PASS`只证明代码报告PCB绑定，
  **不是PHY/link/PING或S2b验收**。横幅/STOP/bound均是尽力有限日志，可丢失；无日志不能推断成功。
- [ ] 地址沿用板`192.168.1.10/24`、网关`192.168.1.1`、MAC`00:0a:35:00:01:02`，不重复确认C3，
  不保证将来无冲突；PC地址不固定，合法v1 PING来源决定回包目的地。
- [ ] 真正PING/PONG/STATUS观察及客户端启动需明确在线授权，并确定现有可用v1客户端入口。
  `tools/periph_pc.py`是C3UT，不能替代v1。当前不启动/修改gcs、不修S3来凑在线条件。
  没有获批可用客户端时停在身份/PCB绑定观察，不声称在线PASS。
- [ ] 保存原始UART字节/时间、启动步骤、使用ELF SHA及允许的PC回执；异常保存首证，不循环Run/重发。

## 4. 永久保留的限制与未覆盖

60s仅provider的条件性软件预算；计数器停摆、MMIO总线挂死、BSP内部打印/MDIO等待无硬实时保证。
源码准备阶段没有目标编译/链接；同轮用户随后Build通过，Codex只读核实新ELF链接。仍没有真实UART/时钟/熵/PHY/GEM/lwIP运行验证、栈堆余量/长稳证明。
旧boot102/log308/关闭版静态29项及C3/S1c/S2a未重跑；仅r1和日志代码不变，旧证据不自动覆盖新入口/新版。
原5×3有限验收、成功前缀、补卡不追溯，dump/OA/性能/长稳未覆盖、NaN未测/PHY未观测/非完整v1不变。
任意LOAD_W/FULL超时仍不读/不复用/不free DMA、永久停车，外部PL复位后重启；不把S2b当恢复路径。
P2暂停/G2旧OOC FAIL和原分工保留；不动旧App/BSP/公共接口/UDP线格式/gcs/旧driver/数值，
不接ROI/START/ROW/补传/权重/M2/DP/双缓冲/多核，不修S3。

## 5. 离线复现与历史入口

仅新增接通差异：`D:\pytorch\python.exe -B tools/test_s2b_connected.py`。
这会在新`build/host/s2b_connected_*`编译/运行5个确定性主机用例，不取真实身份，不访问串口/网卡。
源码审查锁定起点4a602e3：r1主体、日志函数、net、公共协议不变，main仅开关和两条提示改变。
它不是新联网分支的目标编译/链接/运行测试。用户首次Build不要先重跑这套已通过项。
旧`tools/check_s2b_integration.py`及其manifest、旧boot/log测试入口是**关闭版历史版本检查**，
不适用于当前接通版，不自动重锁/运行它们以追求全绿；原报告仍按历史提交复现。
