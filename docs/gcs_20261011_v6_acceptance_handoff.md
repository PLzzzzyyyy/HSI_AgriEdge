# v6 连续任务门禁修复候选：尚不开始新一轮实机（2026-10-11 23:08）

> 后续并行状态已更新：23:25共享记录及只读Git核实，另一会话已在`C:/Users/86187/.codex/worktrees/3716/HSI_AgriEdge`、分支`codex/v5-owner-fix-20261011`继续界面合批，提交`ee7ba63`继承P0并增加owner身份保护，Web仍在开发。该分支不等同于这里仅P0的v6冻结包；主树没有合并该提交。**不再重复询问是否开始UI合批，不在主树重复修改Web，也不先绑定本页v6。**等待隔离候选完整审查后再选新的冻结版本和当次绑定/Build窗口。另一会话goal状态不移植到本会话；本会话没有使用goal/token预算。详见报告`coordination.md`。

## 当前事实

1. HEAD `984c872`未push；暂存区为空。上一轮v5身份修复与本轮候选/文档均未提交，当前没有提交授权；并行交接保留。
2. v5正式ELF已批准且用户已JTAG运行，现服务PID20352/127.0.0.1:8765；旧35444已退出。未重复Build、绑定、停止/替换服务。日志`build/host/gcs_r1_abi4_user/service_switch_v5_01/server.*.log`。
3. v5启动原字是`boot228ce0eb/generation3`。task1收82000/220000后停止；其原字/CRC、暂停恢复停止、一个LOGITS/注意力点和计时独立重放通过，但不是整景或完整第一轮PASS。task2未START即模型查询超时，原失败与通道保留。
4. 旧时间戳跨大文件归档导致新INFO期限提前耗尽，已由2项RED复现。7行局部补丁后26项owner相关测试与41项发布门禁测试通过；不延长超时，不丢旧结果，不开第二socket。实机效果未测。
5. 新`build/host/gcs_r1_abi4_release_v6`已冻结35源/105资产，release `1a699c42adc80bf6c8b82d3eff83a565c15da82a7bde503ddbc689b3c73c9917`，**无sync/approved ELF**。只包含连续任务P0修复和候选默认路径变化，不包含`gcs_20261011_v5_ui_issue_handoff.md`其余六项问题。

## 当前动作：保留主树候选，等待隔离合批审查

请先不要再点击连接/开始、不要重新Build或下载。原服务可保持打开，主机gate已未授权/无活动channel；这不证明板卡已复位或原task被清除。不能删除本地claim、重用boot228ce0eb、重拷初始化journal或手填下一boot。

界面合批现已在上述隔离会话推进，保留其最新记录和分工；本页v6仅作为P0检查点，不抢先部署。若用户后来明确要先验P0，仍须当次许可。若再改受绑定资产，创建下一未占用包，**不得回写v5/v6 manifest**。

## 获得当次许可后，才依次执行

### 1. 新绑定与用户Build（尚未许可/执行）

- 必须先说明：虽然固件算法source_set、硬件和数据未变，GCS资产已改变release。旧v5 ELF只能证明旧资产，不可拿来批准v6。因此正式使用新GCS需要新的生成绑定头及用户App Build，不是原样重复旧Build。
- 重新核仓库/进程/自动Build关闭，完整备份用户App与旧ELF/配置。设计并验证针对选定旧/新版本的受控35源同步，保护已有配置/平台/无关文件。
- **不要运行旧一次性v4/v5同步脚本，也不要使用`--refresh-from`**：它只允许validator资产变化，已实际拒绝本次`gcs/board_link.py`变化；不扩大白名单绕行。尚未准备/执行v6一次性同步器。
- 只有当次用户同意才同步，保留原FAIL和新回执。用户手动Build App；不重建平台/HLS/XSA。保存原始完整Console与新ELF，不为补日志立即重Build。

### 2. 正式新ELF门禁与服务窗口（尚未许可/执行）

- 独立正式审查新ELF全部身份/编译/缓冲/符号，PASS后经用户许可登记；不能用离线回归、v5批准或部分补查代替。
- 再取得当次服务窗口，保存20352状态/日志后才切换；隐藏启动且不重复占用8765。被动GET应初始锁板/UART TX0，不自动控制板卡。

### 3. 用户JTAG启动和第一个小ROI

- 用户下载正式批准的同一ELF，真实使用JTAG就选择“JTAG下载运行”；PMU-FW警告尚无独立消除证据，单独核查，不假称已解决。
- 连接/刷新只读真实BUILD、journal新预约boot/generation、MODEL_SCAN/READY；旧boot已用不能接管。先核三哈希一致及ready，错误/丢页/溢出/不一致就停。不能把网络ready当SD独立冷启动证据。
- **先只做小ROI，例如5×3**，逐项核CLASS/seen、坐标/CRC/身份、PC图与DP；这一步通过后再做下一步，不默认再开整景。

### 4. 专门回归本次实机故障

- 同一连接做足够长任务，依次暂停→恢复→停止，核真实提交前缀；终态原字取证完成后再发第二个小ROI。
- 第二任务必须有自己的INFO/PONG/START ACK/CLASS及新task身份，不能把旧STATUS/结果塞入；保留第一任务历史和证据。大结果归档后不能立即假超时；真不回包仍应失败且不自动START/重试整任务。
- 未经许可不做断网、掉电、复位注入；主机恢复必须走原task/session有界恢复，不重新发旧START。

### 5. 其余A～G/T，全部通过才第二轮

继续`gcs_20261011_acceptance_matrix.md`完整要求及v5界面问题清单：三景/边界/整景、图表实时精度/农情/清空语义、12层注意力各坐标及故障、模型上传与两包持久化/切换/训练闭环、SD真正独立冷启动、PS/driver/PL计时与DP物理画面。旧状态列仅历史，不照抄UART必需条件或重新初始化SD。

记录每次真实PASS/FAIL和缺项，不能因当前26+41离线通过或单个实机任务重放通过关闭第一轮；不自动第二轮、USB、性能优化或push。

## 证据与恢复

- 本轮检查：`build/host/gcs_v5_acceptance_resume_01`。
- 发布前v5生产PASS：`production_recheck.json`；v6只prepare：`v6_prepare_01.json`；RED/green原log；原task1独立报告`task1_readonly_replay_01_report.json`。
- 原v5错误：`build/host/gcs_roi/task_20261011_222229_251595`与`channel_20261011_221543_092598`，绝不改写。
- 索引与复现：`report/gcs_roi/20261011_v6_deadline_candidate/{review.md,manifest.json,reproduce_deadline.py}`；身份核验补记`report/gcs_roi/20261011_elf_identity_fix/review.md`。
- 四件套/llm_log/evidence及双方memory按当前快照恢复；生产服务按既有授权保留，本轮测试/复现任务全部应确认退出后才收尾。无goal/token预算。
