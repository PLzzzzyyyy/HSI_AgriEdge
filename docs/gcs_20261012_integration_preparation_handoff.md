> **2026-10-12 后续只读方案已补齐：** 目标目录、1091路径物料闭包、平台/BSP与历史隔离、回退及分段许可见 [runtime_layout_plan](gcs_20261012_runtime_layout_plan.md)。仍未创建运行副本或改产品/绑定；下文及原证据作为前轮历史保留，不改原REQUIRES_REVIEW。

# 2026-10-12 集成准备交接：清单已核，未建立完整运行副本

用户在只读准备过程中要求交接，停止继续扩展。本轮只核对来源、依赖、发布绑定与回退点，整理后续实施/验收入口；**没有创建或覆盖运行副本，没有改产品、导入完整服务、跑HTTP、启服务、接板、同步App、Build、下载或发布。**

## 1. 当前结论与恢复入口

- 主树 `D:/HSI_AgriEdge`；唯一产品候选仍为 `C:/Users/86187/.codex/worktrees/f3fb/HSI_AgriEdge`。1581是v8正式源码树，3716冻结；两者未改，f3fb仍禁止启动服务。
- [最终来源清单](../report/gcs_roi/20261012_integration_preparation/integration_manifest.json)：按已验归档收敛为 **36个最终路径 = 25个产品路径（18服务/网页 + 7 App源）+ 11个验证路径**。全部最终SHA匹配归档；25个产品的最早before均匹配v8基线。12个v8来源继承也匹配，不能再次认领或重复叠加。
- [依赖清单](../report/gcs_roi/20261012_integration_preparation/dependency_inventory.json)：v8的37 App源/112资产共149条文本SHA核对匹配。旧936项依赖中，97项运行依赖、839项已有硬件见证均存在且大小符合旧清单；这些负载本轮**只查存在性/大小，不重读模型、图像、cube或硬件负载内容**，不能称936项内容重新验收。f3fb的97项运行依赖缺86项，仅11项存在且大小匹配。
- 仅应用现有产品白名单时，App仍37源，运行资产清单预计112→114；新增的是 `gcs/display_labels.py` 和 `gcs/web/class_labels_zh.json`，既有动态枚举会纳入。**这不是已经生成新发布包**，未来默认绑定修改也尚未实施。
- [原始审查](../report/gcs_roi/20261012_integration_preparation/audit_summary.json)保留 `REQUIRES_REVIEW`，原因是一个验证文件的before不属于v8；已在[范围复核](../report/gcs_roi/20261012_integration_preparation/review_resolution.json)定位并制定严格处理规则，未把原始标志改成PASS。
- 本轮未重跑原58逻辑项、单夹具1/1、CPU/A53、中文/控制套件；也没有增加HTTP/真实owner/物理PC-DP-板卡通过结论。已有矩阵及未验项不缩减。

## 2. 归档边界与准确迁移范围

`1b82b29`：原DP/中文已验归档；`4e0393f`：后端4路径中途归档；`68358bd`：清结果9路径续改/累计24路径；`b6ec658`：最后单夹具增量。它们都不是完整候选源码提交或发布。本次按DP累计25、清结果累计24、最后单夹具三层取每路径最新已验after，相关后端不再把4e0393f重复apply一次。

未来应使用**完整v8来源基底 + 下列已核最终文件白名单**，逐路径校验before/after与目标边界。不能拿f3fb HEAD或全部脏差异代替白名单，也不能整树复制f3fb：它的 `gcs/server.py`、`tools/gcs_release.py` 与v8不同，`tools/gcs_release_update.py` 缺失。

### 产品25路径

```text
gcs/board_agri.py
gcs/board_display.py
gcs/board_link.py
gcs/board_task.py
gcs/display_labels.py
gcs/web/agri.js
gcs/web/app.js
gcs/web/board.js
gcs/web/class_labels_zh.json
gcs/web/connection.js
gcs/web/core.js
gcs/web/gt_compare.js
gcs/web/index.html
gcs/web/loop.js
gcs/web/panels.js
gcs/web/panels2.js
gcs/web/style.css
gcs/web/timing.js
src/ps/s2c_roi_app/main.cpp
src/ps/s2c_roi_app/roi_canvas.cpp
src/ps/s2c_roi_app/roi_canvas.h
src/ps/s2c_roi_app/roi_display.cpp
src/ps/s2c_roi_app/roi_display.h
src/ps/s2c_roi_app/roi_labels.h
src/ps/s2c_roi_app/roi_protocol.cpp
```

