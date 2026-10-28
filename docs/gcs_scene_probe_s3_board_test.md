# 整景＋单点探查＋S3：本批上板准备与用户测试

## 19:25最新状态与操作（优先于下方历史步骤）

**用户18:29已Build新版且只读审查PASS；不再Build、prepare或sync。** ELF c0f54bb5…b3399267。首次自动UART因FSBL LF/CR残留漏识别而停车，已修地面站并于19:24:46更新本轮服务，无板端改动；证据report/gcs_roi/20261010_uart_fix/review.md。

现在只需：**Ctrl+F5刷新→“链路与下发”点“连接板卡”→提示已连接后由用户独立冷启动、下载运行现有ELF→“板卡已就绪，可以开始任务”后亲点整景一次。** 自动沿用用户已确认并成功打开的COM6/115200，自动选空闲board源；不再手动选口/勾身份框/查看boot码/点击源应用。更换串口才展开设置，原串口被其他终端占用须先释放；不抢占、不自动开始推理。

数据/S3/PROBE三项仍须真实板测；整景完成后5分钟内三点PROBE/核验包的判据不变。下方“尚未Build”“唯一下一步Build”及旧串口操作是原交接历史，不再执行。后续五阶段与全部功能实机验收要求不变；新版GCS PID38476供本轮用户验证，恢复先核状态。

---

2026-10-10；起点 `7cf479a`。App标记 `scene_probe_s3_r1`。
新对话完整恢复/验证/后续规划见 `docs/gcs_20261010_synced_next_handoff.md`。
**18:18更新：用户已确认并完成9文件同步，24/24源匹配；现在由用户Build已有`s2c_roi_app`，不必再同步/重建平台。尚未目标链接/Build/实机验收，不能直接用当前旧ELF测试。不是全功能第一版收工。**

同步回执/备份 `report/gcs_roi/20261010_s3/sync_181802_081546/`。同步后IDE的.prj新增Debug dirty=true，其余字节未变；只读后验已仅对白名单布尔元数据容错，不回写工程，不放宽编译/链接配置。下方步骤1已完成，从步骤2继续。

## 用户只需执行的流程

1. **确认Vitis自动Build仍关闭**。助手获得本次确认后，一次同步下列9文件，自动备份并核24文件SHA，不动工程配置/链接脚本/平台；你也可在已关闭后自行执行下方唯一同步命令。
2. 你在Vitis **Build已有`s2c_roi_app`**，不用重建平台。不用再抄boot_id或跑多组审查脚本。
3. 原GCS选择“板卡UDP”并应用；在“链路与下发”刷新UART列表、选择**原UART0端口及原波特率**，断开其他串口终端，勾选确认，点“连接并自动采集”。工具**先只读审查新ELF和源码**，通过才连接COM；等待提示后，你再按原受支持的独立冷启动/下载步骤启动新App。不要等App的60秒身份窗口快过了才连接。Build、下载、PS初始化/冷启动均仍由你操作。
4. 界面提示身份已核对后，选择“整景巡检”并手动开始**一次**。完成后，在固定5分钟探查窗口内选几个点（建议左上、内部、右下），逐个点“在板端重新探查此点”，每次等结果再选下一个。
5. 点“核验整景并下载证据包”。报告分别列出**整景数据、S3等待期间服务、单点UART/UDP一致性**。下载成功后点“关闭探查会话”和“结束采集并释放串口”。若有错误/缺材料，保留首份报告，不在同boot重启任务、不自动重新推理；交给助手看证据。

助手启动原GCS可用 `D:/pytorch/python.exe -B tools/gcs_roi.py serve`；启动前查8765，不替换用户服务。源选择/页面打开不发送UDP；助手不替用户点START或PROBE。

手工同步的唯一入口（**只有你已确认自动Build关闭后**才运行；也可让助手在你确认后代做同步）：

```powershell
D:\pytorch\python.exe -B tools\gcs_board_batch.py sync --auto-build-off
```

默认读取已准备包 `build/host/gcs_scene_probe_s3_r1/`。命令不Build、不下载、不复位、不打开UART/UDP。源码/配置被别的操作改过或Build进程仍在就拒绝，不覆盖用户工作。无需使用旧的七文件`sync_gcs_roi_app.py`。

## 本批9个更新文件与保护项

`main.cpp`、`roi_protocol.cpp/.h`、`roi_runtime.cpp/.h`、`roi_display.cpp/.h`、`tt_m3a.cpp/.h`。

