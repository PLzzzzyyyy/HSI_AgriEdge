# 2026-10-08 r9受控诊断与Vivado实际实现授权交接

**2026-10-08后续已执行T3-D1：** P1核OOC完整P&R结束、无后台，最终LUT79.20%/CLB98.14%，WNS−0.488/TNS−18.119，5ns setup未过。小批RTL、P1诊断系统和P2系统仍未建立；新恢复入口`docs/m3_20261008_r9_p1_route_handoff.md`。用户明确最终主动用P2双上下文流水，以n16均摊评价2ms，不要求先单路2ms。以下原提示保留历史，不代表当前仍未启动P&R。

无后台；新诊断尚未启动。以下可直接复制。

```text
继续 D:\HSI_AgriEdge。r9实现及完整证据提交2e81a26；最新授权交接提交见git log -1 -- CODEX_CONTEXT.md。

先读CLAUDE.md、CODEX_CONTEXT.md顶部最新快照、docs/m3_2ms_task_plan.md、docs/m3_20261008_r9_diagnostics_handoff.md和report/m3_worker_r9_g2.md。详细技术继承docs/m3_20261008_t3_r9_handoff.md，但其中“建议未批准”已被最新用户授权取代；按需读取双方memory及相关pitfalls。

用户最新已明确：同意受控RTL诊断/验证顺序调整，并提出可直接做完整Vivado综合布局布线看实际结果；资源不要仅因HLS估计偏高而悲观。此项授权已获得，不要再只解释G2或重复询问是否允许诊断，应检查入口后实际推进。资源仍必须最终合法，不把“19w没问题”解释成通用LUT/FF阈值，不凭估计宣布可行。

当前无相关构建后台。r9完整CSim/P1 HLS/OOC均已结束；本轮仅核对了新诊断和系统构建入口，尚未启动RTL诊断、IP导出或新的Vivado综合/布局布线。恢复先核实际进程及最终回执，不盲目重启已有完成任务。任何新任务须等待结束、核对最终回执和报告后才常规收尾；未经明确同意不得带运行综合交接。

下一步：保留r9候选，不自动开r10追II1。优先评估并推进独立候选的Vivado实际实现（综合/布局/布线），并用受控P1完整12层小批RTL诊断取得真实数值/事务/背压和原始周期；按工具占用安排，不重复启动重任务。先用小批界定验证成本，再决定扩展n16，不能由n1外推n16。

现有G2自动前筛仍FAIL：主II22不是1，HLS LUT141958>117120。保留这条历史事实和前筛代码；本轮用户授权的是诊断例外，不是宣布G2通过。不要再仅因上述前筛FAIL阻止已批准的诊断，也不要暗改阈值把FAIL变PASS。未经相应证据，不宣布G3/G4、最终P2或整体验收通过。

必须清楚区分：
1. P1核OOC布局布线；
2. 集成PS/AXI/时钟复位后的P1诊断系统布局布线；
3. 最终P2完整系统实现。
当前已生成的是r9 P1 RTL/DCP，P2综合和S2新系统尚未建立。不自动扩大到P2交付，不把P1或OOC结果冒充完整最终系统。若当前只能跑核OOC P&R，明确范围；若推进完整诊断系统，必须在新目录真实完成接口集成、约束、DRC与实现，不能原样重跑旧M3a系统充数。

已核查的构建入口：
- build/hls/run_m3_s2_synth.tcl只做新CSim快照的csynth，没有TB/cosim/IP导出。
- tools/run_m3_s2_ooc.py与build/hls/map_m3_s2.tcl只做独立全核综合，生成匹配五浮点IP及DCP，没有place/route。
- build/vivado/build_m3a_zu5ev.tcl和build_zu5ev.tcl针对旧tt_engine，连接s_axi_CTRL、m_axi_FM、m_axi_WT，不适配r9。
- r9接口为s_axi_control、m_axi_wmem/inmem/outmem；weights走wmem，input走inmem，logits/classes/features共outmem。复用平台配置须新建独立系统，不能覆盖旧工程。原build_zu5ev.tcl有create_project -force和bit/XSA导出流程，不能不加边界直接套用。
- 可复用SHA匹配的r9原始RTL或OOC DCP做后续实现，不必无修改重复HLS综合。受控RTL诊断也优先使用已验证源码/RTL快照；如确需重生成应明确原因并保留原始证据。修改HLS源码则必须新针对性回归+新匹配完整CSim，再新tag P1。

r9最终技术事实：
协议24、极值/非均匀8、主机25及P1/P2/W16完整12层full+budget CSim全PASS；当前源/输入/CSim-HLS快照/OOC RTL SHA匹配。P2 W8 n16的6146618仅C迭代，非RTL周期或延迟估计。
P1 HLS tag20261008_t3_fix_r9完整1050.328秒：主II22/depth34、独立投影II1/depth20；LUT141958/117120、FF185346、DSP359、BRAM18=229、URAM13、4.769ns。
独立Vivado2020.2 OOC tag20261008_t3_fix_r9_ip，同器件xazu5ev-sfvc784-1-i、5ns、原五浮点IP，502.422秒完整结束，blackboxes0：LUT96928/82.76%、FF97373、DSP418、BRAM101.5Tile、URAM13；综合WNS+1.234/TNS0/setup失败端点0、WHS+0.050ns。非post-route/系统/200MHz上板/性能通过。
r8对照主II23/33，OOC LUT96678、FF73596、DSP370、WNS+0.795；r9调度改善有限、LUT基本持平、FF/DSP增加，不把HLS LUT下降当映射资源下降，也不因此先判P2一定不行。

固定方案不变：W8A8、最终P2共享核/copy2、K7/H4、单套权重投影核、原ob，消费者完成才RELEASE；P1只是前置/诊断配置，W16只兼容回归。保留T1/T2、PROJECT独立worker/FIFO START-DONE、原ob统一双读入口及COPY返回后lane分发，以及r7/r8/r9已有修订。最终meta ABI不变，核内计数drain后写回，不逐迭代外部更新。

r9原Slot sum/square/scores移出聚合且删除旧成员，无副本；统计按slot/token完整分割，scores仅分slot/token维、列保留LUTRAM。
sum/square本体各6×64寄存器，但各221个相关寄存器行/9608bit含phi/flag/流水；不能只按数组大小估成本。scores确为六个6×64分布式RAM，读port0/写port1；HEAD24×64寄存器；SCORE仍仅6个独立latency2、18个融合DSP48 latency0，不称全lane切断。
原ob仍42×432×8、port0读写/port1只读，各bank两处命名load；一个core_service/run/read_ob/wmem master，权重/ob归core_service、t1/t2归run、head归engine_task，无整套核/权重/ob复制证据；read_ob latency/interval仍6，双口不等于每拍返回两值。

若真实测量后决定继续局部优化，保留阻塞定位：日志2803 ctx_sum端口（24×40，源码229行24项同拍dump）、2805 attn端口（36×32，源码208行六token读）；2795—2801 NORMAL/TRANSFER jobs_active_0/7反馈。NORMAL120/CONTEXT208请求II1乘法时钟告警仍有；当前II22/OOC正裕量不能证明未来II1时满足时序。r8 mem_x告警本版未出现，但跨阶段同址生命周期未改，不用DEPENDENCE false，不宣称依赖已消除。这些不是已证实的II22全部根因。

2ms仅优化目标，不是必须达成的硬门槛；结合实际吞吐、瓶颈可突破性和修改代价取舍，未指定接近的数值容差，不擅设。固定n16、PS_EMBED_PLUS_FULL、CLASS口径。0.310391ms仅外部差额假设、5406748@200MHz仅2ms参考预算，不凭C迭代认定接近。正确性、资源、时序和证据要求不变。

证据report/m3_worker/20261008_t3_fix_r9/，尤其synthesis/fix_audit.json、physical_audit.json、review/与vivado_ooc/。raw_rtl.zip含137份原始RTL/数据/IP Tcl/详细调度。capture_final.py只重放核验、不启动综合，须匹配build树。
运行产物：
build/host/m3_s2_synth_20261008_t3_fix_r9/
build/host/m3_s2_ooc_20261008_t3_fix_r9_ip/
DCP为s2_engine_ooc.dcp，51477335字节，SHA256 fe8591606a8c7858ca9414b97f94fb5b4f01399b22f90e14b95f6b638ef1419a，留build未入库。

原XSA SHA256仍9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652。原XSA、Vitis平台/App不动，最终Build/下载由用户做。新诊断项目不得覆盖build/vivado内原工程或未跟踪工作；不默认生成或替换交付XSA/bit，更不能自动上板。
不转M3b/P3/第二ob/PS双缓冲/K14/H8/重训，不设token预算、不自动push。r4中断原因未独立证明，r6为pragma前端失败无最终II；保留这些历史事实。

结束执行四件套，逐项汇报提交/进度/踩坑/记忆，同步双方可访问memory及MEMORY.md，落实适用llm_log/evidence/复现入口，并直接贴下一轮可复制完整交接提示词。
```
