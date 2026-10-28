# v4 源码同步与用户 Build 后的验收交接（2026-10-11 21:23）

## 1. 当前结论：Build 已完成，尚不能下载验收

- 起点 HEAD `4665e7f`；本轮提交用 `git log -1 -- docs/gcs_20261011_v4_acceptance_handoff.md` 定位，不回退、不自动 push。只提交任务源码/测试/证据/交接文件，原未跟踪生成物、第三方、旧 ELF、历史 Build 与会话导出不动。
- 三项遗留失败已修：PROBE 包式/直接入口；精确 35 源路径集合（新增 `roi_board_log.h`）；前缀夹具补真实签名替身，意外驱动调用无条件 abort。完整离线入口 **97/97 PASS**，36 Python 模块/236 测试、14 当前 BSP A53 语法、86 AST、17 JS 语法、96 浏览器检查；models 45、interop 2 个嵌套命令通过，不重复计入顶层。
- 全新 `build/host/gcs_r1_abi4_release_v4` 已冻结：35 源、105 host assets、45 本地数据文件/1,150,149,380 B；191 IP 文件及既有 XSA、2043 当前用户平台文件只读核验。默认路径在冻结前改为 v4，原 v3 包 142 文件未变。
- v4 release ID：`2ece7a6edbaed994dc6951fbb7ad5a76f8a785fda751632388bb195b5ecb337c`。
- 用户本轮授权“验证完直接同步就好”，随后确认不会自动 Build；35 源已同步到 `build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_app/src`。5 文件字节变更 + 1 新增头；14 绑定源码语法通过。12 同步守卫与 6 元数据恢复测试通过。
- 首次同步末检被 Vitis 自动插入 Debug `dirty="true"` 拦下；原 FAIL 保留。只读确认恰好 13 B 标记变化、既有严格规范化相同后，**不重拷源码、不改配置**完成回执。`v4/sync.json` 正式存在。
- 用户随后确认 Build 完成；实际 ELF 于 **21:09:33** 更新，完整 Console 于 **21:09:34**结束，已复制保存。**现在不要求原样重复 Build。**
- **正式 ELF 发布门禁 FAIL，未注册 `v4/approved_elf.json`，未下载、未切服务、未板测。**失败原因与下一步见第 2 节；不能把离线全绿写成第一轮完成。

## 2. 新对话首先处理的唯一已定位发布卡点

新 ELF：`build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_app/Debug/gcs_r1_abi4_app.elf`，3,167,168 B，SHA256：
`febc4d3a290f402ac19325b8932c54fda1d96aa5483900313052d6ba4aa0e3b9`。

242 B 的完整 v4 BUILD 身份在 ELF 文件中出现两次：

| 文件偏移 | 区域 | 是否运行时加载 | 只读判断 |
|---|---|---|---|
| `0x73a40` | `.rodata` | SHF_ALLOC；落在一个 PT_LOAD 内 | 唯一 `gcs_release_identity`，符号大小 243 B（含 NUL） |
| `0x94a5d` | `.debug_info` | 非 SHF_ALLOC；不在 PT_LOAD 文件范围内 | DWARF 调试副本，不是第二个运行身份 |

没有 `UNBOUND_RELEASE`。现有 `tools/gcs_release_elf.py:audit` 对整个文件 `data.count(identity)!=1`，所以误拒；`gcs_release.py:audited_elf` 和 `gcs_release_platform.py:check_refresh` 也有同类判断，下一轮应一起核清。没有修改这些门槛、删调试段、strip 或回写 ELF。

独立只读补查：14 条真实编译命令/数值 flags、A53 LOAD/入口布局、12 缓冲区、16 必要符号通过；**不替代正式门禁或构成批准**。正式审查在创建 out 目录前失败，因此没有 `elf_review_v4_readonly_01/audit.json`；真实 FAIL 是下列 `user_elf_readonly.log/json`。

