# A/B恢复核验＋C农情业务阶段交接（2026-10-10 23:51）

用户已要求本组做完后新对话用 `/goal` 继续第一轮；当前本组候选及离线回归完成，第一轮**未完成/未验收**。不创建当前goal、不替用户开新任务。

## 恢复顺序

1. 读 `CLAUDE.md` → `CODEX_CONTEXT.md`顶部 → 本文 → `report/gcs_roi/20261010_recovery_agri/review.md`。
2. 按需看 `.claude/progress.md`/双方记忆与索引/相关坑；不全量重读历史。旧总范围见 `report/gcs_roi/20261010_task_integration/review.md` A～G，状态以本组review为准。
3. `git log -1 -- report/gcs_roi/20261010_recovery_agri/review.md`定位本组提交（起点92195bb，已非最新）；核工作树与旧PID，不重复起服务/START/旧通过板测。

## 已完成候选

- INFO、明确同任务恢复、运行中/终态补传、日志重建历史/探查、严格停止前缀；UART多任务记录、新task独立核验zip。
- 农情统计/地块持久台账/原子revision保存/完整HTML+JSON+CSV+PNG报告包、真实任务A/B与共同Test100评测，全部带CLASS/seen来源与覆盖数。
- 原中央分类图/布局/配色/图例/缩放/框选/图层不变；错误/未测/部分覆盖显式，不显示PC推理入口或训练参考成绩。
- 闭环参数/Train100选点/真实任务对比候选已接；模型上传/激活尚缺，相关执行按钮保持准确不可用。
- 最终75 Python+8旧PROBE、61浏览器、协议/槽/画布/4+8 runtime/5 A53 BSP语法及9JS PASS；`tools/test_gcs_task.py`复现。回执 `report/gcs_roi/20261010_recovery_agri/checks`，不是Build/板测。

## 下一步不能遗漏

1. **D整组**：多景多模型注册与输入/标签/类别契约；WBEGIN/WCHUNK/WCOMMIT/WACT上传校验、持久化、安全切换及真实训练后复测比较；保持旧结果身份，失败不清DMA锁、不假装SD有文件。
2. **E真实注意力**：专项确认仍未获得。按 `docs/gcs_20261010_function_first_plan.md` 提案：12×6×6 Q0.24真实引擎输出、HLS/driver/公共输出契约/UDP分片/新IP-XSA；先说明范围集中确认。不能用logits、PC、MODE_DUMP特征代替。
3. **F独立启动**：裸机SD启动镜像/配套文件/脱离PC串口身份，涉及公共契约/BSP等先确认；写卡/启动模式/冷启动由用户执行。
4. **G最终集成**：全部候选完成后才改最终同步器/源清单/ELF审查，统一同步后用户Build、下载、上板验收。**现在不prepare/sync**，旧同步器仍24源scene_probe_s3_r1不能审新task版本。重核最终A/B/C/模型/DP/计时全生命周期，不能拿离线PASS关闭验收。
5. 像素/秒（计算）、ms/像素属于第一轮，现累计task-step含PS准备/engine等待，非纯PL、不可拿端到端代替；细分计时/最终实测仍需落实。USB鼠标本地操作另阶段，性能优化后置，不启动P2/旧优化流程。

## 保留状态及操作边界

- 旧HTTP PID38476、8765，cwd本仓库、命令`D:/pytorch/python.exe -u -B tools/gcs_roi.py serve`、日志`build/host/gcs_service/20261010_192446`；23:50核done220000、UART释放、无UDP。旧Python未加载候选，不凭静态页面判断。允许保留，最终换后端前另核/说明；不自动重启或另开服务。
- bb6bd8e3禁重用；原已下载板包/四通过与缺边角覆盖保持，不重跑旧PASS。
- 本组测试/浏览器均退出，未改用户IDE/hw_server工程。只本任务commit、不push，不夹带vitis/Packages/ELF/旧产物。
- 本组没有授权任何新HLS/driver/BSP/公共契约；`/goal`是持续推进目标，不解除这些许可。若到达需用户Build/设备/授权的位置，清楚列出所需操作并保留目标未完成，不声称第一轮完成。
- 每阶段同步progress/context/evidence/llm_log、双方memory和索引，记录真实新坑；保留独占skill目录。
