# DP/中文候选定向回归收口与新清任务语义交接

2026-10-12 15:30，非运行候选，未发布、未上板。

## 1. 当前结论与恢复顺序

继续唯一候选 `C:/Users/86187/.codex/worktrees/f3fb/HSI_AgriEdge`。先读主树 `CLAUDE.md`、`CODEX_CONTEXT.md` 顶部和本文，再按需查证据。**原23路径初版已存在，本轮补测并做最小修正，不要重新实施中文化。**

- 1581仍是v8正式源码树，3716冻结；主树只维护本轮记录/独立补丁。不得从f3fb启动真实服务。
- 原DP/中文范围的受影响离线检查已收口；**用户新确认的“清除上一任务当前结果”尚未实现，已有明确RED入口**。旧“仅隐藏/恢复”通过不等于新需求通过。
- 用户最新提交约定：四件套默认审查并提交本轮已验工作和必要交接记录，不再逐次询问commit许可；不push，不混入继承/并行改动。发布、上板、服务操作仍单独受限。

## 2. 本轮实际改动及证据范围

证据根 `report/gcs_roi/20261012_dp_chinese_candidate/regression_20261012/`。

本轮产品/测试续改6路径（不含交接/工作流文档）：

1. `gcs/web/board.js`：身份拒绝或本次请求未完成时，清除派生的旧标题/置信度/中心点色块，不仅清图表；板端概率条按结果场景/类别使用原配色。**没有放宽或重写身份门禁**。
2. `sim/host/test_gcs_scene_canvas.cpp`：将受影响断言改用实际 `map_x()/map_width()/map_y()/map_height()`，不再把可用视口当成真实地图边界。
3. `sim/host/test_gcs_chinese_canvas.cpp`：扩展三景CPU数值绘制、状态、边界、点卡/统计隔离、旧隐藏/恢复、刷新范围与遗留15点显示检查。
4. `tools/check_gcs_chinese_names.cjs`：30项名称/ID/颜色/占位/跨景/非法输入检查，显式核对47个中文名。
5. `tools/check_gcs_chinese_dom.cjs`：真实HTML/CSS/ECharts与板端显示逻辑的离线夹具；地图绘制、实时轮询、网络传输被隔离，API仅内存响应。默认检查原显示范围，`--pending-clear`开启未实现的新清任务RED。
6. `sim/host/test_gcs_result_clear.cpp`：新语义的待实现CPU规格；**目前4 FAIL/1 PASS，不属于已验产品功能**。

原 `task_changes.json` / `dp_chinese_candidate.patch` 原样保留；接手23路径SHA全匹配，未改的34个继承目标源未漂移。本轮原字节基线在 `resume_sources.zip`，续改清单/快照在 `continuation_changes.json` / `continuation_snapshots.zip`。`continuation.patch` 与 `combined_dp_chinese.patch` 分别为本轮6路径和累计26路径工作快照，均正反向apply-check通过，**其中包含明确待实现的测试，不是全PASS发布包**。

已验证归档另外使用 `verified/`，仅含已验显示补丁、匹配验证SHA的源码快照、回执与提交范围；新清任务RED单独保留。候选相对HEAD还包含52源继承差异，不能直接 `git add .` 或把整文件差异当本轮成果。主树以独立补丁/快照和记录提交，产品不热灌到主树/1581/3716。

## 3. 已完成验证及真实失败纠正

| 范围 | 结果 | 证据 |
|---|---|---|
| 三景47中文名、板0基/PC未标注0、跨景颜色、非法ID | 30 PASS | `names_expanded_initial.log` |
| 真实CPU画布数值检查 | 21组 PASS | `canvas_initial.log` / `canvas_initial_checks.json` |
| 96字库元数据/位串SHA、47中文绑定与三景DP/PC原色 | PASS；不读图/字体二进制、不重新生成 | `label_binding_audit.json` |
| 受影响旧host：roi_canvas、scene_canvas、probe_canvas、display_control | 4 PASS | `host_a53_checks.json`及对应日志 |
| 实际BSP/A53：roi_canvas、roi_display、main | 3语法 PASS，无App Build/链接 | 同上 |
| 最后改动的board.js及2个CJS | 3语法 PASS | 同上 |
| DOM初轮 | 40项：22 PASS、18 FAIL | `dom_existing_browser/checks.json` |
| 修复后定向DOM | 29/29 PASS；另12项未受影响初轮PASS沿用，合并41项，不重复全跑 | `dom_point_fix/checks.json` |

CPU覆盖真实地图居中/缩放、完整CLASS顺序与直方图、三景右下角ROI、六状态、最长tag/任务号/极端性能数值、所有更新落在共用刷新矩形、点卡只改自身矩形、原始CLASS不变；但仍是CPU数值验证，**不是物理DP目视或板测性能结论**。