下一轮修复要求：
1. 先核实际 HEAD/status/index、ELF 与冻结回执 SHA；不重跑已知失败来覆盖原证据，不读整份会话导出。
2. 针对真实 Debug ELF 修严格的加载态身份验证：唯一身份符号/有效字节范围/PT_LOAD/预期完整绑定必须成立。非加载调试副本不能冒充运行重复；额外加载身份、错误/缺失/UNBOUND、损坏 ELF、错符号/越界仍拒绝。不能简单把计数放宽为 `>=1`。
3. 用本轮真实文件和聚焦正负夹具先 RED/green；同步核正式 audit、生产 audited_elf、validator refresh 的身份入口，不做生产特例绕过。
4. 修验收器会改变受绑定 host assets；**不得改现有 v4 manifest/包来补绿**。门禁完成后另建下一全新版本（如未占用的 v5），先决定默认路径再冻结。新源码绑定/再次用户 Build 的必要性须解释并取得当次许可；不未经许可再同步。
5. 仅当旧新硬件/数据/固件 source_set 完全相同、差异确实只有受允许 validator 资产及绑定头时，才考虑旧 `--refresh-from`；它仍不是通用源码升级入口。本轮一次性源码同步/恢复脚本均已执行，不要再运行。

## 3. 新对话恢复入口与必须保留的文件

按顺序：`CLAUDE.md` → `CODEX_CONTEXT.md` 顶部 → 本文件 → `report/gcs_roi/20261011_ethernet_v4_release/review.md`，再读相关坑、共用进度及双方记忆索引。

- 全绿离线输出：`build/host/gcs_ethernet_v4_resume_02`。上一轮整体 FAIL：`build/host/gcs_ethernet_v4_regression_01`，原位保留。
- 本轮原 RED/green、真实输入、ELF FAIL/定位：`build/host/gcs_ethernet_v4_release_checks_01`；重点 `user_elf_readonly.log`、`new_elf_identity_verified.json`、`user_elf_supplemental.json`。
- 原始 80 文件 App 备份与首次同步 FAIL：`build/host/gcs_r1_abi4_user/source_sync_v4_01`；最终只读完成回执：`source_sync_v4_finalize_01`。
- 用户本次完整日志与未批准 ELF 本地备份：`build/host/gcs_r1_abi4_user/user_build_v4_observed_01`。其中 `gcs_r1_abi4_app.build.log` 是此次完整日志，平台 51 B no-op 日志不能替代历史完整平台 Build 日志。
- 旧批准 ELF `a41bbdad…36e4d66` 在 `app_before_ethernet_v4_sync.zip` 中完整保留；当前 App ELF 已由用户 Build 改为上面的新 SHA，不能再宣称当前路径仍是旧 ELF。
- 归档证据：`report/gcs_roi/20261011_ethernet_v4_release/{closing_summary.json,manifest.json,receipts.zip}`。两代 ELF、App 备份、XSA 与模型大文件只留本地，不提交这些二进制。

## 4. 发布门禁通过以后，才逐步上板

以下是**后续操作顺序，不是已经批准或已经完成的动作**。每阶段失败都停下保存原始回执，不反复 START/重启试运气。

### 4.1 正式新 ELF 审查

保存真正对应新绑定版本的完整 Build Console，核完整编译/链接、全部 source/host assets、平台/IP/XSA/数据、唯一加载身份、DDR/缓冲、必要符号。通过后按当次许可注册新 `approved_elf.json` 并核生产门禁。不要借旧 v3 审查或本轮补查充 PASS；只缺日志时先找原 Console，不为补日志立即重 Build。

### 4.2 明确服务窗口

原 GCS 最后确认 **PID35444 / 127.0.0.1:8765**，命令 `D:/pytorch/python.exe -X utf8 -u -B tools/gcs_roi.py serve --port 8765`，cwd `D:/HSI_AgriEdge`。21:09 被动 GET：无任务/owner、authorized=false、UART released/TX0，旧后台没有 `board_records_protocol=1`。全部本轮临时测试/同步进程已退出。

重新核现场，取得当次服务切换许可，保存旧状态/日志后才替换；后台启动隐藏窗口，不重复起 8765。新服务 GET 应显示网络记录协议能力，初始仍未授权板卡；服务启动本身不发 START/控制、不打开串口。没有许可不停止原服务。

### 4.3 用户 JTAG 首次启动，按真实方式接入

