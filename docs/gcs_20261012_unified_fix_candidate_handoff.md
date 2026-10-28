# 统一修复候选完成后的交接（2026-10-12）

## 2026-10-12 12:25 后续更新（优先于下文原停点）

运行数据已精确补齐，v8已冻结/获许可同步，用户新ELF正式通过；**1581现运行v8服务PID36796/8765**，旧v7保持停止。无需再Build/同步，不自动重启旧服务。下一用户刷新并下载已批准ELF，再按授权受控实机验收。最新恢复入口 **`docs/gcs_20261012_v8_unified_release_handoff.md`**；下文11:30状态保留为历史。


## 0. 最新停点与用户决定

**本轮已完成闭环预检/同包复用和真值并排候选，用户要求“这个做完交接新对话再继续”。现在停止扩大范围；下一轮从运行数据补齐与新发布准备继续。**

先读本文件、`CLAUDE.md`、`CODEX_CONTEXT.md` 顶部。上一份 `gcs_20261012_unified_update_plan_handoff.md` 保留原计划与竞赛优先级，但其中“GT 未实现”“v7 仍运行”已被本文件更新，不能继续沿用。

- 用户本轮明确说“v7可以停掉了”：已核 PID/命令和 127.0.0.1:8765 监听后停止 v7。**10:51:09 确认 PID13872 退出、8765 无监听**，没有启动替代服务。停止前通道 closed/unauthorized，最近任务 #5 LongKou v2 已 done11748/11748；不是本轮板测。
- 原日志、配置、历史任务、训练 FAIL 和已用 SD journal 全部保留。首次停止后的即时观察尚未退出，原 `after.json` 保留，最终状态见 `confirmed.json`；不把初查失败改写为成功。
- 不读图/不截图审图；已通过且输入未变的检查不重跑。浏览器检查仅隔离夹具，既未访问原生产服务，也未发送板卡命令。
- 用户仍负责 Vitis App Build/下载。本轮**未确认当前自动 Build 已关闭，未同步 App、未 Build/下载、未准备新发布、未切新服务**。停止 v7 不等于上/下电、重训、模型上传/激活或改 SD 的授权。

## 1. 三棵树与本轮改动范围

| 路径 | 当前用途 |
|---|---|
| `D:/HSI_AgriEdge` | 主树、原始数据、共用记录、本轮证据。HEAD `984c872`；未把候选产品代码覆盖到主树。前轮恢复工具/既有脏改动保留。 |
| `C:/Users/86187/.codex/worktrees/3716/HSI_AgriEdge` | 原 v7 运行树，**服务已停**。HEAD `b4a10ce`；本轮未改绑定代码/资产。旧包/ELF/日志继续作回退依据，不自动重启。 |
| `C:/Users/86187/.codex/worktrees/1581/HSI_AgriEdge` | **继续工作的候选树**，HEAD `b4a10ce`，含继承差异。本轮 15 个明确产品/检查路径，未提交；不能整树 diff/暂存冒充本轮工作。 |

本轮既有文件：`gcs/server.py`、`gcs/board_models.py`、`gcs/engine.py`、`model/finetune_region.py`、`gcs/web/{core,app,map,loop}.js`、`gcs/web/index.html`、`gcs/web/style.css`、`sim/host/test_gcs_model_delivery.py`。

本轮新文件：`gcs/finetune_guard.py`、`gcs/web/gt_compare.js`、`sim/host/test_gcs_finetune_guard.py`、`tools/check_gcs_gt_compare.cjs`。

仅本轮补丁、修改前/后源码、SHA 和反向检查：主树 `report/gcs_roi/20261012_unified_fix_candidate/`。不要用整树差异夹带先前 SD/HLS/发布修改。

## 2. 已完成：闭环训练前门禁与等价包复用

### 训练前预检

