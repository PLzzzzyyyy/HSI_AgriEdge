## 2026-10-11 14:23 新入口：新XSA已完成，由用户建平台

本文件以下12:21内容是历史检查点。当前新IP/完整系统XSA及本地34源/103配套包已就绪，原cosim不重跑；**用户亲自新建/Build平台，Codex不生成平台/BSP/FSBL/PMUFW**。仍未同步App/Build/设备/实机，第一轮未完成。请改读 `gcs_20261011_xsa_ready_handoff.md` 和详细 `gcs_20261011_user_acceptance_steps.md`、新证据 `report/gcs_roi/20261011_round1_xsa_ready/review.md`。本轮后台已结束，旧HTTP按许可保留；不自动提交，不使用goal。

# 第一轮实施检查点交接（2026-10-11 12:21，后台已结束）

**最终后台结论**：用户要求等待后，原完整RTL cosim于 **12:17:03 PASS**，23个调用完成；C/RTL后检3×12×36注意力字全匹配、普通CLASS/LOGITS/FEAT/PROJ通过。12:18核runner/HLS/xsim/xsimk均退出，没有启动export/system或新测试。最终原始回执/RTL/DMA输出归档在 `report/gcs_roi/20261011_round1_checkpoint/receipts/hls_cosim_final/`；`*.prefix`仍保留为旧时点，不能当最终。**这不是完整系统/最后工作树/实机PASS**；最新SD发现与CRL等缺口、G未接、全部A～G/T实机仍保留。

用户因上下文过长要求收尾、给新对话提示词，并随后说“jixu”。当前只做收尾，不继续新增实现/测试或启动下一硬件阶段。**本轮已有实质实现，但全部候选仍未齐、第一轮未完成。** 不使用/恢复/创建goal，不设token预算，不自动第二轮。

## 1. 恢复现场与后台门禁

- HEAD仍为`195682b`，最新已提交功能仍`0d214f2`；本轮实现及前序8份交接文档均未提交，暂存区没有本轮操作。用户未另行授权本次Git提交，不自动暂存/commit/push。保留用户Vitis/Packages/旧ELF及其他产物。
- 已按用户要求等待原任务自然结束，12:17 cosim PASS、12:18四个任务进程退出；不带后台交付，不启动后续阶段。11:53/11:59进度前缀作为历史保留，最终文件另存。
- 原runner PID`42012`，HLS`43768`，xsim`27796`，xsimk`27080` **均已退出，仅历史定位**。原命令：`D:/pytorch/python.exe -u -B tools/run_gcs_hardware.py cosim --out build/host/gcs_round1_20261011/hls_cosim_declaration_fix`。runner cwd为`D:/HSI_AgriEdge`；HLS cwd为上述输出目录，xsim执行目录为`build/hls/optimization_build/tt_engine_gcs_r1_abi4/sol/sim/verilog`。
- 恢复先只读核当前Git/进程和最终`run.json`/`console.log`/cosim报告；PID可能重用，不能按历史PID操作。**本次RTL已PASS，不重复启动/重置/删除候选**；下一阶段需要审查导出/系统门禁，不凭HLS exit0或cosim PASS关闭完整系统。
- 旧生产服务PID`38476`/`127.0.0.1:8765`允许保留；**12:25收尾**GET仍done220000、UART inactive/released、无同PID UDP，本轮任务后台为空，原始观察已归档。命令与日志仍`D:/pytorch/python.exe -u -B tools/gcs_roi.py serve`、`build/host/gcs_service/20261010_192446`。**旧Python没有加载候选，静态页面已变化不等于新版部署；bb6bd8e3禁复用。** 恢复只读核，不新起服务、不START、不重跑旧板PASS。

## 2. 已写入工作树的候选

### E：真实注意力链路

- `src/hls/tt_engine_regs.h`升级ABI4，OUT=3为全12层注意力；TTE2权重包版本仍2。每patch输出1920字节：64字节头、128字节LOGITS、1728字节12×6×6 uint32 Q0.24。普通CLASS/LOGITS原布局不变，禁止部分层/DUMP混用。
- `tt_engine.cpp`直接复制**实际softmax后、CTX消费的矩阵**，无PC重算、无MODE_DUMP特征替代，无新增训练或数值优化。继续串行K7/DB18、`TT_M3_OVERLAP=0`，不是旧P2。
- driver扩容/输出模式/cache，runtime保留故障停车和成功CPU前缀；跨模型PROBE恢复原模型成功后才交付结果。私有协议通过PROBE flag bit0请求，`0x87`两片各216字，带boot/session/task/request/scene/model/坐标、总CRC与固定布局；同seq重发缓存、不重新运行PL。
- GCS接收严格重排/重复/冲突/丢片门禁；独立核验器读原始包和UART整体/每层CRC；PC沿用现有注意力图/层滑条，不增加DP式面板。最后细节修改及新SD入口之后没有最终完整回归，不能称最终已验证。

### F：SD身份/独立接入与镜像准备

