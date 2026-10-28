# 2026-10-12 完整候选目录与引用闭包方案（只读，未实施）

## 1. 结论与本轮边界

**推荐未来集成根目录 `D:\gcs_20261012`；本轮仅确认它尚不存在，未创建或复制运行副本。** 它是待授权的物料落地位置，不是已经建立的第二产品候选，也不是可启动服务的目录。当前唯一产品候选仍为 `C:\Users\86187\.codex\worktrees\f3fb\HSI_AgriEdge`，仍不完整、禁止从中启动服务。

- 接续主树 `96f9be3` 的只读准备，不重做 DP/中文、清结果修复或旧夹具迁移。1581=v8 正式源码、3716 冻结，均未写；主树旧差异、f3fb 源码及12项来源继承保留。
- 复用[原交接](gcs_20261012_integration_preparation_handoff.md)的36路径白名单和[限定复核](../report/gcs_roi/20261012_integration_preparation/review_resolution.json)。原始 `READONLY_PREPARATION_REQUIRES_REVIEW` 不改；唯一 RED 测试来源例外仍只适用于 `sim/host/test_gcs_result_clear.cpp`。
- 未导入真实 server/release 模块，未 HTTP、启停/重连/接管服务，未接板、读图、操作 SD/真实模型、同步 App、Build、下载、重建 HLS/Vivado 或发布；原58项、单夹具1/1、CPU/A53、中文/控制套件未重跑。
- 18:59 被动无8765监听，但已有 XSCT 外壳 PID37696 和 `hw_server` PID12404；19:22 补全进程链确认 `rdi_xsct.exe` PID47204。均保持不动。**无监听不等于用户 Vitis/板卡空闲**；最后快照以本轮 `passive_state_final.json` 为准，恢复仍须重核。

本轮证据独立放在 [`report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/`](../report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/)，不覆盖上轮输入/审核/验证/提交回执。

## 2. 目标目录：保留现有 ROOT 约束，不借道旧工作区

以下全部为**建议名称与未来布局**，不是已创建的文件：

```text
D:\gcs_20261012\                          R：待授权完整集成物料根
  gcs\  model\  tools\  src\  sim\ ...  仅清单内来源与验证文件
  data\                                 97项既有运行/恢复输入的独立字节副本
  build\hls\...  build\vivado\...        839项既有硬件见证，非重建工程
  build\host\gcs_round1_20261011\...      仅4个HLS run/log见证文件
  build\host\gcs_r1_abi4_release_dpzh_clear_20261012\  待新冻结
  build\host\gcs_r1_abi4_vitis\           待用户新建平台/空App
  build\host\gcs_roi\                    初始不存在或全新空目录
  build\host\gcs_uart\                   同上
  build\host\gcs_network_boot\           同上
  build\host\gcs_training\               同上，非训练许可
```

选择理由：短的 D 盘独立根可避免与1581/f3fb/主树 App 混写；`gcs_release.local_output()` 仍要求输出在**自身** `ROOT/build/host`，无需放宽门禁。新 workspace 也在同一个 R 内，不用 `--workspace-root` 跨工作树绕行；纯物料目录不依赖 `.git`，不要复制 worktree 的 `.git` 指针。该方案是静态路径审查，不是 Vitis 工程搬迁或运行验收。

明确不选：整树复制 f3fb（缺运行文件且 server/release 等非白名单来源不同）；把新包塞回1581；覆盖 `D:\HSI_AgriEdge\build\host\gcs_r1_abi4_vitis`；将旧数据/历史/BSP目录做 junction、symlink 或硬链接到新目录。目标存在、解析后越界、遇重解析点/冲突或来源漂移时停止，不合并、不覆盖、不自动删除。

## 3. 实际复制 / 复用清单

逐文件源路径、目标路径、角色、旧登记 SHA、最终 SHA、归档成员和字节数见 [`copy_reuse_plan.json`](../report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/copy_reuse_plan.json)。这不是复制脚本，也没有调用复制操作。