- 服务端在占用训练槽、起线程/Popen **之前**检查登记区域/场景/hold/model/seed、旧 checkpoint 本地文件及 SHA、hold3 板包 checkpoint 绑定、两份 64×64 比较输入、原始 GT 精确切片、Train100/Test100 互斥及标签来源、旧预测直方图/区域指标和后处理所需旧评测字段。
- 原 `region.json` 里的旧树绝对 checkpoint 路径不被改写；实际训练只读本候选树内同名且 SHA 一致的 checkpoint。
- 记录 `preflight.json`，作为参数传给训练子进程。CLI 也先独立预检，再比对服务回执；场景预处理后再次检查输入未变，防止启动间隙换输入。
- 新运行目录/权重目录/checkpoint 已存在即拒绝，不重训覆盖。旧预测/GT 在训练前已读入，不再等训练后才发现缺文件。
- **本轮没有启动真实训练/评测/导出，也没有重跑原恢复任务。**

### 同内容不同 tag

- 导出包先走原配对/SHA 验证；与已有版本的完整配对身份一致才认定等价，并保存 **6 个文件 SHA、两份独立 checkpoint/manifest 来源**。
- `live1012_093738` 的实际既有导出经新逻辑只读检查，仍映射到 **UI `v3` / 包 `v3_board`**。保留新运行的 candidate/来源，不篡改旧 manifest、不换 tag 重复上传、不放松板端 CRC/tag 门禁。
- 服务返回 `candidate.version/package_tag/reuse`，UI 用 canonical version 继续，并明确提示“六文件一致，复用既有包；未确认激活/复测”。训练运行 tag 与板端包身份分开保存。
- 服务重启发现等价导出时不再增加重复可上传版本；`/api/board/models` 的 `equivalent_exports` 保留映射证据。仅某一 kind CRC 相同但全包不等价时拒绝登记为可下发别名。

## 3. 已完成：只读真值 / 任务预测并排

- 主图“图层”区新增 **真值 / 推理并排**，打开独立模态窗口；左 GT、右当前显示任务的实际结果，默认任务 ROI，可切当前选框/整景。
- 同 ROI、共同缩放/平移/坐标、固定同色表；不受主图透明度与类别隐藏影响，不更改原地图坐标或工具模式。
- 板卡结果只认 `seen` 中实际接收的像素；GT=0 为无标签，未接收以不同棋盘纹显示；GT、旧任务、单点结果都不会填充当前任务预测。
- 显示正确/误分/**已接收无标签**/未接收/无效数量和已收有标签一致率，明确 **非 Test100 精度**。“仅看误分”不改变覆盖统计。
- 本任务真实更新合并到一次刷新，增量修改离屏图像的局部区域；不逐帧重建全图。身份异常、清显示、新任务、切景/加载失败、断开/只读重连均清旧对照缓存。
- 对照窗缩放/拖动/坐标查看没有 fetch/推理/START/模型操作。关闭/Esc 后原单击推理保留；没有重做单击功能或新增控制入口。
- 这只是候选离线验证，**未部署到用户界面、未实机验收**。原界面旧 boot 混显/授权缓存问题没有被宣称整体永久修好；本轮只处理对照窗自己的身份与缓存边界。

## 4. 已完成的定向检查（输入未变不再跑）

| 检查 | 最终结果与口径 |
|---|---|
| Python | **21/21 PASS**：新门禁/等价/服务入口 14 项 + 原同步训练槽回归 1 项 + 受影响模型契约 6 项。日志 `checks/finetune_attempt02.log`；初次 12 项是此前阶段，不相加。 |
| 浏览器 | **25/25 PASS**：新 GT、覆盖/身份/增量、切景/清屏/重连、关闭后单击、等价提示；隔离 HTTP + 假 WebSocket，无外部/生产请求、无截图、无页面错误。`checks/gt_attempt01/report.json`。 |
| 新逻辑的真实输入只读集成 | 主树现有闭环 **15 个输入**通过新预检；3716 现有恢复产物通过新六文件复用识别。没有复制数据、重训、评测、导出或设备操作。`checks/actual_new_logic_check.json`。 |
| 差异与旧候选保护 | 本轮 15 路径独立补丁反向 apply-check PASS；旧 DP 7 源/检查文件与旧单击 4 文件逐 SHA 未变；本轮 App 源零变化。 |