- 前7文件含前一批整景/PROBE WIP；新增2个旧驱动文件只作用户此次批准的等待服务与重入保护。现有24源组成不变，共11个cpp。
- `.project/.cproject/.prj`、`lscript.ld`、README、旧ELF不修改，源同步前后逐字哈希核对；平台/BSP/HLS/权重/SD文件不改。
- 新源包和全部11cpp的2020.2 AArch64/实际BSP语法结果已归档：`report/gcs_roi/20261010_s3/prepared_bundle/`。`readiness.json`明确用户App还未同步，旧ELF未变。
- Build后点击UART按钮会只读检查实际ELF布局、低DDR结果/输入/DP缓冲、真实调用符号、新S3 hook/NetPump/probe/整景符号与App标记，并记录ELF SHA；绝不自动编译/重链。任何失败都在打开COM之前拦下。

## S3实现与板测判据

- `tt_m3a_set_wait_service(callback,context,256)`默认关闭，App显式注册；每256次未完成poll服务一次。**256是轮询次数，不是微秒**。旧API调用方式、数值、寄存器设置、clean/flush/invalidate路径保留。
- 同步调用期间持有执行锁；回调再次init/load/run/修改回调返回BUSY，在MMIO/cache前拒绝。不作为线程/ISR锁；没有第二IP owner。超时仍永久失效，不能在该App继续运行/读复用DMA；须用户外部PL复位＋独立重启。
- App唯一`NetPump`既在批间调用，也从driver等待内部调用。回调只服务一次`xemacif_input`、定时器和STATUS，不执行数值/日志/重入。已只读核实际2020.2 standalone BSP的`xemacpsif_input`每次最多1包；没有自加无限排空循环。
- `S2C S3 scope=scene ...`记录等待内部服务次数、收到的命令数、全任务最大服务间隔/单次服务时间。自动验收要求同任务、等待内确有收包、最大间隔/单次服务低于**既有协议1秒在线租期**。这不是新设推理速度目标、不是功耗/性能验收；数值以本次板测为准。
- App整景执行外层限1800秒；PC1830秒为终态回执留30秒，不续期、不自动重跑。原driver max_polls仍是迭代限，不是时间保证。
- 新READY必须包含`app=scene_probe_s3_r1`；自动身份入口拒绝旧小ROI/旧整景候选标记。原r1提示/帧/板端60秒身份契约不改。

## 自动证据

- UART：`build/host/gcs_uart/capture_*/`，原字节、可读日志、tx_attempt/成功tx记录和关联用户Build审查目录。
- UDP/结果：`build/host/gcs_roi/attempt_*/`。探查使用同peer固定300秒，无空闲心跳，5秒3次相同包/seq有界重传；不另开socket接管，任务与探查失败隔离。
- 统一核验ZIP：原UART/UDP、JSON/CSV、interaction和报告。22万唯一像素、ACK/DONE、550行与全图CRC、页面words/seen SHA、原始导出逐字核验；PROBE进一步核UART CLASS与9个Q16 logits、请求/回复、身份握手及只执行一次的日志。
- `data_acceptance`只表示整景数据；`s3.passed`和`probe.passed`分开，三者同时通过才`batch_acceptance=true`。**仍不等于第一版完整验收。** CPU只对板端logits做softmax显示，不调用PC模型代推理。

## 已完成的离线检查（非板测）

- `tools/gcs_roi.py test`：`report/gcs_roi/20261010_full_feature/checks_175510_581288/`；S3 real-driver+real-protocol等待测试5种（默认关闭/启用/立即完成/超时/契约错误），C++调度/协议/6探查场景，Python50个、4App+1driver目标语法、5JS、16离线浏览器检查PASS。
- 后续仅改新ELF自动门禁和串口界面：`report/gcs_roi/20261010_s3/final_integration/`，11服务/6UART/4全景核验用例及浏览器16项、UART JS PASS；服务比之前新增3个门禁用例，即本批总计53 Python。不拿早期SHA覆盖最后变化。
- 包内11个cpp的独立目标语法全部PASS。以上没有目标链接、实机网络/串口、板端运行、真实新身份或Build。
- 首份TDD RED是缺新回调接口的编译失败（`s3/driver_173539_759836/`），GREEN及协议集成在同目录族；已通过的小ROI真实板测没有重跑。

## 仍然未完成

本批是阶段板测，不是原全功能目标的缩水版。任意ROI、运行中插入探查、任务暂停/恢复/停止/新任务安全切换、丢包补传/结果槽/服务重启历史、多场景多模型上传/CRC/持久化/切换、农情台账/统计业务完整对接、Test100/OA与训练后真实板闭环仍待；注意力/光谱板源方案未闭合。后续继续这些功能，**全部GCS稳定后才统一DP中文、标点、图例、分类图和进度并实机验收**。本次整景期间DP旧ROI流暂停，不能拿它当整景显示。

无需功率计；温度/功率/性能未测仍显示未测。原64ead9e4等boot已消费，不热接管/第二START。DMA永久停车、CPU成功前缀、外部PL复位、补卡不追溯、原未覆盖、P2暂停/G2旧OOC FAIL等历史限制全部保留。
