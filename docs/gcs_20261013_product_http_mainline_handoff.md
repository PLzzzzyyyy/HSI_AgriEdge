# 2026-10-13 主线推进与产品HTTP交接

## 先读这一条：不用再逐项请示

用户最新明确：既定软件主线内直接推进本地开发、隔离测试和必要修正，不再每个小改动/可选导入/一次复验都询问“授权”。用户主动说保存/交接时，才收束并完成四件套。本轮正是用户要求准备新对话；**不是缺许可而阻塞**。该约定已写入双方CLAUDE.md，覆盖较早交接中当前C软件主线的逐项“另批”措辞，旧记录保留历史。

保护对象与技术门禁仍有效：原失败、旧树、主树产品、用户App、模型出处、本机基线/夹具不动，不把软件测试变成真实服务、板卡、Build/下载或发布操作；不自动push。

## 当前准确状态

- 主线：完成C阶段产品server导入隔离与HTTP合同验证，不是重新开发驱动。
- C1已通过：工作提交76d21ee，原收尾HEAD7e2fbfc。20:24:48/PID19304退出0，2项驱动检查+原6个合成请求通过；3socket补救前关闭、1工作线程退出、loop关闭。
- 本轮只读源码/AST，没有产品或测试改动，没有产品模块导入/HTTP，也没有重新执行C1。无本轮后台任务；不重新推断机器或板卡空闲。
- 新根 `D:/gcs_20261012` 仍STAGED_NOT_RUNNABLE，44产品路由NOT_EXECUTED。C1 PASS不是完整C、产品、原owner或板测通过。
- server.py SHA256：`5b32dda8ebb3357360d954b6fba0e86dabd22fcb9b3a12673ee3683894a7d3d2`。
- test_gcs_http_isolated.py（25109B）SHA256：`cd135d244f307b28988b54eabf5f64c3bfc96b18dda0619e334e6da235daa87d`。

## 已核清的静态边界

| 位置 | 静态事实与实施注意 |
|---|---|
| server.py:54；tools/gcs_release.py:60–73 | 模块级runtime_assets遍历并哈希产品/运行资源；不能先真实调用再替换返回值。 |
| server.py:34–57；engine.py:11–18、204–210 | engine会导入Torch/模型模块，Engine构造查询CUDA；必须在其真实导入前切断模型/设备边界。 |
| server.py:95–133 | State构造进行discover_board_exports和board_history.load_all，扫描模型及历史任务；只禁lifespan不够。 |
| server.py:146；uart_capture.py:125–159 | Capture构造读取_last_settings，扫描capture会话JSON；不得碰真实UART历史/端口。 |
| scene_input.py:20–23；board_agri.py:183–209 | InputReader/ParcelStore构造仅路径/锁；后续请求才涉及数据读取、mkdir/fsync/os.replace。C1现有护栏禁止mkdir/rename，产品模式须精确约束到新证据沙箱。 |
| server.py:221–232、1171–1182 | startup创建sender/ticker，main启动浏览器定时器和Uvicorn；HTTP合同测试不调用这些入口或/ws。 |
| server.py:522–610 | 验收端点延迟导入gcs_scene_verify/gcs_probe_verify/gcs_task_verify，并写JSON/CSV/ZIP；必须显式处理边界，不能伪装成真实验收。 |
| server.py:742–752、828–856、870–883 | 业务元数据读取palette/类别JSON；报告和指标端点写文件；真实处理器及路径/身份校验不能被替换掉。 |
| server.py:26；analysis.py、board_metrics.py | NumPy为server直接依赖，分析/指标还引入SciPy；C1名单不含这些包。本机NumPy文本版本1.26.4且有OpenBLAS DLL，但本轮未加载/验证它们。不得直接放开整个site-packages。 |

已重新用AST比对原route_plan.json：**44路由一致，26 GET / 17 POST / 1 PUT**。原附加入口为/web选定文本、/openapi.json、/docs、/docs/oauth2-redirect、/redoc；/ws、startup/shutdown常驻循环、真实owner/模型/ELF验收仍不在此软件HTTP范围。现有路由及其调用摘要已保存，下一轮不必重新全篇阅读。

## 新对话直接继续的工作

1. 在 `D:/gcs_20261012/sim/host/test_gcs_http_isolated.py` 扩展产品HTTP隔离模式，复用现有标准Proactor、单次自唤醒IPC、最多1个AnyIO工作线程。不另造驱动、不重跑独立C1或A/B/旧套件，不覆盖原模式与失败证据。
2. **先完成导入前隔离，再导入server**：明确Engine/模型发现、设备/串口/历史/data owner、发布资源与延迟验证器的合成依赖接口；精确列出可读源码/文本和新沙箱读写。不能先导入真实engine或server再patch。
3. 保留真实server处理器、FastAPI校验、中间件和响应序列化；替身仅限外部边界，所有合成身份/产物显式HTTP_CONTRACT_ONLY，不能以替换处理器或放宽真实资源换PASS。NumPy/SciPy及原生库初始化边界、细化夹具和部分延迟导入处理仍待实施判断，**不是已完成的隔离方案**。
4. 隔离门禁就位后，直接实现并运行已有44路由及原附加入口的HTTP合同验证；在既定边界内按真实失败定向修正和复验，不再每一步询问用户。不得把统一404/409或替身自身断言冒充真实处理器的完整覆盖。
5. 每次执行保留原始输出、作用域、源hash、进程及资源关闭回执；软件结果仍与真实服务/硬件/App/发布区分。当前这份交接不启动上述执行。

## 恢复与记录入口

- 当前快照：主树CODEX_CONTEXT.md顶部、.claude/progress.md；双方CLAUDE.md已更新推进节奏。
- 本轮静态记录：`report/gcs_roi/20261012_integration_preparation/http_c_product_handoff_20261013_205645/static_inventory.json`（44路由、调用、延迟导入、20个已读取源码快照；不是全量物料冻结）。
- 流程原话：同目录session_scope.json；自身记录差异：record_updates.json；提交与双端记忆回执收尾写入同目录。
- 既有C1运行证据：`report/gcs_roi/20261012_integration_preparation/http_c_driver_cython_20261013_202409/attempt_01.json`。
- 原44路由计划保留：`report/gcs_roi/20261012_integration_preparation/http_c_20261013/route_plan.json`。

本轮只提交自己的静态交接、共用规则和必要记录，不夹带继承差异。双方项目记忆/索引同步为“主线直接推进，当前按用户要求交接”，不是待授权。