原单击 **23 项**与 DP **7 条命令**是前轮证据，本轮没有重跑；GT 修改 HTML/core/map 后必要的点击/交互回归已包含在新增 25 项中，不能把旧 23 项冒充本轮整套验证。旧 v7 119 项、算子/HLS/板测均未重复。

原已执行命令（cwd=1581；需要因新修改复验时才使用新输出目录）：

```powershell
D:/pytorch/python.exe -X utf8 -B -m unittest sim.host.test_gcs_finetune_guard sim.host.test_gcs_model_delivery.ModelDeliveryTests.test_training_claim_is_synchronous_and_only_candidates_reach_ui sim.host.test_gcs_models -v
node tools/check_gcs_gt_compare.cjs C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright build/host/gcs_unified_update_01/gt_attempt01
```

原始 RED（缺 guard 模块、缺 GT 入口）和最终 PASS 均归档。`verify_saved.py` 只读核对已保存证据，不启动训练/浏览器/服务或触碰设备。

## 5. 下一对话从这里继续

1. 核实 8765/进程仍为空；如用户另行启动了服务，先核当前目录/身份，不盲开第二服务。物理板卡电源状态未知。
2. **1581 仍未准备完整运行数据**（没有 `data/scenes/longkou` 等完整副本）。按原已核清单从主树/3716 精确补齐三景运行数据、模型包、checkpoint、raw/官方 split 和闭环后处理依赖，不镜像整树。本轮只读预检主树，不等于1581运行数据通过。
3. 保留前轮单击/DP候选，结合本轮补丁准备**新的统一发布身份**；不能复写冻结 v7。注意候选 `tools/gcs_release.py` 的默认 `BUNDLE` 仍指向旧 v7 名称，下一轮需按新发布流程处理默认/服务绑定，不能直接用旧包启动新代码。
4. 复用已核平台/IP/XSA，不重建 HLS/Vivado/平台。当次确认用户自动 Build 关闭后，才同步明确新 App 源；用户 Build 后审 ELF 加载态身份/绑定。本轮没有这一确认或任何新 ELF。
5. 新服务窗口和用户下载/真实任务再按授权实施；当前 v7 已停，不自动回启。模型激活、上/下电、SD 写入、上传/推送仍须相应明确操作/授权。
6. 一次受控验收新单击→实际结果→DP卡、GT 同 ROI 对照；闭环 A/B 需新真实任务、相同登记 ROI、hold3 对 `v3/v3_board`。原 #3/#4/#5 不可冒充该 A/B。
7. 第一轮 A～G/T 欠项与原失败保留；优先级继续参考原统一计划第 6 节，不自动扩展第二轮、性能重构或额外展示功能。

## 6. 收尾范围

- **提交**：未获独立 commit/push 授权，未暂存/提交/推送。15 个候选代码/测试路径的独立补丁已保存；主树只新增本轮证据/交接和共享记录片段，其余脏改动不属于本轮。
- **进度**：本文件是最新入口；三树当前快照/共用进度定位追加，证据索引与真实协作日志同步，历史不删。
- **踩坑**：没有新增独立产品坑；只给已有“缺闭环输入”“同包不同 tag”两条追加本轮候选修复结论，不把离线 PASS 写成已部署。
- **记忆**：同步可访问 Codex/Claude 项目 memory 与两边 `MEMORY.md` 索引；只保留简短状态与此恢复入口。
- 无新第三方依赖/许可变化，未动独占 skill 目录。临时 Python/浏览器/测试进程已结束；无待运行的助手任务。

新对话可直接发送：

> 接手 D:/HSI_AgriEdge，先读 docs/gcs_20261012_unified_fix_candidate_handoff.md。1581 已完成闭环预检/同包复用与 GT 并排候选，21 Python/25 浏览器通过，未部署。v7 已按用户要求停止，勿自动重启；下一从精确补齐1581运行数据和新发布准备继续，用户确认自动Build关闭后再同步，由用户Build/下载。不重训、不换tag重复上传v3_board、不读图、不重跑输入未变的已验项，保留所有继承脏改动与原FAIL。
