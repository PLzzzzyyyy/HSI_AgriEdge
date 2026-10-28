> 2026-10-10 22:38更新：当前入口`docs/gcs_20261010_next_round_handoff.md`和task_integration/review.md。下文较早runtime局部WIP/PC重复卡状态已过期，原第一轮范围不缩减。用户最新：PC不显示DP式大结果卡，分类图回到中间原主地图；计时是本轮必做。

# 第一轮完整功能接续交接（2026-10-10，范围背景）

## 0. 用户最新决定（优先于较早交接）

1. **做完约定功能再统一上板**。不现在prepare/sync，不写Vitis，不要求用户Build当前半成品；先成组实现/定向检查，齐备后一次同步、用户Build/下载/冷启动和新增实机验收。不承诺一轮对话完成全部，不以离线PASS替代板测。
2. **默认板卡推理；用户界面只提供板卡地面站**。隐藏/移除PC推理模式选择、PC参考推理入口、训练参考成绩及无必要的开发备注。不要再次要求用户选择数据源。
3. 这里“去掉PC”指去掉**PC推理模式**，不是取消电脑端界面：用户已明确确认 **PC与DP两边都显示完整分类图**，随同一任务进度更新，未完成区域留空。
4. **不重做原PC视觉**：保留原布局、配色、图例、分类图和图表，只接真实板数据/功能。DP沿用原PC视觉做分辨率适配。现在DP候选只有显示视图，不是完整网页/本地交互已经移植。
5. 普通页面不反复出现“不是PC推理”“本子集”“UART/CRC/boot”等技术解释，原日志/身份/来源/哈希/证据保存在后台与导出中。失败、断线、缺数据、未测、部分评测覆盖等必要状态仍必须显示；**不能隐藏真实错误、伪造指标/注意力/功耗，或删掉证据记录**。
6. 顺序：完整原版功能＋PC/DP同步显示与实机验收，之后再评估性能优化。约900多秒是端到端任务耗时，不当纯计算。板端计时采集/正确显示属于功能，应补齐；不现在开性能HLS优化。
7. USB鼠标控制DP、业务迁PS作为**下一阶段本地独立交互**，不是这一轮临时切架构。厂商手册确认4个USB-A HOST可接鼠标；软件Host/HID/本地控件未实现，不宣称插上即可用。当前仍裸机，不擅改Linux/BSP/驱动。
8. 第一版原有SD上电独立启动仍保留：启动镜像/模型数据/模式说明、摆脱PC串口身份依赖要一起解决；写卡、启动开关、断电上电由用户执行。

## 1. 恢复时读什么

- `CLAUDE.md` → `CODEX_CONTEXT.md`顶部 → 本文件。
- `report/gcs_roi/20261010_metrics_dp/review.md`：已实现精度与DP候选/原始实机证据。
- `report/gcs_roi/20261010_task_lifecycle/review.md`：刚完成的**runtime局部WIP**与测试，不等于任务控制已接通。
- 按需读`.claude/progress.md`、双方pitfalls和项目memory最新部分；不用重读全部历史。旧`docs/gcs_20261010_synced_next_handoff.md`里的“先Build”/“任务仍在跑”均已被新记录替代。

## 2. 实机任务已结束，旧服务允许保留

- 恢复第一步只读GET/进程/端口，不能凭这里记录重复起服务或重发START。
- HTTP `http://127.0.0.1:8765`，PID **38476**，cwd `D:/HSI_AgriEdge`，命令 `D:/pytorch/python.exe -u -B tools/gcs_roi.py serve`，日志 `build/host/gcs_service/20261010_192446/`。这是保留的**旧代码服务**，新光谱/精度候选尚未重启加载，勿宣称当前页面已更新。
- 21:20只读：run1 done，220000/220000；UART active=false / port_released=true，原因45分钟上限自动结束（不是用户点击），RX26646/TX9；UDP worker inactive，同PID无UDP端口。没有本轮遗留测试编译/浏览器进程。HTTP仍监听，按用户已授权跨对话保留，未称服务已退出。
- UART `build/host/gcs_uart/capture_20261010_193000_925202/`；UDP `build/host/gcs_roi/attempt_20261010_193330_881126/`。
- boot **bb6bd8e3**、session **ae327bac**、task **17276**；boot已消费，禁止重用/重START。不要重跑旧15像素或整景通过项，也不补PC推理。
- 用户已确认下载。原`data_acceptance`、`s3.passed`、`probe.passed`、`batch_acceptance`全true；6次记录/3个不同位置，**左上与右下未覆盖**。原报告true保留，覆盖缺项另记，不把“没问题”当所有功能通过。
- 最终原UART/UDP/页面包/ELF等归档：`report/gcs_roi/20261010_metrics_dp/final_acceptance/`，ZIP SHA256 `9c5907a25cd3d308124d54b4bf0f604669993ef6660fa1d8d601d85489dd2801`。
- 部署ELF仍 `vitis/s2c_roi_app/Debug/s2c_roi_app.elf`，SHA256 **c0f54bb591f552bd3bcbf1471f4c27199abcedb493e4240c2f41b416b3399267**，App `scene_probe_s3_r1`；用户18:29已Build，不重复让用户Build该版本。

## 3. 代码已完成到哪里

### 8868d58（本地、未push）
- `gcs/scene_input.py`：本地float32预处理输入光谱/7×7假彩色窗，大小/SHA/CRC校验、边界/旧响应/读取失败保护；不是板回传，不调用PC模型。
- softmax原路径已经是板端PROBE logits→CPU显示，不是尚未实现、不属于PC模型推理。用户新简洁UI要求只改显示措辞，不删来源记录或此路径。