| 分类 | 数量与动作 | 门禁及来源 |
|---|---|---|
| v8 冻结源码/资产 | 149条记录，148个去重文件 | 37 App源/112资产；`tt_engine_regs.h` 两域共用。用1581工作文件，不用主树脏源码或 f3fb HEAD |
| 既有运行输入 | 97路径 | 原运行/模型出处/场景/官方划分/已有闭环及 live 恢复成果；普通独立字节复制，禁止解码、推理、重训、重导出 |
| 既有硬件见证 | 839路径 | 314输入+314快照+191 IP文件及20项已完成证据/支持文件；只复用，不启动 HLS/Vivado |
| 去重基础物料 | **1078路径** | 148+936−6；6个 HLS 源同时属于冻结文本和硬件见证，不能算成额外来源 |
| 已验最终产品 | **25路径** | 18服务/网页+7 App；其中23覆盖基础物料、2新增。逐路径保留最早 v8 基线门禁 |
| 已验验证文件 | **11路径** | 独立增加到验证域，不自动算产品/运行资产。清结果 CPU 测试只新增最终已验文件，不向不存在的 v8 文件套 modify |
| 当前最终落地集合 | **1091路径** | 1078+2+11；36个最终文件沿用三层最新 after，不能再叠加中途 `4e0393f` |

**实际落地每个最终路径只写一次：1055个未替换基底文件取1581，36个取已验最终 after。** 表中23项“覆盖”是物料选择上的替换，不是先写旧文件再套 modify；1091个新目标都须不存在。写产品 after 前仍先校验对应25个 v8 源端基线（其中2个新增产品要求源端不存在），再验最终 SHA；这不豁免产品门禁。11个验证文件独立新增，尤其清结果 CPU 测试不得尝试套其候选RED起点补丁。归档成员或已核f3fb最终文件只是取件来源，不能复制整个候选。

最终集合静态文件字节数 **2,095,032,427（约1.95 GiB）**，只是当前36白名单下最终文件的下限，不是复制过程峰值或完整磁盘预算。尚未计入新包的重复文件、新平台/BSP、App对象/ELF、验证证据/日志、临时文件和保留量。D盘审查时可用约130.13 GB，实施前重新核磁盘，不能把快照当持续保证。当前平台仅供体积参照：5233文件/160,055,078字节，不在直接复制清单；观察到的最长平台路径和拟目标投影均203字符，不等于工具链长路径已测。

补充闭包结论：

1. 静态 Python 本地 import 和 C/C++ 引号 include 审查未发现应追加的仓内来源路径。外部 Python 只读发行元数据、编译器/Node/浏览器只查路径，不运行它们。`tensorly` 不在当前 site-packages 元数据中，但仅由 `tt_model.verify_mode_dot()` 延迟使用，其指定的既有外部目录存在；没有安装或导入，也不把它误报为服务启动失败。
2. 191个 IP 文件中的 `component.xml` 列出380次、190个去重文件引用：均存在、留在 IP 根内、在精确清单内；未读取这些 RTL/硬件负载重做内容验收。新位置仍须在获准字节复制时按登记 SHA 核完整性。
3. 服务仍默认 v8。下一阶段拟单独修改**新完整集成副本**的 `tools/gcs_release.py` 默认包路径及最小定向测试（如 `sim/host/test_gcs_release.py`）；这是36白名单之外的**待授权新增差异**，本轮未实施。只改 CLI `--bundle` 或运行后赋值 `BUNDLE` 都不足以改变服务5处已捕获默认参数的调用。
4. 源码 `roi_release.h` 已是 UNBOUND，不重复修。只应用当前产品白名单预计仍37源/114资产；正式新身份必须等新绑定、冻结和新 ELF 审查，不沿用 v8 release_id 或旧批准回执。

## 4. 平台 / BSP 引用闭包与选定路线

详见 [`platform_bsp_closure.json`](../report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/platform_bsp_closure.json) 及 [`layout_review_resolution.json`](../report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/layout_review_resolution.json)。

### 已核事实，不是新平台验收

- 用户 App `.prj` 的 `location/platform`、system `.sprj` 的 `platform` 都是主树绝对路径；平台 `platform.spr.platHandOff` 仍指主树 XSA。不能复制目录后自称这些绑定已经迁移。`platform.tcl` 还含旧 workspace 的创建/生成命令，只作参考，不执行。
- 导出的 `.xpfm` 相对引用 `hw/*.xsa` 和 `sw/*.spfm`；`.spfm` 的 include/lib/system.mss/boot/QEMU 路径均在该导出树内且存在。相对导出包完整，不代表 App `.prj` 的绝对平台指针会自动换根。
- 当前用户 BSP 与 v8 基准 `.mss` 在既有允许差异下匹配：tt_engine 2.0→4.0，`RAW_API`/`lwip_dhcp=false` 显式默认正规化；其余表项一致。PHY文本、导出 `xtt_engine_hw.h` 与冻结 IP 对应头的 SHA 一致。XSA、库和 ELF 本轮未重新哈希/打开。
- 广义 include 扫描曾将 `xemac_ieee_reg.h` 列为导出 include 缺项。定位后确认它是 PHY源码112行使用的 **lwIP BSP内部同目录头**，实际内部文件存在；不是 App 导出头缺失或产品故障。保留原扫描字段，以单独复核限定解释；不得补假导出头或放宽平台门禁。

