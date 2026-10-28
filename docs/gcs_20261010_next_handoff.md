# 新对话交接：完成全部功能后才“第一版收工”

更新：2026-10-10。**当前是中途交接，不是第一版完成，不是完整协议v1验收。**

**已同步后的最新交接：`docs/gcs_20261010_synced_next_handoff.md`。** 当前9文件同步已完成，下一用户Build，不重复同步。此旧交接保留历史与最初全功能范围。

**当前最新入口：** `docs/gcs_scene_probe_s3_board_test.md`。用户已批准S3两文件最小改动，已实现并完成源包/离线检查，可进入本次自动Build关闭确认→源同步→用户Build/上板；仍未部署/实机验收，完整第一版目标不变。

**本日后续更新：** `docs/gcs_20261010_feature_batch.md` 是较新批次状态：host link/PROBE所有权缺口已修，同peer有界探查、整景只读核验和UART一键候选已接通并过离线检查；用户已批准主动点击后的UART0独占身份/采集，尚未实机执行。S3旧driver最小回调改动另待确认，其他全功能目标不变。本页下述WIP/未授权表述保留为起点历史，不覆盖新记录。

## 1. 用户最终目标与顺序

用户最后纠正了“第一版”的含义：要在新对话把上述功能全部做完、真板验收后，再作为第一版收工；
不是把本轮小ROI成功称为第一版。继续实施，不再只交准备方案。

1. 先完善原 `gcs/` 的真实板卡推理：LongKou整景400×550、单点探查以及原PC模式各业务功能。
2. 同轮处理S3（驱动等待期间网络服务），不能只把批间轮询称为S3解决。
3. 地面站操作由用户亲自点击，助手观察、验证和保存证据；不代点发任务。
4. 地面站功能完成后，再统一改DP：中文、逗号缺字问号、真实类别名、分类图/进度/统计，少放调试数字。
5. DC串联功率计暂不需要；功率/温度/性能/能耗未测就显示未测。并非要求伪造这些指标。
6. 用户嫌每次人工boot_id麻烦。仅提出过“一键串口助手”方案，**尚未授权自动收发UART0**，也未实现。

“整机”依据前后语境按“整景”400×550理解并向用户说明；其后用户明确“整个图推理像之前PC那样”，范围已明确。
用户已确认没有其他并行会话，gcs写权限移交本会话，不必再问原负责人。

## 2. 已验证的真实结果（不要重跑）

- 原地面站用户亲自选择板卡源/点开始。boot=`64ead9e4`，session=`d919c32b`，task=`27245`，START seq=1。
- 用户15:38:50–15:38:54仅Build已有`s2c_roi_app`：4增量单元，11对象链接，0error/0warning/2note。
  C++14/O2/ffp-contract=off/sections/GC/-lm沿用；没有重建平台/改lscript。
- 实测ELF SHA256：`9a1cd0132d6b6d89123ad35a85c2c99b8992404c32e7421f371c2f851dba88c7`。
- 第一次冷启动身份门禁失败，随机值f796395c是在停止后生成，未用；首份日志保留，根因不冒猜。
  第二次用户确认独立冷启动，r1输入64ead9e4成功，SD加载/CRC/cleanup成功，DP init_rc0/READY。
- 15:58:26用户发固定5×3任务；本次1PING+1START，ACK/PONG/3ROW/匹配STATUS，15唯一像素、重复0、错误计数0。
- 用户完整UART同session/task：rc0/driver0/completed15/halted0；15字与本次UDP/正式DOM/API/JSON/CSV逐字一致，
  既有有限参考15/15一致（参考只比较，不补数据）。验收文件 `formal_acceptance.json` 为全true。
- 地面站19项观察/下载检查通过；后续布局独立分区、分类彩图/置信度图、折叠详情、中文名称与单点实收结果
  是**同一真实任务数据的只读显示复核**，没有二次推理，8项检查通过。
- DP：用户确认有启动画面并指出逗号显示为`?`；UART确认结果帧flush。
  **未拿到DP最终15格逐字目视/照片证据，不宣称DP最终画面完整验收。**