### 3531baa（本地、未push）
- `gcs/board_metrics.py`＋`gcs/eval_longkou_v2.json`：板预测＋固定Test100/GT，带混淆矩阵、逐类召回/precision/support、OA/AA/Kappa、覆盖与JSON导出。
- 本次真实板Test100 **203642/203642**：**OA93.8362420326%、AA92.7284172630%、Kappa0.9201084387022872**。经UART/UDP/页面原字及CSV+MAT+Fraction两路径复核，无PC推理/训练成绩代填。
- `src/ps/s2c_roi_app/{main.cpp,roi_canvas.*,roi_display.*,roi_labels.h}`：整景不再关闭DP，提交行与UDP同源绘制，完整图/图例/进度/种植结构；Noto Sans SC固定标签位图/OFL许可/生成记录。没有改引擎、公共driver/BSP/数值或UDP布局。
- 6指标+17服务、33浏览器、canvas/实字回放、3实际A53 BSP语法通过；**没有新ELF Build/下载/DP目视**。DP图片是CPU离线回放，不是显示器照片，也不能据此认定最终外观已获用户验收。

### 本次新检查点：runtime局部WIP（提交号用git log定位）
- `roi_runtime.h/.cpp`新增`begin_task(x,y,w,h)`、`step_task()`、`stop_task()`，`sim/host/test_gcs_task_runtime.cpp`定向测试。
- 任意合法矩形、每次最多4像素/不跨任务行、非4整除尾批、已提交前缀读取；正常完成或正常stop后可新任务且不重init/LOAD_W；新task_mode支持调用边界PROBE，原任务结果与进度不覆盖。
- `busy`运行中重入拒绝；fault/LOAD_W/probe错误后`halted`保留，不允许stop清错或new task恢复；旧one-shot入口仍有原门禁。
- **未接到main/UDP/GCS！** `roi_protocol.*`、`BoardSource`、UI仍旧整景或固定5×3一次任务模式，PAUSE/RESUME/STOP和任意ROI按钮未上线；不要把runtime4种host模式通过说成用户功能完成。
- 当前任务结果仍单槽，会被健康新任务覆盖；多槽、旧task隔离、历史/通信恢复后续继续做，不能先放开多任务界面。
- 新task runtime 4模式、受影响旧scene runtime 8模式、实际A53 runtime语法均PASS；全是host桩/语法验证，不是重跑实机。

## 4. 新对话立即推进顺序

1. 把**板卡专用默认UI**落实在原界面：`gcs/server.py`的默认来源、`gcs/web/{app,board,panels2,uart}.js`。不只是隐藏radio，后台默认和路由也不能误触PC模型；刷新只恢复状态，不自动开COM/发推理/新身份。
2. 接续runtime，按`docs/protocol.md`**既有**STOP/PAUSE/RESUME、START、PROBE布局实现私有调度/协议/主机成组闭环：单一在途命令、ACK关联/有界超时/幂等，任务身份隔离，安全调用/行边界执行。PAUSE后仍泵网络，不在lwIP回调跑推理或停DMA。要同时适配DP对任意ROI/暂停/停止/新任务的显示。
3. 有界ROWREQ补传、断线恢复、结果槽与回收、历史/刷新/服务恢复，显式恢复非热接管；区分丢包统计与致命协议/数值错，不直接删旧安全判断。
4. 农情统计/地块台账/分区分析/报告全部接实际板结果，未接收像素不能算某类；真实评测继续固定标签、部分覆盖明确，资料路径与hash已有不重复索要。
5. 多场景/多模型、WBEGIN/WCHUNK/WCOMMIT/WACT等既有约定的上传/CRC/持久化/安全切换、训练后板实测比较。文件缺口再按准确路径/大小/CRC说明；不要假定当前SD三景齐备。
6. 性能**测量显示**区分板计算像素/秒与ms/像素、端到端接收速度/ETA；无功率计不造功耗/能耗。暂不进入提速优化。
7. 12层注意力当前引擎不输出：方案见`docs/gcs_20261010_function_first_plan.md`，12×6×6 Q0.24真实抓取，不能由logits/PC参考顶替。涉及新引擎/driver/公共契约/UDP扩展，先说明范围并专项确认，不擅删功能。
8. 全部功能候选稳定后更新统一同步器/源包/审查版本/字库清单，用户确认自动Build关闭后一次同步；用户Build，助手只读ELF审查，然后用户下载/冷启动/增量实机验收。现在的`tools/gcs_board_batch.py`仍旧基线24源/旧App标记，**禁止直接拿它给本轮同步**。
9. SD启动整套收尾：boot镜像、模型/数据、启动模式与操作、独立身份/任务入口，用户写卡/断电上电。全部约定功能与实机验收后才第一版完成；USB鼠标本地交互后续另阶段。

## 5. 约束与收尾

Build/下载/冷启动/实际地面站任务操作由用户执行；自动UART已授权且使用已确认COM6/115200，未改口无需重复选择/手抄身份；不能抢占串口。旧服务若保留先读状态，不能重复启动或自动连接。

只读证据和实现不能解除DMA错误停车，不改数值，不超越driver/BSP/公共接口授权。每阶段更新共享progress/context、evidence/llm_log、双方memory及索引；新坑只记可复用非重复项。只提交本任务，不push；保留`vitis/`、Packages等原有用户/生成物。