### 决策：复用硬件与配置合同，不直接搬用户已 Build 工程

1. A阶段只带入冻结 XSA/IP/见证以及三份源码参考：基准 `system.mss`、自定义PHY文件、低DDR `lscript.ld`。不复制整个 `vitis/`、用户 `.metadata`、`.prj/.cproject/.sprj`、Debug、旧对象或旧 ELF。
2. 后续由用户在 **R/build/host/gcs_r1_abi4_vitis** 新建同名 `gcs_r1_abi4_plat`，使用 R 下那份已核 XSA，A53/64位/standalone_domain；保持既有 BSP配置/PHY/寄存器和链接器约束。
3. **新平台库及启动组件的 Vitis 生成也需要独立许可。** 这是消费既有 XSA 生成新软件平台，不是重建 HLS/Vivado，也不等于 App Build、BOOT.BIN/SD准备或下载许可。不借旧编译库绕过新平台审查。
4. 新建 `gcs_r1_abi4_app` 空 C++ App，确认自动 Build 已关闭、没有 `.o/.elf`。新 `.prj.platform` 必须精确指向该新 workspace 的导出 `.xpfm`；按现有 `check_platform/check_empty_app` 规则审查后才可另获许可同步37源及绑定头。
5. 若不批准新平台生成，本轮路线停在“源码/依赖已落地”层；不能拿当前用户工作区替代，也不能为搬迁私改 `.prj` 或放宽门禁。可再讨论另一条受控平台迁移路线，但不擅自实施。

## 5. 历史隔离：运行状态不迁，模型出处不篡改

[`history_isolation.json`](../report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/history_isolation.json) 记录三树历史根的存在性/子目录名称，未读包流、图像、结果负载或恢复 owner。

- 新活动 `gcs_roi` 不带入旧 `task_* / channel_* / probe_* / model_* / display_* / boots / ledger`；新 UART、network_boot、training 也从不存在/全新空根开始。旧编号、boot/session、端口选择、claims和显示回执不自动复活。
- 唯一允许复制的旧 `build/host` 文件是清单列出的两个 HLS 阶段各自 `run.json + console.log`，共4项。这些是硬件来源见证，不是可恢复的运行历史；保留旧 command/baseline_xsa 字符串，不执行/改写。硬件检查工具按自身 ROOT 定位这些见证。
- v8、3716、主树原始 V1/V2、FAIL、journal、日志、旧发布包和用户 App 留在原处。以后要在 UI 中查旧历史，应独立授权只读审计/视图方案，不能先塞入新活动根再默认恢复。新历史隔离也不意味着旧目录可删除。
- **不能一刀切删除/排除 `data/closed_loop/runs`。** 97清单中的既有 `live1012_093738` checkpoint、恢复结果和导出是需要保留的模型来源成果，不是操作 owner 的活动历史；只按精确清单复制，不训练。
- 扫描既有 JSON 元数据发现 **15处绝对路径、11个去重目标**，涉及上游、主树和3716。`board_model.json/checkpoint` 在 `engine.register_board_export()` 的特定“新tag且非等价复用”分支可进入实际 checkpoint 选择；该分支本轮未执行，未用负载比较判定是否会走。其余路径含历史输出、原日志和恢复报告，不能全部说成启动必需项。
- **当前选定方案保留元数据原字节，并显式保留这些外部路径的只读引用。** 即使同名 checkpoint 已复制到 R，也不会自动改变旧 JSON 的绝对路径。不得说这是“脱离旧树的完全自包含包”；3716冻结不等于可删。若要求连条件性 PC checkpoint 读取也不访问旧树，需要另批一个受控解析/重定位方案和定向验证，不能顺手改模型出处或放宽36路径门禁。

## 6. 实施顺序、回退点和下一阶段授权

下列每阶段都尚未实施；本轮授权仍只有只读准备和自身记录提交。**建议下一次只批准 A，完成后停点验收，不把一句“继续”串成 A～H 的全授权。**

