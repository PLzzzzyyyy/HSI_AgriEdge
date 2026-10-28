# 2026-10-13 C1：标准Proactor有限IPC，登记检查停止

## 结果

**C1_DRIVER_STOP；仍STAGED_NOT_RUNNABLE。未完成C1，更未完成产品HTTP或板测。**

用户要求减少额外测试和重复检查，并明确同意标准asyncio仅为自唤醒进行一次有限回环IPC。范围：产品0修改、扩展现有1个测试、最多1个AnyIO工作线程、独立证据；不导入server，不启HTTP服务，不触板卡，结束后停止。

## 唯一执行

- 时间：2026-10-13 19:38:30；PID51600；退出1，未超时，进程已退出。
- 标准Proactor事件循环已构造。实际获准的bind/listen/connect/accept各调用1次；临时监听地址127.0.0.1:50430。这不是“绝对无bind/listen”，也不改变原C的失败结论。
- 新检查器只收集socket.__new__事件，记录到2个对象；`socket.py:295-296` 的accept用已有fd封装返回socket，当前注册器未登记它。预设3个对象的断言因此停止，不能说成产品失败或标准驱动不兼容。
- 计时/取消及6个合成ASGI请求均未到达。FastAPI、Starlette、httpx、AnyIO和server均未导入；工作线程0，HTTP/WS=0，44个产品路由仍NOT_EXECUTED。
- Runner已关闭循环，2个已登记对象已关闭，PID已退出。原回执all_created_sockets_closed只覆盖登记集合，不是接受端独立登记/关闭证明。标准库关闭路径负责接受端，但本次缺少完整逐对象回执。
- 19:39:30被动快照未见8765监听或筛选的相关进程；不证明板卡空闲。没有第二次执行、修后重跑或放宽护栏。

## 变化与复现入口

仅修改 `D:/gcs_20261012/sim/host/test_gcs_http_isolated.py`，6948→23950字节；新SHA256为 `834b680ca98bbc941ae248d1ac74ea36deaedd0e93e7c62387d9d2ca2cc31af7`。原PreimportGuard、StandardDriverPrerequisite及main定义保持；新增显式limited-ipc入口，默认入口仍是原绝对禁监听前置项。本修订保留已知登记问题，不得惯性重跑。

具体命令、cwd、PID、原输出见证据 `report/gcs_roi/20261012_integration_preparation/http_c_driver_20261013_193125/attempt_01.json`。执行方式仍为同一Python的 `-I -S -B -X utf8`，追加 `--limited-ipc --sandbox <本轮独立空临时根>`。后续执行需要重新确认同一C1范围，不复制现有sandbox凑新输入。

before/after为唯一测试原字节，补丁正反向检查及实际前向复现通过；仅证明归档可复现。5个指定保护文本和7个原C证据文件与本轮基线一致，没有重做A/B、旧套件、目录闭包或全量物料SHA。

## 下一步——只修一个检查器问题

登记获准accept返回对象，按身份去重；分别报告socket.__new__事件数量、实际登记对象及关闭结果。再明确批准同一C1的一次复验，不新增测试矩阵，不改驱动，不修改产品。当前没有实施该修复。

C1通过后仍停在产品导入前；完整服务替身、44路由及静态/文档入口另行落实。模型/输入/history/ParcelStore/UART/transport/UDP/发布读取/真实文件响应须先隔离。合成材料只标SYNTHETIC / HTTP_CONTRACT_ONLY；不代表模型语义、approved ELF、原owner、板测或发布。

D冻结、E新平台/App与源同步、F用户Build/ELF、G真实owner及上板窗口、H发布继续分别授权。1581、3716、f3fb原源码继承、主树产品和用户App保留；模型出处未改，非自包含。无依赖安装、HLS/Vivado重建、下载、服务接管、重训或发布。

## 收尾

只提交本次单文件差异归档、独立证据、新文档和共享记录的自身前缀，不提交继承差异，不push，不在新根建立.git。本机记录基线及补丁夹具留存不混提。共用进度、双树快照、协作/evidence与双方项目memory/索引同步；新增坑仅为审计事件数与accept对象登记不同。Windows参数/编码旧坑不重复登记，没有独占skill或许可变化。提交与记忆回执见本证据目录。
