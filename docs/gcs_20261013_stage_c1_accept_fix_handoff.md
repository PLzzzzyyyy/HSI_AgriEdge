# 2026-10-13 C1接受端登记修复与当前停点

**登记修复已验证；C1整体仍STOP，产品HTTP未执行，新根仍STAGED_NOT_RUNNABLE。**

- 用户只批准修accept登记、复验同一C1。标准Proactor、单次自唤醒IPC、最多1个工作线程及原6个合成请求保持；本轮未改变依赖/可选名单。
- 唯一复验于19:55:28结束，PID21848，退出1。标准loop及临时监听关闭检查、计时/取消检查通过。2次socket.__new__审计与3个实际登记对象分别报告；接受端来源accept.return，3个对象均在补救清理之前已关闭。上轮漏登已解决。
- 新停点：FastAPI导入时查询email_validator，被现有名单拒绝。`D:/pytorch/Lib/site-packages/fastapi/openapi/models.py:16-23` 已有try-import/except ImportError降级；不能把此拒绝当成必需依赖缺失。没有安装、放宽名单或再次运行。
- Starlette、httpx、AnyIO已载入；FastAPI导入未完成。server未导入，合成和产品HTTP/WS均0，工作线程0；循环关闭、进程退出。19:56:34被动未见8765监听及匹配进程，不证明板卡空闲。

## 差异与证据

只修改 `D:/gcs_20261012/sim/host/test_gcs_http_isolated.py`，23950→25080字节；SHA256 `22b298f551e10028fc7b626f851fd789764e0ee08296627765c6574d91cd17f1`。原前置模式、6个合成请求及依赖名单的AST不变；仅加入对象身份去重/接受端登记、单独审计计数和逐对象关闭回执，补救关闭不能掩盖关闭失败。

证据：`report/gcs_roi/20261012_integration_preparation/http_c_driver_fix_20261013_195341/`，含授权、before/after、`c1_fix.patch`、唯一attempt原输出及verification。补丁正反向与实际字节复现只证明归档；原C1失败3个文件的SHA保持。没有重跑旧阶段、旧套件或全量物料检查。

## 下一最小范围

只明确把不测的邮件校验列为关闭的可选特性，让框架走已存在的缺省分支；不是允许真实email-validator/DNS资源，也不是安装依赖。另批后仅复验同一C1，不增加用例、换驱动或启动产品导入。本轮尚未实施这一修改。

44个产品路由仍NOT_EXECUTED；完整服务导入隔离与HTTP是后续工作。D～H各自另批；旧树、主树产品、用户App、模型出处、原ERROR及本机夹具保留。没有服务启停、硬件、Build、下载、重训或发布。

收尾只提交本次测试差异归档和必要记录，不push、不混提继承差异；双树快照、共用进度、坑补记及双方memory/索引同步。提交见本证据目录回执。