- 类别映射已查真实训练/导出/包SHA：0玉米、1棉花、2芝麻、3阔叶大豆、4窄叶大豆、5水稻、6水体、
  7道路与房屋、8混合杂草。v2 checkpoint与weights_engine SHA匹配，WCRC27231983；本次预测玉米14、水稻1。
  这是模型预测，不是实地真值或OA；不再以“映射未知”为理由只显示编号。

证据：`report/gcs_roi/20261010_formal/`；实际包`board_run/packets.jsonl`、完整UART`uart_complete_user.txt`；
`user_dp_build.zip`含实测App源/ELF/map/配置/Build日志；`app_before_dp_*.zip`保留改DP前版本。
`ui_acceptance.json`含事件流、DOM值、身份、下载检查；`ui_export.json/.csv`为点击真实导出按钮所得。
截图既有用户截图，也有无头浏览器捕获；优先数值核验，不反复读图。

只读复核（无socket、随机、设备、推理）：

```powershell
D:\pytorch\python.exe -B tools\gcs_roi.py verify --run-dir report\gcs_roi\20261010_formal\board_run --uart report\gcs_roi\20261010_formal\uart_complete_user.txt --ui report\gcs_roi\20261010_formal\ui_acceptance.json
```

注意：`formal_acceptance`只覆盖固定ROI正式GCS显示，不包含完整DP/整景/性能。不要改历史summary中当时的
`uart_verified=false`以伪造实时验证；最终交叉核对结果在独立formal_acceptance文件。

## 3. 三个版本不能混淆

|对象|当前状态|
|---|---|
|用户 `vitis/s2c_roi_app` 源+Debug ELF|24文件固定ROI+英文DP，实际Build/运行通过；没有同步后续整景/探查|
|仓库 `src/ps/s2c_roi_app` 与 `gcs/`|正在扩展整景/探查，**WIP，未完成、未目标Build、未部署**|
|DP中文候选|已保存，但用户要求先整景/全部GCS，再统一DP；不能说已上板中文|

板端源码全包`build/host/gcs_roi_dp_sources_20261010`是已Build固定ROI的24源包。
`tools/sync_gcs_roi_app.py`只是当时7文件同步器，硬编码旧来源/24文件期望，**不能直接拿来同步现在WIP**。
后续应重新列差异和生成包，用户确认自动Build仍关闭后，带备份/前后SHA同步，配置与lscript保留。

当前旧GCS进程已正常关闭（见cleanup.json），磁盘源码已晚于当时进程加载版。不能拿页面旧会话或旧进程
证明WIP可用，也不能把目前repo源码SHA套到已过板测ELF上。
本次`session.json`记录了当时board_roi.py、wire client的磁盘SHA；没有声称完整旧GCS目录在发任务时做过不可变快照。
当前源码和变化均已Git留档；板端实际构建源在ZIP内。

DP候选补充：`dp_chinese_pending_not_deployed.zip`及未参与Build的`roi_labels.h`只是草稿。
类别汉字标签生成脚本未成功添加C0..C8，曾触发“C0 is not a member of labels”主机编译失败，
不能把中文候选描述成可直接Build的完整版本。当前主用roi_canvas已退回用户实测英文版，统一DP阶段再修。

## 4. 整景WIP已经写到哪里

- `roi_protocol.h/.cpp`：旧v1布局不变，START mode0固定400×550，ROWS每行348+52字，UDP载荷1412+228B；
  支持累计完成数/front_row、错误锁闩，仍单启动单任务。没有完整命令重发/补传/多任务生命周期。
- `roi_runtime.cpp/.h`：22万CPU结果槽；`begin_scene/step_scene`每次4像素调用**未修改的**tt_m3a_roi_run，
  两调用之间主循环处理网络；同一模型权重只LOAD一次；失败保留CPU前缀，不读/复用未完成DMA。
- `main.cpp`：整景循环、1800秒外层边界、每行CRC与总CRC UART，分段ROW；小ROI路径保留。
  单次旧driver内部仍阻塞，max_polls不是时间保证，S3未解决；整景每批PS取窗/embed也未证明网络最大间隔。