DOM两类实际缺陷：旧身份拒绝只清概率/注意力，旧类名及色块仍显示；概率条沿用ECharts默认色。均已最小修正。另一个初轮FAIL是夹具误把“规范模型名匹配”的合法版本别名回退当成错误：修正负例使两个版本匹配分支都失败，并增加规范模型别名仍可用正例，**没有收紧/放宽原门禁**。

首次浏览器启动失败是缓存绑定寻找未安装的Chromium1243；改为显式使用已安装1208，无下载安装。失败回执 `dom_initial/` 保留。测试不截图、不读图片、不访问8765、不发真实POST/WebSocket。旧7/23/119整套和未变文本报告没有重复运行。

## 4. 下一轮优先：实现新“清当前任务结果”语义

用户已明确确认：

> 任务结束或停止后，清除上一任务的当前分类图、区域统计、点卡、进度和任务摘要，回到“等待新任务”；下一任务从零显示，旧结果不混入或自动回来。历史、原始回执和失败证据保留。不隐式停止/启动任务。

本轮为了及时交接，仅落地需求与失败规格，**产品仍是旧隐藏语义**。新RED：

- DOM `clear_task/terminal_resets_summary`、`late_tick_stays_waiting`、`running_refused`、`paused_refused`：4 FAIL，旧摘要仍是 `#77 已完成`，运行/暂停仍可隐藏。
- CPU `test_gcs_result_clear.cpp`：清后计数仍保留、运行/暂停未拒绝、旧任务update仍接受，共4 FAIL；新任务本来就能从零开始这一项PASS。
- 回执 `dom_pending_clear/checks.json` / `result_clear.log`。这不是新问题已经修好。

恢复后先读这些测试，再决定清结果状态机，不要只改按钮文案：

1. PC：`core.js::ResultDisplay`、`panels2.js::clearResultDisplay`、`panels.js::tick/runState`、`board.js::render/controls/display/tick`。清除应解除当前结果/摘要，不删 `S.runs` 的历史；旧tick、gate及迟到点回执不能自动恢复。运行/暂停/未完成操作应拒绝清除，不暗发STOP。
2. 新任务显式启动后允许新身份/零进度显示，保持 `ResultDisplay.arm/accept` 身份规则；检查PC参考入口与板卡入口差别。历史只能显式查看，不再把“恢复DP显示”混同撤销清当前结果。
3. DP：`SceneCanvas::clear_predictions/update/append/probe/restore_predictions` 与 `roi_display.cpp::display_scene_control`；当前action0仅隐藏，action1恢复。`main.cpp` 前台取显示请求，不应为了清结果重启DP/DPDMA或清ResultStore/运行协议任务。当前结果状态与保留历史/控制身份须分离，考虑清后新独立点、旧update拒绝、下一任务begin、故障告警不得伪装为已解除。
4. 协议原owner/boot/session/task/nonce/seq校验、已有互斥与只读证据必须保留。是否需要协议门禁调整尚未决定，不要将本段设计线索当成已选实现。
5. f3fb不是完整运行副本：早期只继承了52目标源，`gcs/board_display.py`等后端与较新的协议显示测试不在该基线中。若实现确需动后端，先对照1581只读源码，按需归档/继承相关基线，不拿主树旧后端重做，不直接运行候选服务。

## 5. 安全边界与最后服务快照

- 14:36/14:38无8765监听；14:50看到用户启动命令对应PID10400，当时还未监听。**15:27:32再次被动查询时无8765监听，也未见该服务命令/PID**。原因未调查，助手没有停止/重启它；用户曾反馈“好了”是历史信息，不据此推断当前仍在。
- 本轮没有读取HTTP任务状态，不能沿用14:24的#8状态当现态。下一轮先被动核实，不自动启动、重连、恢复、接管或停止任务。
- 1581的52个对照源、冻结3716的49个可比源SHA保持不变；见 `preservation_audit.json`。本轮所有host命令、浏览器均已结束，无助手后台待接管。
- 不热改1581/3716，不操作板卡/SD/真实模型，不同步App/Build/下载/HLS/Vivado，不push、不读图。板端输入方案未定；闭环非核心，保留成果不重训。

## 6. 定向复现

在f3fb中运行，所有输出目录使用**新名字**，不要覆盖原FAIL回执：

```powershell
node tools/check_gcs_chinese_names.cjs
node tools/check_gcs_chinese_dom.cjs --out build/host/dp_chinese_dom_new
node tools/check_gcs_chinese_dom.cjs --out build/host/dp_clear_red_new --grep '^clear_task/' --pending-clear
```

第三条当前预期失败，不能当常规PASS回归。C++编译/执行和A53完整argv在 `host_a53_checks.json`、`canvas_initial_checks.json`；仅复验实际受修改影响的组，不复制旧全套。Playwright复用现有绑定/浏览器，支持 `PLAYWRIGHT_MODULE` / `PLAYWRIGHT_CHROMIUM` 覆盖，不自动安装。

协作日志 `report/llm_log/20261012_dp_chinese_regression.md`；证据索引 `report/evidence.md`。提交号与提交/未提交范围以 `CODEX_CONTEXT.md` 顶部及提交回执为准。
