## 2026-10-11 19:59 更新：候选已提交，恢复入口已迁移

源码/证据候选 `cb3f9b6` 已本地提交，未 push。最新状态、定向验证与剩余任务见 [以太网候选检查点交接](gcs_20261011_ethernet_v4_checkpoint.md)。以下 19:22 的“未提交/待定位”是保留的历史，不是当前状态。

# 2026-10-11 以太网取证候选：待集中提交，下一轮继续验证

## 当前停点（优先于 17:46 及以前记录）

**最新指令：用户要求立即给出交接，把尚未完成的工作留到下一轮。因此本轮未暂存、未 commit、未 push；HEAD 仍为 `195682b`。集中提交审查只做了状态盘点，不能称已完成。**

- 用户最新要求：串口不再作为正常使用/验收前提；本轮先修复并交接，完整测试放到新对话。随后明确要求检查、提交前几轮未提交内容。允许本地检查点 commit，不 push，不使用 goal/token 预算。
- 接手时 HEAD 为 `195682b`（2026-10-11 09:52），此后第一轮 ABI4、硬件计数器、启动身份、发布审查、SD 准备及本轮以太网候选尚未提交。下一轮应先审查相关源码、测试、文档和证据，再集中本地提交；Vitis/Vivado 生成目录、旧 ELF、会话导出及第三方资料不直接纳入。
- **这是未完成全套回归的候选检查点，不是完整去串口验收通过，也不是可直接重新 Build/部署的正式发布。**

## 已实现并落盘

1. App 的完整 BUILD 行进入有界 `BoardLog`，不再被旧 160B 串口输出上限截断；保留启动及最近四个任务的真实记录，溢出显式失败，维护串口 TX 默认关闭。
2. 新只读 UDP 页回读核验 boot/session/task、偏移、容量、CRC 和完整原始流；任务回读使用现有唯一 UDP owner，不另开连接接管。GET、页面恢复和历史读取不发设备命令。
3. 明确选择 JTAG/SD 后才进行以太网启动核验：完整 BUILD/SD journal/READY 与实时空闲 INFO 对齐，旧 boot、活动任务、发布不符不放行。扫描中可以显式再次刷新；不能把网络无响应称作 SD 仍在加载。
4. 前端正常入口改为 `connection.js`，不再加载 `uart.js` 或展示串口选择。新版静态页遇到旧服务缺少 `board_records_protocol=1` 时禁用接入，不能靠刷新页面部署新版。
5. 新增显式 `POST /api/run/{rid}/board/records`；当前终态任务在原 owner 上回读，历史任务仅重放保存的页。计时 GET 保持被动。任务验收 ZIP 包含原始 `board_log/packets.jsonl`、二进制文本、CRC/SHA 回执和 ELF 绑定，不再要求 UART，也不在失败时退回 UART。
6. `tools/gcs_release.py` 的私有源清单已加入 `roi_board_log.h`（共 35 个 App 源/头）。**新发布包未冻结，旧 v3 包、平台和 ELF 未改、未同步。**

## 本轮验证（离线，非板上结果）

- 17 项 PASS：`test_gcs_network_records` 4、`test_gcs_boot_http` 8、`test_gcs_board_log` 5。
- 12 项语法检查 PASS：3 个新/受影响 JS 的 `node --check`，9 个 Python 文件 AST。
- 新测试先复现任务打包仍读 UART、缺少显式记录 API 的失败，再修复通过；原 RED 日志保留。
- 本轮未执行完整浏览器回归、全体 host/C++/A53 检查、App Build、下载或实机验收。不得把此前候选报告或本轮模拟数据标为板上 PASS。
- 证据：`report/gcs_roi/20261011_ethernet_handoff/`；本轮工作日志：`report/llm_log/20261011_ethernet_records.md`。

## 下一轮按此顺序继续（不要重读整份会话）