- WIP整景开始会`display_suspend()`关闭旧小ROI DP流，避免旧5×3画面冒充整景；这是临时策略，统一DP阶段必须替换。
  目前未同步/未运行此代码；用户手上还是原DP画面。
- `gcs/board_scene.py`：复用S2c公共头/ACK/PONG/STATUS解析，扩展ROW/整景身份和22万唯一像素判断；
  冲突重复先全段检查再提交，最后DONE+全像素+ACK才成功。
- `gcs/board_roi.py`：整景30分钟总界限/30秒无回执界限；分块事件和轻量summary，完成时CSV/全量JSON；
  **任务完成后socket立即关闭**，这点直接阻碍后续真板PROBE，应先修生命周期。
- `gcs/server.py`：新增`/api/run/{rid}/board_words`（u32 CLASS全景 + byte seen掩码）；源切换不发包，不PC回退。
- `gcs/web/board.js/core.js`：整景选项、轻量增量更新、实际分类/置信度图、全量数据恢复、原始详情抽样、实收邻域。
  **只做过JS语法检查，整景前后端浏览器联调尚未完成。** 每次tick画22万点/统计的代价需实测，非性能结论。

## 5. 单点PROBE WIP与首要缺口

已写**板端候选**：PROBE type09 24B、LOGITS type85 64B（9类）、ACK错误、序号/坐标去重；
仅任务DONE后同peer/task允许。runtime先调用已有CLASS路径得到相同input，再调用已有LOGITS输出接口，
不重写数值；main打印单点CLASS和9个Q16 logits。没有同步/Build/运行。

必须先处理：
1. PC收到整景结束后关闭socket。新socket/新peer会被板端身份锁拒绝；应设计显式有界交互会话、留证、可退出，
   不偷偷发心跳保活永久后台，不换peer绕过身份。UI真实探查按钮/REST/ws尚未接通。
2. PC目前`decode`不接0x85，不能向现有接收器直接投PROBE。要独立关联req_seq/task/scene/wcrc/坐标、长度、CLASS/
   logits一致性，保留首个错误；同序号只重发缓存不能重算。当前板端只缓存最近1次probe，迟到旧seq策略需补审。
3. 完整场景与当前探查的状态/缓冲/错误要隔离；probe失败不得把旧任务成功误当本probe成功。
4. 当前新增probe引用使主机runtime测试link失败：未提供`tt_m3a_output_bytes`、`tt_m3a_run`测试桩。
   不是目标Build失败，不能加空桩只为绿灯；增加真实探查调度/失败不读DMA等定向用例。
5. 当前界面“单点探查”仅查看本次已经收到的CLASS/置信度/7×7已有邻域，**不是完整logits探查**。
   概率、logits、注意力不能由PC模型补算冒充真板。注意力当前没有板端输出，完全对齐PC需要明确实现方案，
   或用户明确同意作为未支持项；不能私自删功能后宣称“全部完成”。

## 6. 验证状态（新变化必须重新核，不重跑旧基线）

- 固定ROI：18新Python单元/服务门禁，初始英文DP renderer/prefix/实际BSP语法，用户Build与新板测，已过。
- 整景最早子集（加probe之前）：`report/gcs_roi/20261010_full_scene/checks_161222/`，调度成功/失败、
  协议分包、7 PC全景用例、main/runtime/protocol/display实际BSP语法PASS。
- 最新交接检查：`report/gcs_roi/20261010_handoff/checkpoint_checks.json`：
  - 最新PC整景receiver 7项PASS；4单元目标语法PASS；5个JS语法PASS。
  - **tools/test_gcs_scene.py 当前FAIL（上述新增probe依赖缺测试桩），首份日志保留。**
  - latest source未目标链接/Build/板测；旧PASS不能冒充新版本PASS。
- `sim/host/test_gcs_roi.py`、server用例仍写“scan禁止”等旧断言，`tools/check_gcs_roi.cjs`仍有固定15像素、
  数字类名/可见详情断言；它们尚未适配后续整景/中文/折叠视图。不得对当前UI继续宣称19项全部已过。
