# 2026-10-12 单项补充：旧隐藏提示夹具迁移验证

**仅夹具1路径变化，精确DOM 1/1 PASS；产品未改、未发布。** 下方原9/24路径与58项记录保留，本节不将其称为本轮重跑。

- 旧 `layout/legacy_hide_preserves_history_no_transport` 更名 `layout/terminal_clear_preserves_history_no_transport`。前提确认done、已选历史、统计/点卡非空；清后验证选择解除、零统计、点卡/概率图清空、进度摘要归零/等待新任务，历史/四类原缓冲/S.live/控制来源不变。提示明确历史/原证据保留及DP未清除，旧restore返回false且无新请求。
- 回执 `report/gcs_roi/20261012_result_clear_candidate/legacy_fixture_20261012/dom_terminal_clear/checks.json`：仅上述1项，页面错误0、拦截异常0、浏览器关闭；`commands.json`、`syntax.log`、`dom.log`保存实际argv、退出码和输出。
- 接手24来源SHA匹配，39个相关文本来源中38未变，剩余1项仅指定夹具块变化。`source_preservation.json`及 `verified_fixture/` 对照接手原字节，正反向apply-check和实际前向一致，不以候选HEAD为基线、不改上轮累计归档。
- 复用既有DOM/CSS/ECharts与内存API，不读图、不启动服务；地图绘制器/传输仍是既有桩，没有新增物理分类图/完整HTTP/真实原owner/板卡结论。原58项及CPU/A53/中文/控制套件未重跑。

## 精确复现：只跑迁移的一个用例

在f3fb执行，输出目录必须尚不存在；复用本机既有绑定/浏览器，不安装或下载依赖：

```powershell
$env:PLAYWRIGHT_MODULE='C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright'
$env:PLAYWRIGHT_CHROMIUM='C:/Users/86187/AppData/Local/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-win64/chrome-headless-shell.exe'
node --check tools/check_gcs_chinese_dom.cjs
node tools/check_gcs_chinese_dom.cjs --out build/host/result_clear_legacy_fixture_next --grep '^layout/terminal_clear_preserves_history_no_transport$'
```

不要加 `--clear-only`（会跳过layout），无需 `--pending-clear`；最终回执应仅有上述1项。禁止从不完整f3fb启服务、重连/接管、操作板卡/SD/模型或自动App/Build/下载；完整HTTP/原owner/物理PC-DP-板卡及发布另获许可。输入未定、先显示后操作，闭环保留不重训。

收尾仅提交单路径增量归档和必要记录自身差异；确切提交/未提交范围、末次被动状态和双方memory回执见新目录 `commit_receipt.json`、`passive_state_handoff.json`、`memory_sync_receipt.json`。无新可复用坑、依赖/字体/许可或独占skill变更。

---

以下为68358bd对应的上轮原记录；其中“旧夹具尚未迁移”的历史状态现已由本节关闭。

# 清当前任务结果：续改验证与恢复入口

日期：2026-10-12。用户要求收尾交接，停止继续扩展。**这是独立候选的定向离线验证，不是发布、完整服务验收或物理显示结论。**

## 当前目录与提交含义

- 主树：`D:/HSI_AgriEdge`；唯一非运行候选：`C:/Users/86187/.codex/worktrees/f3fb/HSI_AgriEdge`。
- `1b82b29` 是前轮 DP/中文已验独立归档，`4e0393f` 是上轮四路径后端合同及中途记录；两者不是整候选源码提交或发布，不重做原初版。
- 接手先核 `working_changes.json`、`working/`、`backend_inheritance.json`、`verified_backend/`。22 路径 WIP、后端4路径及12个 v8 来源 SHA 匹配后才修改。本轮没有新增来源继承。
- 本轮 **9 路径续改**：5个前端模块、3个 CPU 夹具、1个离线 DOM 夹具；累计清结果自身差异 **24 路径**。基线分别是接手原字节、上轮清结果基线加必要 v8 来源，**不是 f3fb HEAD**。
- 提交仅归档可分离自身补丁/源码快照及必要记录。候选原源码、继承差异和主树原有脏改动不直接混提；不 push。确切提交号与路径见下述 `commit_receipt.json`。

证据根：`report/gcs_roi/20261012_result_clear_candidate/continuation_20261012/`。

## 本轮改动

1. **夹具前提**：probe_canvas 先明确 stopped，再验清零、拒绝 restore 和显式新点；三景 clear_result 的新请求 seq=65535，布局极值仍保留；PAUSE/STOP 校验原调度 ACK，再应用控制，未修改协议时序。
2. **START / 历史**：接受条件在剪枝、S.live 赋值和 newRun 前检查；旧或重复 START 不覆盖历史、不回退当前任务。终态和已接收计数不接受旧摘要倒退；恢复合并而非删除已有缓存。真实新任务独立零缓冲。
3. **DP 回执**：仅认 `clear_result` 新合同，绑定 source、boot/session/task、request_id、nonce 和严格布尔应用标志；HTTP 前事件须在请求身份固定后再次核验，终态不被旧排队/错误事件改写。跨 source 旧异步 success/error/finally 不得干扰新请求；已离开的 boot/session 不由旧 tick/gate 重新授权。
4. **点与显示**：清后旧点无新请求不能上屏；显式选择历史不是授权新点。板端旧 POST 的尾处理不得清掉后来 PC 点的图表；新独立点不恢复区域计数。原 owner 的操作互斥保留，前端程序入口也拒绝 DP 待回执期间 START。
5. **清除意图**：刷新与只读恢复回到等待新任务，保留历史；存储失败拒绝清除。PC 历史可显式查看，但不能代表恢复当前 DP 结果。

