# DP 第一轮显示与中文化候选：中途交接（2026-10-12 14:24）

> **2026-10-12 15:36最新入口：`gcs_20261012_dp_chinese_regression_handoff.md`。** 原显示范围定向回归已收口并修两处点显示问题；新增“终态清上一任务当前结果、保留历史、等待新任务”已确认但未实施，PC/CPU RED已保存。以下14:24/14:31内容是历史。15:27仅被动查询无8765监听/服务进程，不能假设仍在或自动启动。用户最新约定四件套默认自行审查commit，不再逐次询问，不push。

## 0. 14:31最新补充：v8已按用户许可停止

用户追加要求先停v8、随后自行启动。已读取PID36796实际cwd和命令，确认属于1581后停止；14:31:47复核进程已退出、8765无监听，未发板端停止/复位命令、未自动重启。下文14:24的“服务仍在”仅为停服前历史。

用户在PowerShell中手动启动：

```powershell
Set-Location -LiteralPath "C:\Users\86187\.codex\worktrees\1581\HSI_AgriEdge"
& "D:\pytorch\python.exe" -X utf8 -u -B tools/gcs_roi.py serve --port 8765
```

地址 `http://127.0.0.1:8765`。不要从主树或f3fb启动。停止服务不授权热改正式源码/发布/Build/上板；候选仍待回归。

## 1. 最新停点

用户要求“交接，新对话再继续，给提示词”。已停止扩展产品修改；**本批已经实施初版，但尚未完成受影响回归，也没有发布或上板**。不要再按上一入口的“尚未实施”从头开工。

- 主记录树：`D:/HSI_AgriEdge`，HEAD `72c8893` 是前轮提交，不是本轮提交。
- 唯一新候选：`C:/Users/86187/.codex/worktrees/f3fb/HSI_AgriEdge`，从 `72c8893244678dd2cd58fdec7ffb036662283eba` 创建。
- 在候选中按原字节复制了 v8/1581 的 **52 个目标源码/词表文件**，包括继承修改；不是完整运行数据副本，不要启动此候选的真实地面站服务。
- 本轮产品/测试/生成工具差异共 **23 个路径（18 修改、5 新增）**。精确名单和前后 SHA 在 `report/gcs_roi/20261012_dp_chinese_candidate/task_changes.json`；不能用候选相对 Git HEAD 的全部差异冒充本轮范围。
- **未获本轮 commit/push 明确授权**，未暂存、未提交、未 push。主树、1581、3716 的继承改动、旧包、失败证据均保留。

## 2. 服务被动现态：只作快照，不接管

2026-10-12 14:24:11 的 GET/进程/监听观测：

- 1581 是 v8 正式运行树，**PID36796 / 127.0.0.1:8765** 仍在。
- 命令：`D:/pytorch/python.exe -X utf8 -u -B tools/gcs_roi.py serve --port 8765`。
- 主机任务 **#8，洪湖 v1，done 18128/18128**；boot `228ce0ef`，板端 session `10212bf4` / task `4`，error=null；ROI 为行284、列233、高88、宽206。
- **主机 gate 当前 active=false / authorized=false / transport_state=closed**。关闭原因未调查，不等于服务停止，不自动重连、恢复、停止或重跑。
- 服务日志仍在 1581 的 `build/host/gcs_unified_release_v8_01/service_v8_01/`；任务日志 `build/host/gcs_roi/task_20261012_133207_379138/`。
- 本轮没有启动浏览器、真实候选服务、训练、App Build、硬件工具或板端命令；临时离线命令均已结束。
- 接手时对照的 52 个运行树源文件 SHA 均未漂移，见 `running_source_unchanged.json`。这不是重复板测或完整运行目录审计。

## 3. 已经写入 f3fb 的内容

### DP