### 验证11路径（不自动算运行资产）

```text
sim/host/test_gcs_chinese_canvas.cpp
sim/host/test_gcs_chinese_report.py
sim/host/test_gcs_display_control.cpp
sim/host/test_gcs_model_protocol.cpp
sim/host/test_gcs_probe_canvas.cpp
sim/host/test_gcs_result_clear.cpp
sim/host/test_gcs_result_clear.py
sim/host/test_gcs_scene_canvas.cpp
tools/check_gcs_chinese_dom.cjs
tools/check_gcs_chinese_names.cjs
tools/generate_gcs_dp_labels.py
```

**单独处理的来源例外**：`sim/host/test_gcs_result_clear.cpp` 原先作为候选RED夹具创建，不在v8，也明确被原DP已验产品包排除；清结果累计补丁因此记录的是“修改这个既存候选夹具”。其before SHA为 `62cb3b67…`，最新已验after为 `121868a5…`。未来在完整v8副本中应按白名单**新增已验最终测试文件**，而非对不存在的文件套modify补丁；目标若意外已存在必须停下来核来源。完整SHA、归档和成员在 `review_resolution.json`；该例外只适用于这一验证路径，不能放宽25个产品路径的基线门禁。

## 3. 已知依赖与发布绑定约束

1. **运行负载**：97项总登记字节 2,045,989,400，839项已有硬件见证总登记字节 46,370,255。这些是旧清单字节，不是本轮新增拷贝量或已核可用磁盘预算。下一阶段只按获准清单复制既有文件并校验，不载入模型、不推理、重训、重评或重新导出；保留既有闭环与live恢复来源。另有1项上游只读checkpoint引用，完整副本不等于消除了这个外部依赖。
2. **平台/BSP/历史闭包尚须落实**：本轮没有创建目标目录或完整工程。37/112与936旧清单不能被当成任意新目录天然可运行的保证；下一轮仍需只读确认所选目标下的平台/BSP引用、工具链路径与历史目录隔离方式，再形成实际复制/复用清单。复用已验XSA/IP/平台，不擅自重建HLS/Vivado。
3. **不能只换打包CLI目录**：1581 `tools/gcs_release.py:14` 的 `BUNDLE` 仍为 `build/host/gcs_r1_abi4_release_v8`，`inspect`/`audited_elf` 的默认参数在定义时绑定。完整服务有5处不传bundle的 `audited_elf(loaded_assets=...)` 调用。因此仅 `prepare --bundle <新目录>` 不会改变服务默认验收目标；运行时只赋值BUNDLE也不是可靠修法。
4. **未来最小绑定处理建议，尚未实施**：只在获准的新完整候选中，沿用既有做法调整新默认包路径及其定向测试，再冻结新的source/asset/release身份。新包名、目标根目录、App工作区均未确定；不得原位改1581、复用旧v8身份冒充新包，或绕过源码/ELF/已加载资产门禁。
5. **模板已正确，不重复修**：1581和f3fb源码中的 `roi_release.h` 都是UNBOUND模板；v8包内 `app_src/roi_release.h` 才是绑定产物。本轮没有发现需重新清模板宏的问题，新包只能在自身目录渲染绑定头。
6. **服务导入不是零副作用检查**：源码在导入时枚举运行资产并执行 `S=State()`，涉及owner、历史和模型目录发现。本轮只用AST/文本读取，没有import服务器或release模块；以后离线HTTP夹具应先隔离文件路径、状态和传输，不以“没监听端口”推断import毫无副作用。

## 4. 完整服务与实机验收清单（本轮均未执行）

完整v8服务 `gcs/server.py:471` 的 `/api/board/display` 在 `S.control_lock` 内核 `S.source is S.board_source` 与严格 `confirmed is True`，调用同一 `S.board_source.request_display(..., identity=cmd, on_update=...)`。**这是静态转交关系，不是HTTP或真实原owner验收。**