- `tools/gcs_roi.py verify`目前只验固定ROI UART格式/15字，不支持FULL_ROW CRC/220000字，更不是整景验收器。
  补独立只读full验证，严格检查550行CRC、总CRC、唯一像素/缺口/身份/前端导出。
- 本轮离线fixtures均是单元输入，不是模拟板；禁止把这些或旧图当本次板源真实结果。

## 7. 功能完成清单（新对话实际推进，不作为“已做”清单）

- [x] 固定小ROI真实板→原正式GCS；原始字/置信度/状态/导出交叉核对。
- [x] 中文类别映射证据、类别图/置信度图、折叠原始字/同任务局部查询（固定ROI数据）。
- [ ] 整景真实板执行/接收/显示、22万像素完整性、UART CRC、刷新恢复/导出验收。
- [ ] 任意ROI（目前仅固定5×3或整景），坐标/边界/部分批次和新任务生命周期。
- [ ] 真板单点CLASS/LOGITS/概率与7×7邻域；无PC推理回退；输入光谱/注意力来源明确。
- [ ] PAUSE/RESUME/STOP、ACK关联/去重、任务切换、安全取消、旧消息隔离。
- [ ] S3：等待PL时网络服务，不破坏独占所有权/cache/超时停车；新增接口若必须改旧driver先集中确认。
- [ ] 丢包/断线识别、补传、结果槽/历史恢复、通信指标（沿docs/protocol.md，不自行改变线格式）。
- [ ] 多模型/场景、权重上传/CRC/持久化/切换、PC训练后的真实板闭环重跑。
- [ ] 原PC农情/地块台账/统计/导出使用真实结果；Test100/混淆矩阵/OA需真板执行及准确掩码来源。
- [ ] 全部GCS功能稳定后统一DP中文/标点/分类图/进度/图例/统计；用户目视及截图证据。
- [ ] 按用户想要的一键身份方案另获UART0自动收发授权后实现；没授权仍人工r1。

SD：当前完整LongKou float32立方体和v2三文件已在卡，不需为整景补这4文件。Test100掩码/其他景/模型
并不因此具备，实施前给用户精确新增材料/路径/大小/CRC，不擅自写卡或重命名旧文件。

## 8. 原边界与设备状态

- Vitis Build/下载/独立冷启动由用户；每次改App集中列清单，确认自动Build关闭后再同步。
- 只向192.168.1.10:5010做已实现范围定向测试；新boot及明确启动确认前不发任务。
- `64ead9e4`已消费，不热接管/第二次START；e4196b84/e86a03b1也不可复用。
- 初始“不要修S3/不要整景”后来已被用户明确扩大目标覆盖；**旧数值/driver/BSP/公共接口/UDP布局不能无故改**。
  若S3必须修改旧driver，先报告最小必要变更与验证计划，不能以“全做完”为由静默接管底层。
- DMA超时永久停车、外部PL复位+App重启、CPU成功前缀、补卡不追溯、原dump/OA/性能/长稳未覆盖、P2暂停/G2旧OOC FAIL保留。
- 关闭的是助手本轮服务/浏览器，用户IDE/XSCT/hw_server及板端没有被停止/复位。
  板端最后确认是旧App ONE_SHOT_COMPLETE；下轮必须核实，不假定仍运行或可热接。

## 9. 立即恢复动作

读CLAUDE.md、本交接、CODEX_CONTEXT顶部、最新进度和相关pitfalls；核Git/进程。
先复核最新WIP差异和上面已知link失败，不一开始就让用户Build。
建议先使整景+有界PROBE会话闭环、完善测试/浏览器离线检查，再集中一次App同步/用户Build/新冷启动真板验收。
不要继续给用户零碎多轮Build，也不要跳过证据把大范围功能称已完成。

常用入口：`tools/gcs_roi.py serve`（启动前核端口；当前WIP谨慎，不自动授权/发UDP）、
`tools/test_gcs_scene.py`（当前预期FAIL待修）、`docs/gcs_roi_acceptance.md`（较早固定ROI流程，顶部说明优先）。
后续“第一版收工”须完成实际约定功能/验收并明确剩余不支持项，执行四件套、证据/llm_log/双方memory索引同步、
核后台清理，只提交本任务、不push。