1. 不重建既有平台/HLS/XSA；用户使用正式批准的那个新 ELF。核用户启动配置，先前 PMU-FW 未运行警告单独处理，不假定已解决。
2. 用户按当次许可下载/运行；当前首测是 JTAG 就选 **“JTAG 下载运行”**，不能为了绕过门禁选择“SD 启动”。无需串口输入或手填身份。
3. 浏览器打开 `http://127.0.0.1:8765`，在“连接板卡”里选择真实启动方式，点 **“连接 / 刷新启动状态”**并确认当前无任务。这只查询真实身份/板端启动记录，不下载、复位、推理或接管旧任务。
4. 必须看到实际 BUILD 与批准 release/source/XSA 相同，boot 为真实 SD 预约所得且不复用，启动完整/ready。扫描尚未完成则保留状态/原字并有界刷新，不能把无响应臆断成“仍在读 SD”。错误、溢出、丢页、身份不符就停。
5. 已用 journal 绝不初始化回退或重拷。旧 RX 的 boot `228ce0e9/generation1`、`228ce0ea/generation2` 都是历史，不是下一次可手填的身份；JTAG 首测不等于 SD 独立启动。

### 4.4 小任务 → 生命周期 → 三景/整景

- 先选实际登记的 scene/model，小 ROI（如 5×3）核真实 CLASS/seen、坐标/CRC/boot-session-task、PC 图与 DP。通过后再选足够长的 ROI 测暂停/恢复/停止；不要指望极短任务留出暂停窗口。
- 核暂停时提交前缀保持、恢复不重算/不混入旧行；停止后只保留真实前缀，新任务清旧；同连接继续控制、终态取证，模型事务进行时取证必须等真正空闲。
- 三景边界/小图/整景按矩阵逐项；历史、刷新、后端重启恢复及第五任务回收，必须是原任务身份和真实落盘结果，不重发旧 START。断线/损包/电源故障的具体注入先取得许可。
- “核验任务并下载证据包”只核现有任务，不补跑；采用当前以太网 BoardLog 原始页/字节/CRC/SHA/批准 ELF。不要照抄历史文档中的 `--uart` 必需条件，不缺证据时回退旧 UART 或 PC 重算填值。

### 4.5 E/T 注意力与计时

每景记录左上/中心/右下等约定坐标，核真实 LOGITS、两片注意力/432 个 Q0.24、12 层 CRC/顺序/完整性；冲突/丢片拒验并清旧，不能补 PC 数据。

计时核 TASK_CLOCK/PHASE/DETAIL/ENGINE、提交像素和实际 STATUS：App 前台桶、PS 预处理、driver cache/submit/wait/complete、PL 周期分别记录；wait_service 是子集，不重复相加。配置频率 199,998,000 Hz 与名义 200 MHz 分列，不称晶振实测。旧 compute_us 不是纯 PL，2 ms 仍是优化目标而非新造硬阈值。

### 4.6 D/F 模型、SD 持久化和独立启动

- 上传前固定两包 SHA/CRC、tag/checkpoint、scene/ABI。核事务及有界续传、失败不激活、终态安全切换；PC 文件/DDR/RAM 夹具不证明 SD 落盘。
- 用户授权的断电/冷扫后，核实际两包与 cube、同模型/同 ROI 新任务；真实训练必须用户显式发起，保留旧模型任务→Train100/训练日志→新配对包→上传/激活→同 ROI 新板任务链条。只在共同真实像素上比较，不把训练参考精度当板测。
- 真正 SD 独立启动另行准备同一批准版本的 BOOT.BIN/FSBL/PMUFW/bit/App 并授权写卡/切启动方式；本轮没有生成镜像或动卡。**已有安装不能再跑 new-installation/provision 覆盖 journal。**
- 用户实际去除调试下载依赖并冷启动，记录 READY/DP/身份、再次冷启动的 generation 前进及持久化原证据；网络身份就绪不单独证明物理断电和独立启动。

## 5. 第一轮关闭条件

继续使用 `docs/gcs_20261011_acceptance_matrix.md` 的完整 A～G/T 要求；旧状态段落是历史，不恢复旧“未建平台/未准备 SD”等动作。第一轮所有必需实机证据全过才第二轮，不启动 USB/性能优化/旧 P2。收尾依旧执行提交、共用进度/当前快照、坑、双方可访问 memory 与索引，以及 llm_log/evidence；不使用 goal/token 预算。
