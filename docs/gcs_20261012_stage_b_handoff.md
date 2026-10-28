# 2026-10-12 B阶段最小默认绑定交接：仍不可运行

## 1. 结果与授权

用户在明确列出“新根一个产品文件、一个新增定向测试、独立归档及必要收尾；C～H不授权”后回复“继续”。本轮仅实施该B范围：**新默认绑定定向验证通过，运行状态仍为 `STAGED_NOT_RUNNABLE`，不得启服务。**

本轮操作的物料根为 `D:/gcs_20261012`，不是已验运行工程；f3fb保留为原产品源码候选，仍不完整、禁启。A阶段已经完成，不得重跑复制。A工作提交 `4c0f0e7`、最终回执提交 `9d22839` 及原证据保持原样；本轮实际提交见B证据 `commit_receipt.json`，不是整候选源码提交或发布，不push。

## 2. 精确写集与来源

| 路径（相对新根） | 本轮变化 |
|---|---|
| `tools/gcs_release.py` | 只替换一个BUNDLE路径字面量：`ROOT/build/host/gcs_r1_abi4_release_v8` → `ROOT/build/host/gcs_r1_abi4_release_dpzh_clear_20261012` |
| `sim/host/test_gcs_release_binding.py` | 用户明确许可后新编写的139行/6644字节最小测试；A中不存在，不复制1581、主树脏测试或候选测试 |

产品before SHA256：`56748c27885f32d63973ae929988af7eee99563647d44b59a6636cece6ab66f1`；after：`ea4dccee48c360f8e69c808332dd926d26691341571634c89b3a28a4f443598b`。测试SHA256：`96a6995e9d54735f7ee5c05d9f9c2cbc02340e76c9327a0916757315dc59d435`，RED到GREEN未改测试。

除该字面量外，产品原字节完全不变。`inspect()`和`audited_elf()`在模块定义时捕获新默认，CLI亦使用新默认；服务五处省略bundle参数的调用只做AST核对，`gcs/server.py`未修改、未导入。`src/ps/s2c_roi_app/roi_release.h`的UNBOUND模板、source/asset/ELF门禁未改。没有运行后改全局、CLI冒充服务切换或旧包回退。

新包路径只被指定，**目录、manifest、身份和approved ELF均未生成**。这属于原36最终路径之外的B独立差异，不回填A白名单，不按候选HEAD认领。

## 3. 验证口径

- 修改前：7个测试方法运行完成，5处断言因旧v8默认值而预期RED；原输出保留。修改后同一测试文件 **7/7 PASS**，退出码0，2026-10-12 21:09:16完成，进程已退出。
- 覆盖：新根导入来源；模块/函数捕获默认；缺manifest拒绝且不回退旧包；CLI默认及显式参数分发；服务五处静态调用；ROOT/build/host越界拒绝；已有目标在硬件/写入前拒绝。
- 负例为内存替身，不读取真实包、ELF、模型或硬件。测试仅导入新根发布工具及其board_release合同模块；server只读AST。使用Python `-I -B`，设有拒绝写盘、进程启动和网络操作的审计钩子，不安装依赖。
- 产品原字节比较确认仅一个字面量变化；server、合同模块和UNBOUND的定向SHA仍匹配A记录。新根原1090个未改文件的元数据未变，无额外目录、字节码或运行状态文件。
- 新根现为 **1092文件、2,095,039,088字节（本轮元数据统计）**：A的1091文件，加6644字节测试，原产品增加17字节。**不是重跑1092个文件的负载SHA验证**。A原1091文件/2,095,032,427字节见证仍是历史原样物料结果。
- 独立before/after及补丁正反向check、实际前向原字节复现通过。首轮夹具因系统Git `core.autocrlf=true`变成CRLF而未通过字节等值；失败夹具/回执保留，另建夹具用命令级 `core.autocrlf=false/core.eol=lf`复核，未改全局配置、登记SHA、产品或测试。
- 原58项、旧单夹具1/1、CPU/A53、中文/控制套件未重跑；不宣称完整source/asset/ELF门禁、完整HTTP、产品功能、模型语义或板测重新通过。

仅需要复现本轮绑定检查且授权边界仍满足时，入口为：

```powershell
D:/pytorch/python.exe -I -B D:/gcs_20261012/sim/host/test_gcs_release_binding.py
```

不因换对话惯性复跑；不要调用发布工具的真实prepare/audit-current流程代替该隔离测试。

## 4. 证据与失败保留

新证据：[`report/gcs_roi/20261012_integration_preparation/binding_b_20261012/`](../report/gcs_roi/20261012_integration_preparation/binding_b_20261012/)。

| 入口 | 用途 |
|---|---|
| `authorization.json`、`preflight.json` | B许可、4项定向文本SHA、新测试不存在门禁、A回执保护；未重审目录闭包 |
| `before.zip`、`after.zip`、`binding_delta.patch`、`archive_manifest.json` | 仅B的1 modify + 1 add原字节、SHA和可复现补丁 |
| `test_red.json`、`test_green.json`及stdout/stderr | 同一测试的真实前后结果、命令、PID及退出状态 |
| `edit_receipt.json`、`verification.json` | 精确字面量差异与验证边界、保护检查；不是发布批准 |
| `editor_transport.json`、`archive_attempt_01.json` | Windows补丁参数传递失败及CRLF夹具失败，原样保留，不冒充产品失败或隐藏重试 |
| `record_baseline.json`、`record_updates.json` | 共享记录自身前缀与原差异分离；本机基线归档不混提 |
| `commit_receipt.json`、`finalization_receipt.json`、`memory_sync_receipt.json` | 精确提交、收尾及双方可访问memory/索引同步回执 |
| `passive_state_start.json`、`passive_state_final.json` | 被动OS快照，不代表板卡空闲 |

A的11个受保护回执SHA保持不变；未覆盖A工具/日志/归档，未改旧target_absent条件凑PASS。新根B后已不是A原样字节集合，不能拿A原样校验器要求它仍全量匹配A。

## 5. 剩余工作与停点

**本轮到B结束，C～H仍需各自明确授权，不自动串行。** 下一最多先列明C的导入前隔离方案及合成输入/内存owner范围，再请用户确认；不得先导入真实server再隔离。

- C隔离完整HTTP、D新冻结、E用户新建ABI4平台/空App及源同步、F用户Build/新ELF审查、G服务/真实owner/新boot/用户下载及PC-DP-板卡联验、H发布，继续按原布局方案分别授权。
- 1581=v8与3716冻结不动；f3fb源码及12来源继承保留。主树产品源码、用户App `D:/HSI_AgriEdge/build/host/gcs_r1_abi4_vitis` 不动。仅必要交接记录同步双树。
- 新活动history/UART/network_boot/training和平台/App均未建立；原4个HLS run/log仍只是A清单硬件见证。没有借旧库、源同步、Build、下载、SD操作、HLS/Vivado重建或服务启停/重连/接管。
- 模型元数据15处绝对引用/11目标保持原字节，条件性checkpoint仍可能访问旧树；非完全自包含，3716不可删除。输入方案未定，先显示后操作；闭环非核心，保留成果、不重训。
- B失败不自动覆盖/删除新根，也不操作旧服务“回退”；保留before/after和原失败，另获相应授权。旧v8配套仍独立保留。

收尾只提交已验B归档、新文档及共享记录的自身前缀；不建立新根.git，不混入完整源码或原未提交差异。复用既有Windows参数/换行坑，本轮无新增坑，没有技能、依赖、字体及其许可变化。
