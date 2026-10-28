# 2026-10-13 C1驱动通过与产品验证边界

**C1_DRIVER_PASS_NOT_PRODUCT_HTTP；仍STAGED_NOT_RUNNABLE。server未导入，44个产品路由NOT_EXECUTED。**

## 授权与差异

用户“继续”仅批准关闭Pydantic v1的cython可选编译态探测，再执行同一个C1一次。只在 `D:/gcs_20261012/sim/host/test_gcs_http_isolated.py` 的 `LimitedIpcGuard.optional` 增加cython；25099→25109字节，新SHA256 `cd135d244f307b28988b54eabf5f64c3bfc96b18dda0619e334e6da235daa87d`。

现有finder抛ModuleNotFoundError，让Pydantic v1走已有ImportError→compiled=False缺省。没有加载真实cython/email_validator、安装依赖或修改site-packages。除该单行声明外字节/AST不变，原绝对禁监听模式、原6个合成请求、标准Proactor、单次自唤醒IPC和最多1工作线程边界均保留。

## 唯一执行结果

- 20:24:47～20:24:48，PID19304，退出0，无超时；仅执行一次。
- 两项驱动检查通过：标准loop及临时监听关闭、计时与取消。
- 原六个合成请求全部通过：同步路由、路径校验、JSON回显、JSON校验、异常处理、FileResponse。合成HTTP=6，产品HTTP/WS=0；这不是产品路由验收。
- 1次socketpair、2次socket.__new__审计、3个登记对象（含accept.return）；全部在补救清理之前关闭。AnyIO工作线程启动1个并已退出，loop关闭、无残留线程，拒绝操作为空。
- FastAPI 0.135.1、Starlette 0.52.1、httpx 0.28.1及AnyIO已导入；cython/email_validator进入optional_features_skipped，无真实模块读取。server未导入、lifespan未启动。
- 唯一测试写入为本轮新证据sandbox/probe.txt。20:26:03被动未见PID19304、匹配进程或8765监听；不推断板卡空闲。

## 证据、复现入口与保留项

证据目录 `report/gcs_roi/20261012_integration_preparation/http_c_driver_cython_20261013_202409/`：authorization、baseline、before/after.zip、c1_cython.patch、pre_run_review、唯一attempt原stdout/stderr/JSON、passive_state及verification。最近一次C1失败三份回执SHA不变；更旧失败/物料/本机基线/夹具未动，不重验旧阶段或全量清单。

以下为**已执行历史命令，不是再次运行的授权**；cwd为本证据目录：

```text
D:\pytorch\python.exe -I -S -B -X utf8 D:\gcs_20261012\sim\host\test_gcs_http_isolated.py --limited-ipc --sandbox D:\HSI_AgriEdge\report\gcs_roi\20261012_integration_preparation\http_c_driver_cython_20261013_202409\sandbox
```

本次运行回执证明C1合成驱动通过；归档和字节核对本身不代替运行。工作提交见本目录commit_receipt.json，收尾与双端记忆见finalization_receipt.json、memory_sync_receipt.json。只提交本轮测试差异归档及必要记录，不混入继承差异、不push；新根不建立.git，不宣称全源冻结或可运行产品。

## 下一步推荐（仅建议，执行仍另批）

用户补充“完成这个继续推荐”，按收尾及建议处理，不作为产品执行许可。推荐下一步确认**完整C的产品server导入隔离与既有44路由HTTP验收范围**，而不是继续增加驱动测试或重复已通过C1：

1. 先只读明确产品导入可能触发的资源、依赖替身及禁止副作用；保留真实FastAPI/ASGI校验栈，不借替身隐藏产品错误。
2. 沿用已有44路由清单及当前标准驱动，列明测试写入沙箱、单次有限IPC/工作线程限制、资源审计与退出回执；不新增测试矩阵、不安装依赖或修改产品。具体方案仍需核对产品实现，不能假定已具备完整隔离。
3. 方案获明确确认后，才执行该产品验证范围；仍在产品导入前设门禁，失败即停，不连带批准D～H。

原失败、旧树、主树产品、用户App、模型出处、本机基线/夹具全部保留。未做服务启停、硬件、Build、下载、重训或发布。C1完成不等于完整C、产品HTTP、真实owner或物理板卡通过。