- `roi_canvas.h/.cpp`：地图可用高度 **880→928**，仍按三景原比例缩放；地图区域 `(404,94,844,928)`。
- 移除重复图例，右侧统一“中文类别名称、像素数、占比、比例条”；三景分别9/22/16类，类别字库统一22号，保留原顺序和颜色。
- 左侧独立点卡：坐标、具体中文类别、置信度优先；场景/模型及 CRC、启动/会话/任务等追溯信息次要。
- 运行、等待、暂停、停止、完成、失败均有中文标签；计算性能压缩为小面板，不给功率/温度/能耗补假数。
- 主 `SceneCanvas` 和遗留15点 `render()` 都做了中文化。增加小写 ASCII 字形，以原大小写显示模型 tag，不改真实身份。
- `roi_display.cpp` 使用 `SCENE_UPDATE_RECTS` 统一刷新区域，未重启 DP/DPDMA；清/恢复仍只作用于显示。
- `generate_gcs_dp_labels.py` 复用已安装 Noto Sans SC / OFL；生成 `roi_labels.h`（118674字节、96标签）。没有新增字体二进制或依赖。

### PC 与共享词表

- 新增 `gcs/web/class_labels_zh.json`：47项具体中文名，显式 **0基** ID，绑定原英文名/顺序/颜色。原 `palette.json`、`model/scenes.py`、旧 LongKou 绑定表未改。
- `core.js`：统一加载三景词表；`clsName(c, scene)` 接受 PC 的1基类别（0为未标注），`boardClassName(id, scene)` 显式处理板端0基类别；跨景颜色也按结果场景查表。
- 点卡/概率图、图例/统计、评测图、闭环对比图、历史、场景选择和真值对比等改为中文显示；英文任务/来源/状态字段做显示映射，原协议枚举和数据保持不变。
- 保留单点既有 request/boot/session/task/scene/model/CRC 身份门禁，**没有为了跨景显示放宽旧结果校验**。下轮需专门核跨景与拒绝过期结果的交互。
- 新增 `errorMessage()`：普通界面显示中文解释，未知英文诊断保留在浏览器控制台/原始回执，不改写服务端证据。实际错误措辞与模型阶段映射仍需定向审查。
- 新增 `gcs/display_labels.py`，`board_agri.py` 的 HTML/CSV 展示名称取共享词表；**原 report JSON、board_result JSON、CLASS字、掩码和统计保持原始值**。CSV机器字段名和文件名不改。此改动不涉及训练或推理。
- 洪湖部分蔬菜中文采用现有英文类名的显示译名（大白菜、小白菜、青菜、小青菜、菜心、榨菜等），不是已核官方中文名；如用户希望调整俗名，只改显示词表，不合并类别、不挪ID。

## 4. 验证进度：已经做了什么、没有做什么

已保留真实回执：

1. `tools/check_gcs_chinese_names.cjs`：原实现 **12项 RED**，修复后 **12项 PASS**，覆盖三景首尾类别、0占位、非法ID、未知场景、跨景名称与颜色。此后仅添加普通文案辅助函数，未改名称/颜色函数；最终 JS 语法已核。
2. `test_gcs_chinese_canvas.cpp`：原地图高度断言 RED；新渲染器主机编译与初步断言 PASS。**目前该测试只验证地图高度和47个字库尺寸，不是完整绘制/布局回归**。最后又仅调整任务号横坐标和注释。
3. `test_gcs_chinese_report.py`：原 HTML/CSV 三景名称 RED；收尾时 **1个测试方法、3景子用例 PASS**，核中文名称、ID顺序、CLASS字与原JSON/分析数据不变。未变地图编码被替身隔离，未生成或读取图片。
4. 最终 **11个 JS/CJS `node --check` + 4个 Python AST** 通过。
5. 仅本轮补丁正向（独立原始副本）、反向（候选现态）`git apply --check` 均通过；52源运行树字节未漂移。

**未完成**：浏览器 DOM/长文本边界；DP 三景真实绘制边界、各状态、点卡与统计隔离、隐藏/恢复、刷新区域覆盖；受影响既有 host 回归；A53语法检查。未新建完整测试编排脚本。没有任何新板测、物理DP目视、完整功能验收或性能结论。

