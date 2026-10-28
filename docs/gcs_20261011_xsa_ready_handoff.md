# 新XSA就绪 → 用户建平台/第一轮验收交接（2026-10-11）

> **16:30交接**：用户F盘容量只读发现小F卷及另一个大分区；尚未备份/改盘/写卡。用户要求新对话继续，最新入口`gcs_20261011_sd_capacity_handoff.md`。软件/ELF/新服务已就绪，不再Build、同步或重跑硬件。

> **16:10更新**：用户已许可并完成PC新服务切换，最后观察PID35444/127.0.0.1:8765，旧38476停止且旧证据保留；服务默认板卡锁定/UART TX0/无UDP。下一用户安全取卡提供盘符，助手只读核45数据文件及双journal，未provision/写卡/实机。当前不再要求Build、同步或再次切服务。

> **15:48更新**：用户v3 App已Build，正式ELF及生产只读门禁PASS；批准ELF a41bbdad…36e4d66。下一约服务窗口、确认SD身份/配套，随后用户下载启动及A～G/T实机。不要再同步、重Build或重建平台；先前“待Build”是历史。

> **15:46更新**：v3绑定已刷新，34源/14新BSP语法PASS；下一仅用户新App F5/Debug Build，再由助手自动找日志/审ELF。不再同步或重建平台，不提前下载/接入。15:38“未刷新”已是历史。

> **15:38后续进展**：用户新平台/首次App已Build，34源已同步；原ELF门禁的Vitis空构建元数据与旧DP符号检查已修正，33回归PASS。最新独立候选是`build/host/gcs_r1_abi4_release_v3`，需新绑定刷新后用户再Build App一次；不重建平台/XSA，不改.prj过关。当前未再同步、未批准ELF或实机。恢复以CODEX_CONTEXT顶部、user_acceptance_steps顶部和`report/gcs_roi/20261011_user_platform/review.md`为准。下文14:23历史保留。

## 结论与下一步

**可以新开对话。新硬件与本地完整源包已就绪；新平台由用户创建/Build，不能由Codex代建。** 下一先指导用户建新平台，核新BSP，再经当次确认同步源码、用户Build App与实机验收。第一轮尚未完成。

1. 新XSA：`D:/HSI_AgriEdge/build/vivado/tt_gcs_r1_abi4_zu5ev.xsa`，SHA256 `bc7dfb43856d2ce2fddbd727aedc91daa091cec7ac7b8f64f6ea7773f8a2d380`，3,376,874 B。
2. 新源包：`build/host/gcs_r1_abi4_release`，34 App源、103配套文件，release=`b01ce7b5a6efcc2ad402612a920341f9f2745428b3eac45f32c1613a79cbc3a2`。包内`app_src/roi_release.h`是绑定版，不能用仓库UNBOUND模板替换。
3. **详细步骤**：`docs/gcs_20261011_user_acceptance_steps.md`；完整范围：`docs/gcs_20261011_acceptance_matrix.md`。
4. 本轮证据：`report/gcs_roi/20261011_round1_xsa_ready/review.md`；原始运行：`build/host/gcs_round1_20261011_continue`。12:17 cosim证据继续保留在前一`round1_checkpoint`，没有重跑。

## 已验证的本轮增量

- SD INFO漏空包体已修；显式确认、错误版本/端点/旧boot/已有owner/超时门禁通过。ABI4 INFO末尾携带release前128位（48登记项时1404 B≤1412），生产接入/恢复核对新发布身份；这不是物理冷启动证明。
- 最新CRL driver10命令PASS；真实计数器+生成AXI-Lite独立边界测试PASS；原23次完整cosim周期原字保留，未重跑已PASS的RTL。
- IP经独立export副本/最终catalog输出，数值top RTL SHA仍`15e2a0a2224afd37fdb46b067fa0368ba58b47e4b157fca2057388daeb00cbfb`，与原cosim逐字节相同。原失败日志和原始导出均保留。
- 完整系统13:50 PASS：WNS=+0.081522ns，WHS=+0.006640ns；57818 LUT、70179 FF、113 BRAM Tile、620 DSP、20 URAM。148315条可布线net全部完成，routing error=0，12类check_timing计数均0；DRC保留712 Warning+4 Advisory，**不是零告警**。
- 45顶层私有App命令（含runtime子套件）、7真实协议/GCS管道用例、19条最终增量/A53命令、93浏览器检查通过；本地绑定源包14个CPP用**既有BSP**语法通过，非新平台/ELF Build。
- G已写新清单/标记/源包/同步器/ELF门禁；server两入口不再调用旧24源审查。UART保存绑定ELF证据，旧Python配新静态页面不能点新接入。实际新平台/同步/ELF尚待用户，不能把工具夹具视为真实部署通过。

