# v5 实机问题接手：界面、单点探查与连续任务

更新：2026-10-11 22:43（接手核验，尚未修复本页问题）。

## 当前停点

- 恢复会话：`codex-session-01a12b2a-1a59-77c0-942e-3407ca7e9e08.md`，导出于22:37。末尾用户要求统计问题、在新对话解决；尤其要求推理期间精度实时更新，以及清空后刷新不再自动出现旧图。
- **21:58旧快照的“等待登记/切服务”已过时**。v5正式ELF已登记，用户随后完成JTAG运行。批准ELF SHA为`57c5e3f0c954e9adf384f05590022e116f8083de4502fa4bb6c5f9d05ce1fc3e`，release为`69c36469740f3530ae0ea09efa4f02156567736ca8f40e26f5cb59ae664f5747`。不要再走旧v4误拒流程，也不要原样重复同步/Build/切服务。
- 22:43被动核验：GCS **PID 20352**，监听`127.0.0.1:8765`；旧35444已退出。工作目录`D:/HSI_AgriEdge`，命令`D:/pytorch/python.exe -X utf8 -u -B tools/gcs_roi.py serve --port 8765`。日志在`build/host/gcs_r1_abi4_user/service_switch_v5_01/server.stdout.log`及`server.stderr.log`。
- 当前主机API显示`authorized=false / active=false / channel_ready=false`，UART已释放、TX/RX均0；未观察到PID20352持有UDP端点。这是**主机侧状态**，不是重新查询板卡后的硬件状态。不得自动接管、清理旧会话或发START。
- 最后有效板端身份为`boot=228ce0eb / session=912652d6`；已使用的SD journal和本地boot claim都不可回退/删除。

## 已核实的真实回执（不等于完整验收）

- task1：longkou/v2，整景目标220000像素，实际收到82000像素/205行后`stopped`，不是整景完成。板端任务step统计为`226.195 px/s / 4.420963 ms/px`，包含PS准备、引擎等待及其服务；不是纯PL耗时。
- task1在`row=142,col=103`的单点回执为`done`：有9个LOGITS、432个Q0.24注意力值，形状12×6×6、CRC`17189094`。不能把右侧空白解释为“板端没有注意力输出”。具体界面状态/异步绑定问题仍待复现。
- task2：ROI为`x=62,y=148,width=182,height=136`，0/24752像素、无ACK，错误为“模型回执超时；提交/激活状态未确认，不自动开始任务”。原channel结尾`healthy=false / closed=true / latest_task=1`。超时根因尚未确认，不能通过放宽身份门禁或隐藏错误解决。
- 初次启动接入0回复与用户确认网线未插紧的时间线相符；之后已真实接入并推理。不要继续当作“停在main/尚未Build”的旧问题处理。此前PMU-FW警告仍没有独立消除证据。

## 待修清单与验收要求

| 优先级 | 问题 | 当前依据与下一步 |
| --- | --- | --- |
| P0 | 停止整景后框选任务模型回执超时，重连接到旧任务身份 | 查原owner、模型事务、证据回读与终态切换；先用真实回执构造离线回归。保留原失败，不自动接管或重发任务。 |
| P1 | 单点必须可独立推理，不以先做整图预测为前提 | 当前板端探查入口依赖已有任务/连接；梳理独立探查生命周期，不用自动启动整景来绕过。若需固件/公共协议扩展，先列清范围与重新绑定/部署步骤。 |
| P1 | 单点右侧注意力及其他输入/输出图表缺失或与原界面不一致 | 已有真实12层注意力回执；核光谱、概率、注意力、层选择、历史/当前任务及坐标绑定。完整性/身份/CRC不通过仍应留空并明确原因，禁止用旧值或PC重算注意力补图。 |
| P1 | 精度指标须随推理实时更新，不只在单独评测或结束后更新 | 按当前任务已接收结果与固定测试标签的交集增量统计；显示样本数/覆盖与“当前部分结果”，不把未推理像素算入，也不冒充完整数据集最终精度。 |
| P1 | 左侧农情分析空白 | 复现板端结果到统计/业务面板的刷新链路；按真实接收覆盖更新，不把局部结果外推为整景农情。 |
| P1 | 清空PC结果后刷新浏览器又恢复上次识别图 | 源码确认：按钮只`setAB(null,null)`清当前选择；初始化恢复服务历史，重新选择已有结果。需持久化清空显示意图，覆盖刷新/重连/异步回填；默认保留原始任务历史与取证文件，不做物理删除。 |
| P1 | 清空PC结果时DP不动 | 当前按钮仅前端清理，没有DP命令。记录为PC/DP清屏语义与联动需求，先区分清显示、停止任务、删除历史；不得借清屏偷偷发START/STOP或丢弃证据。 |

优先顺序：原回执保护与P0离线复现 → 清空持久化/实时精度/农情与探查显示 → 独立单点及DP控制所需接口 → 定向回归 → 用户许可部署和实机验证。第一轮A～G/T矩阵仍保留，不能凭上述部分回执全部置PASS；性能优化/第二轮不提前启动。

## 恢复路径

- 被动接手快照：`build/host/gcs_takeover/20261011_224332/api_state.json`、`receipt.json`（6份恢复输入SHA256；没有板卡控制动作）。
- 已登记ELF：`build/host/gcs_r1_abi4_release_v5/approved_elf.json`；服务切换：`build/host/gcs_r1_abi4_user/service_switch_v5_01/switch.json`。
- 启动：`build/host/gcs_network_boot/network_start_20261011_221453_353673`。
- task1：`build/host/gcs_roi/task_20261011_221543_103873/summary.json`及该目录原始报文、`board_logs`。
- task2：`build/host/gcs_roi/task_20261011_222229_251595/summary.json`及`packets.jsonl`。
- 共用通道：`build/host/gcs_roi/channel_20261011_221543_092598/`下`session.json`、`summary.json`、`packets.jsonl`。
- 代码入口：`gcs/web/`下`app.js`、`core.js`、`board.js`、`panels2.js`、`agri.js`；`gcs/server.py`、`gcs/board_link.py`、`gcs/board_upload.py`；DP另核`src/ps/s2c_roi_app/`。本轮这些文件未改。
- 总验收：`docs/gcs_20261011_acceptance_matrix.md`。优先读当前条目，不沿较早文档重复执行旧同步/初始化/服务切换。

## 工作树与边界

- HEAD仍`984c872`。上一轮ELF加载态修复尚未提交：`tools/gcs_release.py`、`tools/gcs_release_elf.py`、`tools/gcs_release_platform.py`、`sim/host/test_gcs_release.py`、`sim/host/test_gcs_release_refresh.py`、新`sim/host/test_gcs_release_identity.py`及`report/gcs_roi/20261011_elf_identity_fix/`。保留其改动，不视为本轮新修复。
- 本轮仅被动恢复与交接记录/可访问双端记忆同步；未跑功能回归、未改业务代码、未提交或push、未Build/同步/重启服务/操作SD与板卡。旧97/97属于v4离线基线，41项属于上一轮v5身份定向验证，均不是本轮重新执行的结果。
- 没有新技术问题被修复，不另造llm_log、性能证据、技能或重复踩坑。原始会话、失败回执、用户工程及无关产物保留。生产服务20352按既有授权保留，没有本轮新启动的后台任务。
