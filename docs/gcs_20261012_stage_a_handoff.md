# 2026-10-12 A阶段物料落地交接：STAGED_NOT_RUNNABLE

## 1. 当前状态与授权

**`D:\gcs_20261012` 已按精确清单建立独立字节副本，2026-10-12 20:30:21 完成目标回读校验，停在 `STAGED_NOT_RUNNABLE`。不得从这里启动服务。**

用户在恢复上下文、列明A阶段目标/来源/校验/停止条件后回复“OK”。许可仅包括A：创建该新根、复制清单字节、校验SHA及必要收尾记录。**B～H未获本轮授权，也未实施。** 原方案见 [runtime_layout_plan](gcs_20261012_runtime_layout_plan.md)，准备工作提交 `1c57d47`、交接回执 `f0a0744`；本轮提交号及精确范围见新证据的 `commit_receipt.json`。

新证据目录：[`report/gcs_roi/20261012_integration_preparation/staging_a_20261012/`](../report/gcs_roi/20261012_integration_preparation/staging_a_20261012/)。原目录闭包、原REQUIRES_REVIEW及限定解释、旧FAIL和历史归档全部保留，不改旧回执以适应新状态。

## 2. 实际物料与验证

| 项目 | 实际结果 |
|---|---|
| 最终文件集合 | **1091路径，2,095,032,427字节**；目标文件/目录集合精确匹配，没有额外活动状态或工作区 |
| 未替换基底 | **1055文件来自1581工作文件**，不是主树脏源码或候选HEAD |
| 最终覆盖来源 | **36文件直接取三份已验归档的after成员**；12取1b82b29、23取68358bd、1取b6ec658 |
| 产品/验证边界 | 36仍为**25产品（18服务网页＋7 App）＋11验证**；未增加产品路径 |
| 源端门禁 | **1078既有基底文件SHA通过**；25产品门禁中23个基线SHA通过、2个新增产品源端不存在；清结果CPU测试另核源端不存在 |
| 最终字节门禁 | 36归档after成员SHA通过；复制流SHA与登记一致；**1091目标文件全部回读SHA通过** |
| 独立性 | 所有目标普通文件，链接数均1、文件ID各异；无重解析点、不与既有源文件同一文件，不采用链接或整树拷贝 |
| 工具检查 | 新复制工具**16项合成测试通过**；重解析拒绝用模拟文件属性测试，实际目标另做完整stat检查；不是产品功能测试 |

三个归档整体字节分别与其已提交快照核对，逐成员再按清单登记SHA校验。固定清单 SHA256：

```text
1bd3e92718af621ca796cfc055db24bdf24fde30cfdea457bdd18a902ee4757b
```

每个新目标仅以排他创建方式写一次：**没有先拷旧版本再套modify补丁**。`sim/host/test_gcs_result_clear.cpp` 只新增已验最终测试，未套候选RED起点补丁。复制前复核路径/重解析点/碰撞/可用空间；采用流式字节读取，A阶段另留1 GiB复制安全余量，不将其宣称为后续包、BSP、Build及日志的完整预算。

本轮确实将清单内既有负载从上轮stat检查推进到**字节SHA完整性检查**，但没有解码模型/图像、推理、训练、重导出、功能验收或板测。未重新解释模型出处或重做目录闭包审查。

## 3. 仍然不具备运行/发布资格

- 状态只登记在外部证据 `run_a/result.json`；没有为标记状态向物料根加第1092个文件，也没有改旧目录ACL。`STAGED_NOT_RUNNABLE`是本阶段停点，不是平台、发布身份或运行验收结论。
- 默认发布绑定仍为v8，服务5处捕获默认参数的问题未改；只换CLI `--bundle`不够。源码UNBOUND模板保持正确原字节，不重复修。
- 新包、新ABI4平台/空App均未建立；没有源同步、用户Build、ELF审批、下载或借用旧库。当前用户App `D:\HSI_AgriEdge\build\host\gcs_r1_abi4_vitis` 未覆盖。
- 新活动 `build/host/gcs_roi`、`gcs_uart`、`gcs_network_boot`、`gcs_training` 均不存在；`.git`、新平台/App及拟新发布包目录也不存在。旧owner/boot/session、日志和运行历史没有带入。仅清单中4个HLS run/log作为硬件见证例外复制，其命令字符串未执行。
- 模型元数据保留原字节：既有15处绝对路径/11目标没有重写。条件性checkpoint选择仍可能读取旧树；**不能宣称完全自包含，更不能删除3716**。97项运行/恢复成果按清单保留，不重训。
- f3fb仍保留为原产品源码候选，仍不完整、禁止启服务；新根仅为A阶段已暂存物料，不是新增已验运行候选。1581=v8、3716冻结不动；主树旧差异、候选源码及12项来源继承保留。双树只有必要当前交接前缀更新。