## 未执行、不可抹掉的事项

- 未创建/Build新平台，未运行XSCT生成FSBL/PMUFW/BSP；没有`build/host/gcs_r1_abi4_vitis`。原候选`prepare_gcs_platform.tcl`已标参考并主动拒绝执行；`gcs_release_platform.py`现仅核**用户已建**平台，`--sync`需确认自动Build关闭。
- 未同步新App源码、未Build/下载新版ELF；未生成BOOT.BIN/初始journal分发包/写卡/启动模式/上下电/训练/新板任务。
- 全部新增/受影响A～G/T实机项仍待验，尤其真SD冷扫/持久化、安全切换、真实训练后上传激活+同ROI新板任务、DP/PC、真注意力/计时和安全故障方案。
- 用户随后要求第一轮完成后启动第二轮，但**只有全部必需实机项及最终证据通过才触发**；当前不启动USB/提速/旧P2，不使用goal或token预算。
- 新平台实物布局、库/头差异和用户ELF符号/低DDR布局仍需实测门禁。若候选工具发现真实差异，保留原失败并定位，不降低检查或拿旧平台填补。

## Git与旧服务

- HEAD仍`195682b`，已提交功能`0d214f2`；本轮与前序未提交差异保留，暂存区未操作。不自动commit/push，不夹带用户Vitis/Packages/旧ELF。
- 最终只读进程/端口/GET回执见新报告`handoff_observations`。旧HTTP38476/8765允许保留，Python未加载候选；`bb6bd8e3`禁复用。恢复先核实际进程/命令，不按历史PID操作，不重复起服务或重跑旧板测。
- 本轮硬件/测试进程已退出；收尾归档结束后再交付最终提示词，不带未完成硬件任务给下一会话。

## 可直接复制到新对话

```text
接手 D:\HSI_AgriEdge，继续第一轮。先只读git status/log；HEAD应195682b，已提交功能0d214f2，本轮及前序交接文档未提交。保留工作树/暂存区/用户旧Vitis与Packages，不自动commit/push；不使用/创建/恢复goal，不设token预算。
依次读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/gcs_20261011_xsa_ready_handoff.md、docs/gcs_20261011_user_acceptance_steps.md、acceptance_matrix.md及report/gcs_roi/20261011_round1_xsa_ready/review.md。其余记录/双方记忆/pitfalls只按需读。
新XSA已13:50完整系统PASS：build/vivado/tt_gcs_r1_abi4_zu5ev.xsa，SHA bc7dfb43856d2ce2fddbd727aedc91daa091cec7ac7b8f64f6ea7773f8a2d380。WNS+0.081522ns/WHS+0.006640ns，非板测。12:17完整cosim PASS与新IP/系统均不要重跑或覆盖；当前本轮后台已结束，历史PID不能复用。
本地源包build/host/gcs_r1_abi4_release已准备，34源/103配套文件，release b01ce7b5a6efcc2ad402612a920341f9f2745428b3eac45f32c1613a79cbc3a2；只导入包内绑定版roi_release.h，不用仓库UNBOUND模板。新门禁已接，但新平台、实际源码同步、用户App Build/ELF/板测都未做；候选工具未在真实新平台验证。
最新明确边界：新平台也由我创建/Build（含BSP/FSBL/PMUFW），App创建/Build、下载、写卡、启动模式、上下电和实机均由我。先一步一步指导我建新平台，不运行平台生成脚本；我给路径/日志后你只读核新BSP。只有我确认自动Build关闭并允许同步，才用新gcs_release_platform.py同步新App的34源，保留项目配置/备份，再我Build、你只读ELF审查。不能用旧24源scene_probe_s3_r1工具。
E/F/T2已授权同范围不重复询问；范围外/BSP变化另确认，真实训练我显式发起，具体故障方案先确认。默认板卡，无PC推理/参考成绩入口，保留PC中央主图/原配色布局图例缩放框选，DP显示同任务结果。注意力须真实12x6x6 Q0.24；墙钟不是纯PL、计时子集不重复相加。
旧HTTP38476/127.0.0.1:8765允许保留，先只读核进程端口GET；旧Python未加载候选、bb6bd8e3禁复用，不重复启动服务/旧板任务，最终切换先约窗口。第一轮保留真SD冷扫/持久化、安全切换、真训练后上传激活和同ROI新任务、PC/DP、全部A～G/T新增/受影响实机验收与最终证据。只有全部通过后才按我要求进入第二轮；当前不启动USB/优化/旧P2。四件套及双方memory索引按项目规则维护，不自动提交。
```
