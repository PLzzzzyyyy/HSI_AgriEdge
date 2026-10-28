# S2c：最小业务闭环操作入口

起点 `da8d476`，Vitis **2020.2**。固定 LongKou/v2、原点(x=0,y=0)、宽5高3。
不是完整地面站、完整 v1 或 S3 修复。S2b 40/40 PONG、41 STATUS 已过，不重跑。

**2026-10-10本轮已完成，无需照下面再Build/板测：** 用户14:56 Build通过，独立冷启动boot_id=e4196b84；
15:03 Codex一次START得到ACK/3 ROW/15字/DONE，用户UART同session=ec50ce2e/task=4599执行成功。
UART↔UDP↔既有参考15/15逐字一致，最小业务闭环PASS。原始证据见
[review](../report/system_s2c/20261010_minimal_roi/review.md)、
[实际结果HTML](../report/system_s2c/20261010_minimal_roi/board_run/result.html)。
以下是复现步骤留档；该启动已执行过，不能再下第二任务。未来新冷启动另获授权并使用新ID。

## 1. 创建及同步（本轮用户已确认关闭自动Build，20源同步已完成）

`vitis/s2c_roi_app`：现有 `s1b_m3a_plat` → `psu_cortexa53_0` → `standalone_domain`，
Empty Application / C++。只读核实平台/处理器/语言正确；新lscript主栈/堆各0x2000。
必须确认 **Project → Build Automatically 已关闭且当前没有Build**，然后才同步。

独立包 `build/host/s2c_sources_20261010/{app_src,manifest.json}`，20个文件。
只新增清单源码到新App的src；不覆盖lscript、README、工程配置，不碰S2b/旧App/BSP。
同名不同内容立即停止；保存逐源SHA和工程配置前后SHA。不自动Build。
再生源码包（只拷贝既有数值依赖，不重跑旧验证；输出必须为不存在目录）：

```powershell
D:\pytorch\python.exe -B tools\prepare_s2c_roi.py --out build\host\s2c_sources_new
```

## 2. 用户Build，然后核回执

1. 自动Build保持关闭，Refresh **s2c_roi_app**，配置选 **Debug**。
2. Properties → C/C++ Build → Settings → ARM v8 g++ compiler：
   - Optimization 选 **Optimize more (-O2)**，新建Debug默认O0，需用户设置。
   - Miscellaneous / Other flags 保留原项并补为
     `-c -fmessage-length=0 -MT"$@" -std=c++14 -mcpu=cortex-a53 -ffp-contract=off -ffunction-sections -fdata-sections -Wall -Wextra -Werror`。
   - 不定义HOST_TEST，不加fast-math，不改ABI。
3. ARM v8 g++ linker → Libraries 添加 `m`（不带-l）；Miscellaneous / Other flags保留原项，
   添加 `-Wl,--gc-sections -Wl,-Map=s2c_roi_app.map`，与原S1b数值Build口径一致。
   平台已继承xilffs/lwip4/xil/gcc/c的链接group和include/lib，不重配BSP或删库。
   保留新lscript，主栈/堆0x2000、低DDR `psu_ddr_0_MEM_0`。
4. 只对 **s2c_roi_app → Build Project**，不Clean/Build All/Build平台，不下载。
5. 回传此次完整Console；保留 `Debug/s2c_roi_app.elf`，有map则一并保留。
   核对编译参数/20源SHA/唯一main/无强未定义符号/低DDR BSS与DMA缓冲/执行符号/ELF SHA。
   Global timer pragma是note。已做的-fsyntax-only不等于App Build或链接通过。
   尤其检查每条编译命令含 `-ffp-contract=off`，不能用仅网络的S2b参数替代数值基线。
6. 新error/warning、意外平台重建或源码漂移：保存首份日志后停，不盲试/改BSP。

## 3. 用户独立冷启动（不能热接管S2b）

Build回执核对后，由用户手动完成独立冷启动、匹配PS初始化/FSBL、PL编程和新App下载。
不是只Restart/Run新ELF。沿原已验证启动流程，匹配冻结串行M3a平台：
XSA SHA256 `9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652`。
若走JTAG，新launch检查新ELF、匹配平台FSBL、Reset entire system、Program FPGA、A53_0；
不覆盖旧launch。断电/上电/下载全部用户操作。PMU-FW/PHY旧警告保留，不把1000当PHY实测。

SD沿用已过卡，逻辑盘1，`scenes/longkou/` 下：