- `roi_boot_id.{h,cpp}`/`roi_boot_sd.cpp`：预置两个64字节持久记录，启动先读两份、核CRC/补码/安装nonce/连续代数，覆盖旧槽、sync/close、重开两份逐字读回、卸载成功后才发布新boot/READY；失败不修复、不回退到PC熵、不发起任务；同App只尝试一次。
- `main.cpp`已改为SD来源，不读取UART身份；`uart_capture.SdIdentity`及Capture改为RX-only，旧Identity类仅保留历史离线测试，不在生产入口使用。PC观察身份也有本地no-reuse记录。
- **FAT/SD整卡回滚、克隆及“设备声称写成功但掉电后丢失”的存储保证不由软件证明**。无静默重置/修复；更换介质需新安装，初始journal绝不可覆盖已用卡。真实掉电方案须用户先确认。
- `gcs_boot_provision.py`、`gcs_boot_bundle.py`、`board/boot/gcs_round1.bif.in`和`gcs_sd_boot_verify.py`已写候选，但没有生成BOOT.BIN、初始身份文件包、复制45个数据文件或操作SD。镜像工具依赖将来的新版ELF审查结构，**G尚未实现故当前不可用来打包**。
- 最后新增`board_boot.py`、`POST /api/board/sd_connect`及原连接区按钮：用户显式确认后只INFO发现ABI4新空闲boot，关闭发现socket，再允许未来显式任务；不开串口、不自动PING/START、不接管旧任务。**这组最后修改与`test_gcs_boot_discovery.py`尚未运行测试**；没有UART时内部UART细分仍未测，不能拿网络端到端补数。

### T2：真实计时口径

- `tt_measure.h`选择性single-owner采样，`tt_net.cpp`在原取窗/归一化/embed循环插桩，`m3a_roi.cpp`单列校验；driver分cache_prepare、寄存器/start submit、engine wait、cache_complete；wait_service是wait内部子集。任务步、setup/LOAD_W、PROBE等口径仍区分。
- 私有App现有9桶和compute_us保留；新增TASK_DETAIL/TASK_ENGINE、GCS解析/报告/原折叠表。内部各项是step子集，PL周期又是submit/wait内的独立计数，不能把它们重复加到墙钟。
- HLS C的`cycles=0`不是真测量。`src/rtl/tt_gcs_cycle_counter.v`和严格匹配的RTL安装器接管现有cycles寄存器，计accepted start→done（含PL侧AXI停顿、不含PS）；0/饱和均无效，driver拒绝。
- **名义200MHz与实际配置分频分开**：PS参考33,333,000Hz，RPLL48/2/4得到199,998,000Hz；Vivado ACT_FREQMHZ为199.998001（浮点生成差1Hz）。新增driver只读CRL分频/锁定/整数PLL检查，不匹配不报PL测量。最后该driver扩展尚未重新跑完整driver/numeric套件，A53新入口需补验证。

## 3. 已有离线证据和明确覆盖缺口

归档：`report/gcs_roi/20261011_round1_checkpoint/`。原运行：`build/host/gcs_round1_20261011/`。

| 记录 | 观察结论（只对当时输入） | 不证明的内容 |
|---|---|---|
| attention_csim_abs.log / hls_synth | 3输入×12层共1296 Q0.24原字一致；普通CLASS/LOGITS/FEAT/PROJ回归；HLS综合PASS | RTL最终/新IP/完整系统/板测 |
| HLS资源估计 | BRAM18=231/288，DSP588/1248，FF81943/234240，LUT110488/117120，URAM20/64 | 不是Vivado实际资源或时序通过 |
| driver | 10条命令exit0，含8运行模式、注意力实际HLS C+driver缓存/guard、0/饱和反例 | 周期值由host显式12345夹具注入；后加CRL检查未复验 |
| numeric_timing | 9条命令exit0；真实PS数值/driver与独立取窗对照、8 ROI形状、6运行模式 | 合成MMIO/时钟，非真实PL/板时延 |
| private_app | 45顶层命令exit0；内含20 runtime模式（注意力/坏头/恢复失败），7入口A53语法、5等待服务、模型协议/画布/配对 | main不是执行测试；最后源修改未被完整覆盖；语法不是Build |
| interop | 7管道用例PASS，实际私有协议/Models/ModelSd与GCS字节接通 | RAM FatFs/合成调度数值，不执行真实main/PL/物理SD |
| boot_checks_fixed | 编译+14 RAM文件系统模式+UART RX-only合计16命令exit0 | 不证明真实SD/掉电/冷启动；无UART入口后加未测 |
| browser | 87离线检查PASS，注意力/内部计时/清旧/旧布局；2张新fixture截图目视 | 在最后SD按钮/文字细节前运行，**不是最终工作树全PASS** |
| 小型解析/boot_tools/timing等 | 12项及后续14项unittest曾在工具输出PASS；部分仅工具输出，无新增原始日志 | 不把口述观察伪造成已归档独立回执 |
| RTL counter/完整cosim | 单模块Icarus边界/复位/饱和仅工具输出；完整23调用Verilog cosim最终PASS，原cycles寄存器输出随23事务归档 | 不等于计数边界与完整引擎/AXI-Lite端到端独立审计通过，也不是板测 |