原语义不变：只在终态清当前分类图、统计、点卡、进度和摘要，保留原始回执、任务/控制身份及失败证据；运行/暂停拒绝，不隐式 STOP/START。action2、INFO bit5/result_clear、V2 日志保持，旧隐藏回执不追认为新成功。

## 验证与证据口径

| 项目 | 实际回执 |
|---|---|
| 三处修正 CPU 夹具 | probe_canvas PASS；三景 clear_result 3 PASS；model_protocol `display` PASS；`host_fixture/checks.json` |
| 初轮新 DOM RED | 26项7 PASS；包含真实失败，后续夹具前提纠正另留回执 |
| 第二批与夹具纠正 RED | 17项5 PASS；其中新 START 用例需显式 scan，恢复夹具需补非核心 business 端口；纠正后8项仍 RED，证明产品问题，不改产品迎合夹具 |
| 第一轮修复 | `dom_first_fix/`：44/44 PASS |
| 补充身份/异步负例 | `dom_identity_followup/`：12项8 PASS；旧 gate 的4个新负例 FAIL；另有旧点、板端迟到 POST 各1 RED |
| 末轮受影响复验 | `dom_identity_final/`：23/23 PASS，零页面错误、零漏出真实请求、浏览器关闭 |
| 按最新回执合并 | **58项 PASS**，见 `logical_dom_results.json`；不是终版全套重跑，未改链路沿用前次定向 PASS |
| A53 | canvas/display/main/protocol 4项 `-fsyntax-only` PASS；仅 BSP timer 的 pragma note，无 Build/链接/下载 |
| 最终语法 | 5个 JS 模块及离线夹具，共6 PASS；`final_syntax/checks.json` |
| 未变旧结果沿用 | CPU clear9、display_control、三景状态/damage3、后端7方法；源码 SHA 核对不变，无重复旧套件 |
| 补丁 | 9路径续改、24路径累计分别正反向 apply-check + 实际前向原字节 SHA 匹配；仅证明可复用，不等于部署 |

DOM 使用既有 Playwright、真实 DOM/CSS/ECharts 与本机内存 API/事件夹具。app.js 的分发和恢复逻辑被实际执行；媒体只用空白 canvas，不读图；非核心连接/业务/闭环端口是桩。所有 POST/WebSocket 都是内存记录，真实网络路径被拦截，没有启动服务、连接板卡或推理真实模型。

## 未做与下一步

- `layout/legacy_hide_preserves_history_no_transport` 仍有旧隐藏提示断言（“任务继续”），本轮未跑。若继续整理测试入口，只迁移这条过时断言到终态清结果契约；不能据旧历史 PASS 宣称整个现有 DOM 入口全绿。
- 完整服务 HTTP 路由/真实原 owner、物理 PC/DP/板卡联验和发布均未做。f3fb 不含完整运行副本，**不得从 f3fb 启服务**。发布/同步/App/Build/下载另获许可；不要因候选离线通过而部署。
- 输入方案未定，先显示后操作；闭环非核心，保留已有成果、不重训。既有验收矩阵未被本轮收窄。
- 恢复先读主树 CLAUDE.md、CODEX_CONTEXT 顶部及交接；无需重做原 DP/中文初版，也不因换会话重跑58项或旧30/41/21/7/23/119套件。

需要复现被修改的清结果用例时，使用新目录，禁止覆盖原 RED：

```powershell
# 在 f3fb 中，浏览器/绑定路径见对应 checks.json，可通过环境变量复用。
node tools/check_gcs_chinese_dom.cjs --out build/host/result_clear_next --grep '^clear_' --pending-clear --clear-only
# 更窄范围用 --grep 定位实际修改项；CPU/A53 完整 argv 在各 checks.json。
```

## 安全与交接

17:19:53 被动无8765监听/服务/本轮验证助手；所有临时浏览器和 CPU/A53 命令已结束。144个 v8 只读快照路径、140个冻结路径未变。1581仍为 v8 正式源码，3716冻结；不依据本次观测推定下次仍停。

四件套记录入口：`.claude/progress.md`、`CODEX_CONTEXT.md`、双方项目坑、`report/llm_log/20261012_result_clear_continuation.md`、`report/evidence.md`；可访问的双方 memory 及 MEMORY.md 索引另同步。技能目录为独占范围，本轮不擅改；无新增依赖、字体或许可，已验教训先记项目坑，技能提炼留给该目录获授权维护方。