| 阶段 | 需明确批准的范围 | 完成后仍禁止 / 停点 |
|---|---|---|
| A 物料落地 | 确认 R；按1091最终清单建立普通独立字节副本，允许复制期间读取/哈希既有输入字节；复核路径/磁盘/源SHA/碰撞，记录实际复制回执 | 不加载模型、不改绑定、不导入 server、不建平台/同步App、不启服务；仅 `STAGED_NOT_RUNNABLE` |
| B 最小绑定 | 只在获准完整副本修改新默认及最小定向测试；独立 before/after 归档，不混认36路径或继承 | 不冻结/运行；1581、3716、f3fb和主树产品源均不改，不绕过 source/asset/ELF门禁 |
| C 离线完整HTTP | 允许受控导入完整服务；**导入前**隔离模型发现、InputReader、历史、UART、transport，使用临时合成输入/内存owner | 不触真实模型目录、旧日志或设备；不是“真实原owner”验收，不启动常驻服务 |
| D 新冻结 | 批准新包目录及现有只读硬件/数据内容核验，生成新 manifest/身份/绑定头 | 不能沿用 v8 的 approved_elf/sync 充当新批准；不是App Build或发布 |
| E 平台与源同步 | 用户创建/生成新平台和空App；只读平台审查另行通过后，明确批准源同步；自动Build关闭 | 不覆盖当前用户App，不自动Build/下载，不执行旧platform.tcl |
| F 用户Build与审查 | 用户在新工作区Build；另批新构建日志/ELF来源和配置审查 | 不下载、不启动服务、不用旧ELF替代7个App源变化产生的新产物 |
| G 联验窗口 | 分别批准服务切换、真实原owner/新boot状态核实、需要的用户下载及PC/DP/板卡联验 | 不假定停机/板卡空闲，不自动接管、STOP/START或续跑；既有矩阵欠项保留 |
| H 发布 | 独立发布授权及完整证据审查 | 本轮和上述阶段均不隐含push、部署或SD更改 |

回退点：

- **R0 原有配套v8**：1581源码/原包、当前主树用户App和旧ELF均保留。v8 release_id 为 `6f9b125c1922afdc3f0d7deadf1c1b45e29806691eed79783cc75607273e3959`；旧ELF登记 SHA `4cace08414f93804de77fcabe86edbe48844b0abbb8dfa9e547b81a683a42788` 来自上轮只读核验，本轮仅 stat，不冒称重验。3716/v7不是默认回退目标。
- **R1 复制失败**：保留未完成新目录/失败回执，停止后续阶段；不补混、reset或删目录。重新尝试用另经批准的位置/清单修订，不原地掩盖失败。
- **R2 绑定/HTTP/冻结失败**：保留新 before/after、临时证据和失败包，默认v8仍不受影响；不回写旧包身份、原FAIL或UNBOUND模板。
- **R3 新平台/App Build失败**：保留新平台、构建日志及失败ELF；当前用户工作区没有被覆盖，无需也不得擅自“恢复”它。
- **R4 已切服务/设备后的回退**：另获操作窗口许可，配套旧PC服务与旧固件，实核 boot/任务/owner；不自动重连、不复活旧控制身份、不将V2降写V1。不因计划中有回退段落就获得设备操作权。

输入方案仍未定，先显示后操作；闭环非核心，保留成果、不重训。完整HTTP、真实原owner、物理PC/DP/板卡与发布欠项不因本方案收口而消失。

## 7. 复现、验收口径与收尾

```powershell
# 主树；仅核225条已记录文本SHA（221主审计+4限定复核）和1078条基础文件stat。
# 不导入产品、不打开模型/图像/XSA/库/ELF负载、不运行旧功能套件。
D:/pytorch/python.exe report/gcs_roi/20261012_integration_preparation/layout_closure_20261012/verify_handoff.py
```

主审计单独可用 `audit_layout.py --verify-readonly`（221文本SHA+1078 stat）。`--capture` 只允许首次生成本目录的新证据，已有记录不覆盖；修订应另建证据版本。逐条复制清单、来源闭包、BSP/历史判定和本轮限定解释分别见同目录 JSON；验证/提交/记忆回执是记录检查，不是产品测试或新发布证明。

这是**实施前停点**核对：未来获准创建目标后，旧快照的 `target_absent` 检查应拒绝；应生成新阶段独立回执，不能修改这份历史记录凑PASS。这里的外部“只读复用”是操作约束，不宣称已经设置新的ACL/只读属性，本轮没有更改旧目录权限。

主树/候选当前快照、共用进度、协作日志与 evidence 索引同步。提交仅本轮只读工具/方案/证据和共享记录自身增量，不混提主树旧源码或候选改动，不push；提交范围以 `commit_receipt.json` 为准。双方可访问项目memory及MEMORY.md索引同步并保留历史。独占skill目录不动，无新依赖、字体或许可变化。
