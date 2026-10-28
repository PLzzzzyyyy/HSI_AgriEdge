# PC 单点探查 ↔ DP 联动：接手复核记录（2026-10-17 深夜）

接手对象：Codex 会话 `rollout-2026-10-17T22-10-37`（GPT 完成"PROBE 成功路径补 DP 刷新"并获用户确认）。
本记录整理既有证据、指出真实使用边界，并列出本次接手所做的修复与复核工具。
**未改动任何进入发布身份的资产**（`gcs/`、`model/`、`src/hs*` 与 tools 清单内文件均未动，见下）。

## 一、既有证据链（来自控制台运行记录）

- `build/host/gcs_roi/channel_20261017_224829_306396/`（boot `228ce105`，linked 固件）：
  - 22:48:44 探查 (1,1)：PROBE 0x09 → LOGITS + 2 段 0x87 注意力全部返回；
  - 22:49:31 探查 (1,1)：同上；用户随后确认 **DP 左侧「PROBE / PL」卡已出现且与 PC 一致**；
  - 22:51:57 探查 (344,182)：同样全部返回（会话结束后用户自行操作，链路正常）；
  - 22:52:57 用户启动整景任务（task=2）；**22:53:40 前后控制台进程消失**：
    通道无错误包、无 STOP，`task_20261017_225257_074685/` 无 `results.csv`、无板端记录回读，
    即进程被外部终止（窗口被关/被杀），板卡上该任务成为孤儿任务。
  - 此后 `build/host/gcs_roi/boots/` 与 `build/host/gcs_network_boot/` 均无新记录 → 未再重启。

结论：**探查→PC→DP 的联动机制在真板上已两次全链路成功**；没有证据显示联动路径本身失效。
"无法联动"的两个真实使用边界见下。

## 二、真实使用边界（非缺陷，但会造成"没反应"的观感）

1. **探查窗口**：任务完成后约 **5 分钟**内（控制台空闲 300 s 后通道关闭，`interaction.state='closed'`），
   之后探查按钮禁用，提示"探查连接已关闭：原任务连接已结束"。恢复方式：任务页点「恢复」或重新开始任务。
   （README 已补说明。）
2. **探查必须先有过任务**：板卡端 `probe_model` 要求任务已启动，DP 画布（`dp_live`）也在首个任务
   START 后才建立；不跑任务直接探查不会有任何联动。
3. **控制台进程消失后**：整景任务会变孤儿；需要重跑 `START_DEMO.bat`（板卡复位）或走「恢复」，
   否则新控制台无法连接旧启动（防抢会话设计）。

## 三、本次接手所做修改（均不触碰发布身份）

- `tools/gcs_mini.py`（精简控制台共享协议层）：
  - 新增 INFO 权重登记表缓存与 `scene_crc()`——**修掉洪湖/汉川两景 WACT/START/PROBE 都用死 LongKou CRC 的真 bug**（龙口不受影响）；
  - PROBE 被拒（ACK code≠0）或 8 秒无响应时发出 `probe_failed` 事件，不再永久停在"探查中…"。
- `tools/gcs_web.py`（8770 网页精简控制台）：接住 `probe_failed` 显示"探查失败：原因"；ACK 名称补 PROBE；
  保存 meta 的 wcrc 用实际值；起始 spec 交由 Link 按登记表解析 CRC。
- `tools/make_team_package.ps1`：团队包补齐 **linked/dpfix 两个固件** + **联动候选 manifest**
  （`build/host/gcs_pc_dp_link_20261017/manifest.json`）与发布校验所需引用文件（vitis lscript/system.mss/physpeed.c、
  build tcl/xdc 共 8 个）——否则队友拿到的包里原版控制台连不上、也没有联动固件。
- `README_运行说明.md`、`docs/team_package.md`：§六 DP 黑屏条目改为"linked 第一优先、dpfix 第二"；
  §八 身份说明更新为本地演示候选（release `473aafa8…`）；补"单点探查约 5 分钟窗口"说明。
- 新增 `tools/recheck_pc_dp_probe.py`：真板复核驱动（复位下载 linked → 起本地演示控制台 → 连接 →
  5×3 任务 → **经 JTAG 读回 DP 帧缓存探针卡区域（前/后）** → 网页同接口发探查 → 断言探针卡像素、
  板端 `S2C PROBE` 行、PC 结果字段三者一致）。用法：
  `D:\Anaconda\python.exe tools\recheck_pc_dp_probe.py all`

## 四、复核状态

- 本轮离线批次（py_compile、依赖检查、CPU 画布联动测试 `tools/test_gcs_roi_display_link.py`、
  启动器副本一致性、ELF 哈希）与 `recheck_pc_dp_probe.py all` 真板复核：
  **待补跑**（会话期间执行通道受限）。命令与断言已固化在脚本内，跑完会在
  `build/host/pc_dp_probe_recheck_<时间>/summary.json` 留下 PASS/FAIL 证据。

## 五、既有资产不动清单

- 发布身份相关文件一律未改：`gcs/**`、`model/**`、`src/hls/**`、tools 清单内 18 个脚本、
  `vitis/...` 引用件、`build/host/gcs_pc_dp_link_20261017/manifest.json`。
  因此本机与候选包的 release 绑定（`473aafa8…`）保持不变，控制台连接不受本次修改影响。