1. 先核 `git status`/HEAD（应仍为195682b）及当前服务；读本页、`CODEX_CONTEXT.md` 顶部即可恢复。按用户已给授权审查前几轮和本轮未提交源码/文档/证据，列明确路径后本地commit，不push。盘点在`build/host/gcs_ethernet_resume_01/untracked_review.json`；大量Vitis/Vivado生成目录、旧ELF、会话导出及第三方资料留原位，不直接git add .。
2. **先补剩余迁移边界，再声称完整去串口**：`tools/gcs_sd_boot_verify.py` 仍以 `--uart` 为入口，`tools/gcs_model_verify.py` 仍有可选 UART 关联；核对模型专用操作、恢复后回读、启动早期无网络错误的真实可观测性。不能用任务取证 17 PASS 代替这些验证。
3. 更新浏览器旧串口测试夹具：`tools/check_gcs_scene.cjs`、`tools/check_gcs_round1.cjs` 仍访问 `UartPanel`/`#uart-*`/`#sd-connect`，需迁到新显式入口，检查取消无流量、旧服务禁用、扫描未授权、JTAG/SD如实选择及错误不留旧数据，再跑 headless DOM/布局回归。
4. 定向检查真实 owner 终态回读/PROBE 后重读/恢复/任务保留槽。一次前置基线的 `test_gcs_model_link.ModelLinkTests.test_query_upload_activate_tasks_probe_and_history_one_socket` 等待 PROBE 到 done 失败，尚未完成定位；优先核 ABI4 attention 夹具，不忽略、不宣布全套 PASS。
5. 跑相关 Python/C++ 协议/BoardLog/runtime/A53 语法与发布布局回归，补 `tools/test_gcs_round1.py` 的新测试入口。已有 `sim/host/test_gcs_board_log.cpp`，但本轮续接未重跑。数据/证据只用隔离 `build/host` 目录，不连接真实板卡。
6. 检查完整门禁后才准备全新 v4 源码包；原 `gcs_release.py` 默认 BUNDLE 仍是 v3，不能覆盖该包。下一轮另选新目录并核默认入口/绑定/生产门禁。用户确认一次源码同步窗口后由用户 Build；平台/HLS/XSA不因本次去串口重复重建。
7. 新服务必须另获切换窗口，不可直接结束原服务。A～G/T 实机欠项全部保留；全部通过才进入第二轮，性能优化后置。

## 现场与禁止事项

- 最后只读核实（2026-10-11 19:15）：原 GCS PID **35444**，`127.0.0.1:8765`，板卡未授权/无活动 owner；UART `active=false`、端口已释放、TX=0；旧服务无 `board_records_protocol` 字段。未重启服务。
- 本轮临时测试均已退出，无新构建后台；不要结束用户原 GCS 或 IDE。
- SD 已安装的数据/模型和双 journal 保留。实机已使用 `boot=228ce0e9 / generation=1`，**绝不重拷初始化 journal、手填 boot 或回退身份**。`BOOT.BIN` 尚未完成，SD 独立冷启动仍未验收；原 PMU-FW 警告也未闭环。
- 未触碰正在运行的板卡、SD、用户 Vitis App、既有平台/XSA/ELF；未改 Codex 上下文设置。

## 最短恢复提示

> 接手 D:\HSI_AgriEdge，按 CLAUDE.md 和 docs/gcs_20261011_ethernet_handoff.md 接着做以太网候选的剩余迁移与回归。HEAD仍195682b、尚未暂存或commit；先按授权审查并提交前轮/本轮相关改动，不覆盖生成物，不启动重复服务。17 项定向测试通过不等于全套通过；优先处理旧浏览器串口夹具、模型/SD验收器入口和 owner/恢复取证，再完成 host/C++/A53/浏览器回归与新包准备。原 GCS 最后 PID35444/8765，平台/HLS/XSA/ELF及已使用的 SD journal 不动；用户另行确认同步、Build、部署和实机操作。允许本地 commit，不 push，不使用 goal/token 预算。