|文件|字节|CRC32|
|---|---:|---|
|cube_f32.bin|243794880|BF3B60C5|
|weights/v2/cls_token.bin|10584|C85F498E|
|weights/v2/pos_embed.bin|63504|F5113FAE|
|weights/v2/weights_engine.bin|480576|27231983|

无需追溯补卡。新App在身份通过后先读完并校验SD（约244MB），随后开UDP；START前不推理。

- UART0独占、原参数；关自动发送/宏/重连重发。原样复用r1，所以提示仍为
  **`S2B BOOT_ID: 8 hex digits + LF/CRLF`**，不因这个前缀单独认定跑错App。
- 看到本次完整提示后，用PC系统CSPRNG现取，人工发送一次8位hex+LF或CRLF：

  ```powershell
  D:\pytorch\python.exe -c "import secrets; print(format(secrets.randbits(32), '08x'))"
  ```

  不复用e86a03b1；极小概率抽到旧值则停止并记录本次启动，不用固定值替代。
  60s总预算、提示/尾部静默、UART错误/超时永久锁闩等r1契约不变；不在同启动重试。
- 等待 `S2C SD rc=0 loaded=1 ... cleanup=0`，然后
  **`S2C READY boot_id=xxxxxxxx wcrc=27231983 roi=0,0,5,3 UDP=5010`**。
  READY前不发业务；核8位身份与人工输入一致，不用截断显示补零。
- 给出UART全文/文件位置及新8位boot_id，并明确 **“新版业务App已按流程启动”**，
  此后才由Codex执行下节指定客户端。未确认不发UDP、不操作设备。

## 4. 单条PC入口：确认后执行一次

```powershell
D:\pytorch\python.exe -B tools\s2c_roi_client.py --boot-id <本次8位hex> --board-started
```

只有一个短期客户端socket/临时本地端口，发送固定到192.168.1.10:5010。
不启动Web/其他服务、不改网卡/防火墙、不访问UART/设备工具、不自动开浏览器。
初始最多5s核此次新业务身份/空闲状态；一次START，PING250ms维护会话；
默认30s总上限（可显式5..120s），无START重发/ROWREQ/自动重启/换模型。
不是重跑S2b40包测试，握手只作本次身份隔离。

PASS须同时满足ACK关联、三行/15个实收CLASS、相同boot/session/task/wcrc的DONE
（done=total=15, front_row=3）、类别/保留位有效、无错误/补传计数、15字与原有限验收逐字一致。
重复行不增加像素，冲突立即失败；不因STATUS完成就补齐数据。
UART应有EXEC、`RESULT rc=0 driver=0 completed=15 halted=0`和15字，和UDP交叉核对后
才能宣称实际板端最小业务闭环。

每次新目录 `build/host/s2c_roi_<时间>/`：session.json、packets.jsonl逐包原hex、
summary.json、results.csv、直接可打开的result.html。首份失败不覆盖、不自动二测。
表格分列本次UDP与历史对照；类别零基，不编作物名；温度/功率/性能仍未测。
只读重放（无socket/随机/设备）：

```powershell
D:\pytorch\python.exe -B tools\s2c_roi_client.py --replay build\host\s2c_roi_<时间>
```

## 5. 边界/验证

私有目录src/ps/s2c_roi_app；boot_id、SD、ROI、tt_net、M3a/寄存器原样复用。
SD先加载；START后init→LOAD_W→ROI原4+4+4+3批次，回调仅验包/ACK/置位，main执行。
ROW只从CPU已提交结果取数，板端不含历史CLASS字或PC推理实现。
START32/ACK20/ROW40/PING16/PONG24/STATUS92B遵守原v1布局。
code0仅接受；执行失败code6+原错误码u32，随后永久停车，不定义新state。
同tuple同body只ACK不重跑；一次启动仅一次任务，不支持任务后换会话/peer。
未实现完整v1的v0兼容/INFO/STOP/补传/整景/上传/探查等。
旧同步S3服务时延限制保留，超1s可能offline/停发ROW，不借此偷偷改driver。
故障保留DMA及CPU成功前缀，不清cache/free/复用；外部PL复位+App重启由用户完成。

新增检查 `python -B tools/test_s2c_roi.py`：私有协议、一次性调度/失败前缀、PC客户端，
及新3单元对实际BSP的-fsyntax-only。不是旧数值重测/目标Build/真板验证。
原5×3有限验收、dump/OA/性能/长稳未覆盖、补卡不追溯、P2暂停/G2旧OOC FAIL均保留。
证据入口：`report/system_s2c/20261010_minimal_roi/review.md`。