| 后续层级 | 定向检查重点 | 证据/边界 |
|---|---|---|
| 完整服务离线HTTP夹具 | 正确payload交给同一owner对象，identity/回调保持，返回新合同 | 先隔离临时状态、日志及传输；内存owner不能冒称真实原连接 |
| 拒绝路径 | 未确认、source不一致、身份不符、旧action/能力、活动/暂停/待操作时拒绝，无隐式START/STOP | 原始HTTP/调用计数/状态快照；不放宽门禁 |
| 回执/恢复 | action2、INFO bit5/result_clear、完整身份/nonce、V2日志；旧隐藏回执不能冒认成功 | 新HTTP/事件/持久记录一致；原始V1/V2与失败证据保留 |
| 发布绑定 | 新候选工具默认、实际包、source/asset、用户新ELF、进程已加载资产一致 | 新冻结和新用户Build审查另获许可，不能沿用v8 ELF替代新产物 |
| PC/DP/板卡 | 终态清当前结果并等待新任务，运行/暂停拒绝，历史/控制身份保留，新任务从零 | 真实同一owner/boot/session/task及物理显示由获准实机窗口确认，不以DOM或帧缓存ACK代替 |
| 原验收欠项 | 原A～G/T及板卡/性能/长稳等未验项保持 | 本表只是本次变更的集成补充，不替换或缩减原矩阵 |

输入方案仍未定，先显示后操作；闭环非核心，保留成果，不把本轮清单当新训练任务。

## 5. 回退与保存点

- 默认回退参照是**配套v8**，不是自动降回3716/v7。1581完整源码、`1581/.../build/host/gcs_r1_abi4_release_v8`、旧发布/日志/FAIL保持不动。
- v8 release_id：`6f9b125c1922afdc3f0d7deadf1c1b45e29806691eed79783cc75607273e3959`。
- 当前用户App工作区：`D:\HSI_AgriEdge\build\host\gcs_r1_abi4_vitis`；它不在f3fb内。本轮未写该目录。
- 当前旧ELF：`D:\HSI_AgriEdge\build\host\gcs_r1_abi4_vitis\gcs_r1_abi4_app\Debug\gcs_r1_abi4_app.elf`，3232488字节，本轮只读SHA仍为 `4cace08414f93804de77fcabe86edbe48844b0abbb8dfa9e547b81a683a42788`，与既有审查一致；没有Build、下载或板上确认。
- 集成/冻结/新Build失败时，保留新的原始失败与独立目录，停在相应门禁；不reset旧工作树、不混改旧包或覆盖用户App。任何清理也须另核准确目录及权限，不安排自动删除。
- 真正切换服务/设备后的回退需另获许可、匹配旧PC服务与旧固件、核真实新boot和任务状态；不得自动重连/接管/复活旧控制身份。V2记录不能降写V1，旧历史与失败证据不回滚成“成功”。

## 6. 下一轮第一件事与许可边界

1. 先读主树 `CLAUDE.md`、`CODEX_CONTEXT.md` 顶部与本文。被动核8765/服务/任务助手现态；**主机无监听不证明板卡空闲**。不要依据18:31快照假定下轮仍停，末次状态见本轮 `passive_state_handoff.json`。
2. 复用本轮清单，必要时仅做下面的只读SHA复核；不要因换对话重跑58项/旧CPU/A53/中文控制套件。
3. 下一轮可先继续**只读**落实目标目录方案、平台/BSP与历史隔离闭包。建立完整运行副本、复制运行资产、修改新默认绑定，需要明确相应范围后再做；当前“ok”只批准了本轮准备，“交接”不自动增加写运行树/服务/设备权限。
4. 获准建立独立完整副本后，再按白名单及来源例外实施；源/资产准备、离线HTTP验证、新冻结、App同步、用户Build/下载、服务启动、真实owner/板卡窗口和发布分阶段授权。现阶段无新目录、无新release_id或新ELF，不从f3fb启动任何服务。

```powershell
# 在主树；仅检查本轮215个已记录只读输入SHA，不导入产品、不跑功能测试。
D:/pytorch/python.exe report/gcs_roi/20261012_integration_preparation/audit_preparation.py --verify-readonly
```

完整重做清单须新证据目录，不能覆盖已有原始审查/复核文件。收尾提交号及准确范围见本轮 `commit_receipt.json`；只提交本轮文档/只读审计工具与回执及共享记录自身前缀，不包含任何产品源码，也不push。主树旧差异、候选原源码/12来源继承全部保留。双方memory/索引同步回执见 `memory_sync_receipt.json`。