## 4. 证据与复核入口

| 文件 | 用途 |
|---|---|
| `authorization.json`、`authorization_text_resolution.json` | 用户A许可与限定范围；初始中文问题字段曾受PowerShell ASCII管道影响，原记录保留、用UTF-8独立纠正，ASCII许可字段和“OK”未变 |
| `stage_materials.py`、`test_stage_materials.py` | 仅标准库的一次性复制/只读校验工具与合成门禁测试 |
| `test_red.json`、`test_red_subject.py.txt` | 实现前缺少复制能力的预期RED，原样保留，不是产品失败 |
| `test_implementation_attempt_01.json` | 16项合成检查PASS、工具和测试SHA、标准库导入清单 |
| `run_a/source_preflight.json` | 逐文件源端SHA/不存在门禁、归档after来源及磁盘快照 |
| `run_a/copy_journal.jsonl` | 1091次实际排他写入的源选择、SHA、文件状态回执 |
| `run_a/target_verification.json`、`run_a/result.json` | 1091目标回读SHA、精确集合和最终停点 |
| `execution.json` | 实际命令、有限复制进程PID/退出码/输出；进程已退出，无续跑 |
| `verification.json`、`protected_before_records.json` | 回执交叉检查、自身工具SHA、受保护Git/记录状态检查；非旧功能套件复跑 |
| `commit_receipt.json`、`finalization_receipt.json`、`memory_sync_receipt.json` | 自身提交、收尾和双向记忆同步回执 |
| `passive_state_start.json`、`passive_state_final.json` | 被动端口/工具进程状态，不代表板卡空闲 |

需要再次核验**A原样物料**时，可在主树执行下列只读入口；本轮最终回读已由复制工具完成，不为换对话惯性重跑：

```powershell
D:/pytorch/python.exe -I -B report/gcs_roi/20261012_integration_preparation/staging_a_20261012/stage_materials.py --verify-staged-readonly
```

真实执行命令保存在 `execution.json`，**不得重跑 `--execute-authorized-a`**：目录/回执存在会拒绝，工具不提供自动合并、续跑或清理。旧布局审计中的 `target_absent` 此时应失败，这是历史实施前条件已经改变，不得修改旧证据凑PASS。B若将来获准修改新绑定，也应另存before/after，不能覆盖本轮A字节见证。

## 5. 下一步与保护边界

下一阶段最多另请用户批准**B：只在新根进行最小默认绑定及定向验证，独立归档新增差异**。隔离完整HTTP、新冻结、新平台及源同步、用户Build/ELF审查、服务/真实owner/PC-DP-板卡窗口和发布，继续按原方案C～H分别授权；不自动串行。

输入方案未定，先显示后操作；闭环非核心，保留成果、不重训。原58项、旧单夹具1/1、CPU/A53、中文/控制旧套件未重跑；未导入真实server、HTTP、启停/重连/接管服务、操作板卡/SD/真实模型、读图、同步App、Build下载或重建HLS/Vivado。复制后已有用户XSCT/hw_server保持不动，末态看被动回执。

本轮收尾只提交新工具、文档、复制证据和共享记录的自身前缀；**不是完整候选源码提交或发布**，不push。先前未提交差异和本轮记录基线/合成夹具等未提交支持文件如实保留。共用进度、主树/候选快照、协作/evidence及双方可访问项目memory和MEMORY索引同步；无新增可复用坑，复用既有Windows补丁长度/UTF-8管道经验，不重复登记，不改独占skill、依赖、字体或许可。