已保留真实失败：缺attention契约编译RED；相对`__FILE__`定位失败；boot缺头/编译警告；Python接收分片别名导致冲突漏检RED；首次RTL cosim声明顺序FAIL（Vitis仍exit0），修订后12:17完整PASS。`test_input_drift.json`明确记录部分测试后改源；哈希匹配也不能替代最终检查，尤其计时器/SD发现最新增量。

## 4. 下一实施轮的阻塞顺序（不跳到用户Build）

1. 先核已完成RTL最终回执（12:17 PASS/进程退出），**不重跑本次cosim**。下一审查导出是否保留counter、现有testbench逐层/普通行为覆盖及真实周期寄存器绑定；仍可能需补明确的完整RTL周期边界独立核验。export/system工具未运行，不能盲跑自动串联。
2. 修整并定向验证最新增量：SD-only发现（含旧boot/非空session/错误端点/版本拒绝）、GET被动/原UI布局；单模块boot工具/镜像门禁；CRL时钟driver与A53；计时合计/独立核验；注意力部分/冲突/回放与跨模型恢复。保留合成/实机界限。不要为凑进度重复旧PASS。
3. `tools/check_gcs_hardware.py`、`build/vivado/build_gcs_round1.tcl`尚未执行，需本地审查后以**独立ABI4候选**完成导出/全系统资源/时序/XSA。旧串行XSA SHA`9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652`不得覆盖。
4. **G明确未接**：App/uart/独立核验多数仍`model_lifecycle_r1`，boot工具预期`gcs_r1_abi4`；`server.py`两个连接入口仍调用旧`gcs_board_batch.audit(...gcs_scene_probe_s3_r1)`；旧24源prepare/sync/audit完全不能用于当前工作树。全部候选齐备后才统一改全量源/资产/硬件/数据清单、标记、同步器和ELF审查。当前禁止prepare/sync，不建议用户Build。
5. 新平台的BSP/DP/lwIP/FatFs/PHY差异和FSBL/PMUFW需完整来源核对，不能把旧平台/旧ELF放进新BOOT；保持standalone。范围外driver/BSP/公共契约扩展先集中说明再确认。用户Build/下载/写卡/启动模式/上下电/实机、显式训练和具体故障注入门禁不变。
6. 完整A～G/T矩阵全部保留：真实SD持久化/冷扫描、安全激活、显式真实训练后配对导出/上传/激活/同ROI新板任务、DP/PC目视、尾批/停止/补传/恢复/四槽/报告/固定Test100、最终时延原始证据。全部新增/受影响实机通过前第一轮不完成。USB/优化/旧P2后置。

## 新对话提示词（当前后台已结束，可以恢复实施）

```text
接手 D:\HSI_AgriEdge，继续第一轮补齐实施，不做重复只读盘点，不使用/创建/恢复goal，不设token预算，不自动第二轮。
先只读git status/log；HEAD上次195682b，前一功能0d214f2。本轮E/F/T2部分候选及前序8文档都未提交，保留工作树/暂存区/用户工程，不自动commit/push。
按顺序读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/gcs_20261011_round1_resume.md、docs/gcs_20261011_acceptance_matrix.md、report/gcs_roi/20261011_round1_checkpoint/review.md；其余只按需读。
完整RTL cosim已于12:17 PASS，原runner42012/HLS43768/xsim27796/xsimk27080已退出。先核最终回执，不重跑本次cosim、不复用历史PID；日志build/host/gcs_round1_20261011/hls_cosim_declaration_fix/{run.json,console.log}。独立候选tt_engine_gcs_r1_abi4，旧XSA不动，尚未export/system。
E真实12×6×6 Q0.24/HLS-公共输出-driver-cache-UDP-IP/XSA、F SD身份/持久记录/失败门禁、T2公共数值-driver必要细分计时均已明确授权，不重复询问同范围；范围外扩展另确认。当前已部分实现，未全部最终验证，G未接、实机全待测。按交接剩余顺序完成全部候选，不只做一项就结束。
注意：新SD-only以太网发现组最后加入还未测；CRL分频检查/最新UI未被原PASS覆盖。driver真实周期不是host合成12345；计算墙钟不能称纯PL。先定向验证最新增量、审查导出和全系统门禁，再完成新IP/全系统。全部候选齐备后才统一源/资产/标记/同步器/ELF门禁；当前server仍接旧24源审查，不能prepare/sync或让我Build旧清单。
我负责Build App、下载、写卡、启动模式/上下电/上板验收；真实训练由我显式发起，故障注入先确认安全方案。最终给完整A～G/T验收包；不把RAM/合成/语法/旧PASS当新版板测。
默认板卡推理，保留PC原中央地图/布局配色/图例缩放框选，DP显示任务结果，错误未测如实标。旧HTTP38476/8765允许保留，先只读核进程端口GET；旧Python未加载候选，禁复用bb6bd8e3、不重复起服务/旧板测。最终切换先明确窗口。USB/优化/旧P2不启动。
```