失败证据保留：原名称 RED、原地图高度 RED、原报告 RED；第一次候选名称测试夹具把 `/web/` 错映射成仓库根路径，已修测试路径；词表验证曾抓住汉川两项手录颜色错误，已恢复原 palette 颜色，未触及运行树。

## 5. 下一步（先审查候选，再定向补测）

1. 在 **f3fb** 继续，先读本入口、`task_changes.json` 和精确补丁；不要覆盖已有初版，不新建重复候选，不从主树旧代码重做。
2. 补足纯CPU布局测试：三景/47类/长词、空结果、六种任务状态、地图边缘ROI、数值长文本、CLASS前缀/直方图不变、点卡不混入区域统计、清/恢复语义；验证所有 `update()` 改动落在 `SCENE_UPDATE_RECTS`，点卡仅在自身矩形。
3. 旧 `test_gcs_scene_canvas.cpp` 有直接按 `SCENE_MAP_X/W` 计算像素的假设；新布局有居中留边，应按 `canvas.map_x()/map_width()` 等真实映射修正受影响断言后才运行。`test_gcs_model_canvas.cpp` 会写PPM，本轮没跑；按“不读图”边界选择无图片的数值检查。
4. PC 用离线夹具核真实 DOM/图表选项：三景具体中文名称、板0基/PC+1、跨景单点和过期身份拒绝、空值/错误/状态、长词不溢出、用户按钮提示。不要连接8765做交互测试，不执行真实 POST。
5. 已有 Playwright 绑定可用：`C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright`（另有其他缓存），没有安装新依赖。可用离线DOM注入，不截图、不读图片；本轮尚未启动浏览器。
6. 对实际受影响项补 host/A53 语法，不重跑未变旧7/23/119套件。g++ `D:/mingw64/bin/g++.exe`；A53与BSP路径见候选 `tools/check_gcs_dp_probe.py`，不可把脚本旧全套未经筛选直接重跑。
7. 保留本批现有闭环入口/模型成果，不重训、不删除；板端输入方案未定，主操作迁移仍不做。

## 6. 范围、复现与归档

证据根：`D:/HSI_AgriEdge/report/gcs_roi/20261012_dp_chinese_candidate/`。

- `baseline_manifest.json` / `baseline_sources.zip`：52个v8原字节目标源快照。
- `task_changes.json`：23路径的新增标志、前后SHA和大小。
- `dp_chinese_candidate.patch` / `task_snapshots.zip`：仅本轮差异、前后原字节；`patch_validation.json` 正反向检查。
- `names_red.log` / `names_green_initial.log`、`canvas_red*.log` / `canvas_initial*.log`、`report_red.log` / `report_green_text_only.log`、`handoff_checks.json`、`font_manifest.json`。
- `passive_state_start.json` / `passive_state_handoff.json`、`running_source_unchanged.json`。
- 临时编译/补丁检查副本只在候选 `build/host/dp_chinese_*`，没有后台存活任务。
- 协作：`report/llm_log/20261012_dp_chinese_candidate.md`；索引 `report/evidence.md`；共用进度/上下文和双方可访问 memory/MEMORY.md 已同步此停点。

复现只在候选进行：`node tools/check_gcs_chinese_names.cjs`；`D:/pytorch/python.exe -X utf8 -B sim/host/test_gcs_chinese_report.py`。字库仅在词表/标签确有修改时执行 `D:/pytorch/python.exe -X utf8 -B tools/generate_gcs_dp_labels.py --report <新候选输出目录>/manifest.json`，不要无故重生成已核未变资产。

**发布/上板另获许可**：不热改1581或冻结3716；不重启服务、接管/恢复/停止/重跑任务、操作板卡/SD/模型、自动同步 App、Build/下载或重建HLS/Vivado；不读图、不push。当前通过的v8/ELF继续沿用。
