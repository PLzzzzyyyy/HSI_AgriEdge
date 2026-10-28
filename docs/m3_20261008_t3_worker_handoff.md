# T3 worker修订交接：r4新P1运行中，未授予G2 PASS

> 历史交接已被取代：r4中断无最终报告；r5完整HLS与Vivado OOC均已结束，无后台。主II64/投影II14仍未过；Vivado OOC LUT84436/72.09%，不能把HLS估计当真实超限。当前恢复见docs/m3_20261008_t3_r5_handoff.md和report/m3_worker_r5_g2.md。

2026-10-08，起点ccd8758；本轮只做T3。提交定位：git log -1 -- report/m3_worker_t3.md。
先读CLAUDE.md、CODEX_CONTEXT.md最新快照、docs/m3_2ms_task_plan.md和report/m3_worker_t3.md。

## 已落实的代码修订

1. PROJECT移出主schedule_loop进入独立core_service；START/DONE使用深度2请求/响应FIFO，
   单套Projection/权重/xb/原ob归worker，engine只处理事务。
2. ob仍Act[6][2][7][216]，token/b分bank、parity在深度；唯一read_ob双读入口与COPY lane分发隔离，
   RESIDUAL复用同入口。copy2/H4不变，消费者写完并提交RELEASE才放行下一producer。
3. r3首次尝试曾让engine与worker均读wmem，完整CSim通过但184.911秒后前综合失败：
   HLS200-1013/200-984；没有最终LUT/II。r4已改为engine唯一AXI读者，
   通过同一请求FIFO发W12/W3/EXP装载worker单套权重，CORE_LOAD作为完成ACK。
4. 超时先排空已接受响应再STOP；错误reload不装载worker；协议显式初始化所有ap_int字段。
   不用DEPENDENCE false、不增第二ob/权重核/AXI master。

## 最终验证与证据

- **最终r4**：协议24条记录（4编译+4正例+16负例）、极值8条、完整主机25条全部PASS。
  覆盖bank/parity/tail、consumer lifetime、背压、W16 group13及三种原系统负例/四种新协议负例。
- **20261008_t3_fix_r4 P1/P2/W16完整12层full+budget CSim全PASS**；当前源/快照/81输入/102集成产物哈希匹配。
- report/m3_worker/20261008_t3_fix_r4/integration/manifest.json及archive_manifest.json；
  相邻r3/failed_synthesis为前一尝试真实失败。r3以及修改前T2的CSim都不能替代最终r4。
- P2 W8 n16目前6138460 **C迭代**，不是RTL周期，握手存在新增开销；不能声称2ms已达成。
- 13门禁+5旧证据复核PASS仅证明测试工具，不等于新硬件通过。

## 当前后台：先核对再操作

工作目录D:/HSI_AgriEdge；新P1于2026-10-08 12:26:41启动，交接时仍运行中：

```powershell
python tools/run_m3_s2_synth.py --csim-tag 20261008_t3_fix_r4 --only 8p1_pack --tag 20261008_t3_fix_r4 --timeout 10800
```

- Python启动器pid6764；shell pid29344；HLS pid37548（PID可能失效，必须实际核对）。
- 状态/日志：build/host/m3_s2_synth_20261008_t3_fix_r4/running.json、results.json、8p1_pack.log。
- 工程：build/hls/optimization_build/m3_s2_syn_8p1_pack_20261008_t3_fix_r4/。
- Vitis HLS2020.2，xazu5ev-sfvc784-1-i，5ns；尚无完整新P1资源/主II/实际端口结论。
- r3旧进程已结束；CSim/主机均完成。P2综合未启动。不依赖聊天tool session ID恢复，不重复启动已有构建。

## 下一轮仍只T3

1. 收取r4最终日志/阶段回执和报告。命令exit0不等于综合完成；无最终报告就保留对应阻塞。
2. 复核顶层合法资源、主schedule_loop、独立project_loop、实际ob双口调度、权重/投影核单套无隐藏复制。
   不能用局部II1或C迭代代替主循环/完整RTL。
   旧tools/review_m3_s2_t3.py假设内存在engine；新内存在core_service，需按真实层级复核，
   不能把空匹配/未发现bank当PASS。保留实际RAM包装和调度原文证据。
3. P1任何门禁失败都停留T3，依据实际报告修复；改源码后必须再次边界/生命周期/负例/W16及新完整CSim，
   才能换新tag再综合。禁止原样重跑r3或旧r1失败快照。
4. 仅当P1上述门禁全部通过才考虑P2；不自动进入T4。

固定W8A8/P2共享核/copy2/K7H4/单套权重投影核/原ob；n16 PS_EMBED_PLUS_FULL CLASS≤2.000000ms/patch。
外部差额0.310391ms仅假设，对应PL批周期≤5406748@200MHz。不转M3b/P3/第二ob/PS双缓冲/K14/H8/重训。
原XSA SHA256 9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652未变；原平台/App不动，
最终Vitis Build/下载由用户做。结束四件套并贴完整下一轮提示词，不设token预算、不push。

## 下一轮可复制提示词

```text
继续 D:/HSI_AgriEdge。先读CLAUDE.md、CODEX_CONTEXT.md最新快照、docs/m3_2ms_task_plan.md、
docs/m3_20261008_t3_worker_handoff.md和report/m3_worker_t3.md。
本轮仍只T3：上轮已真实拆出PROJECT worker/FIFO握手及原ob双读仲裁，保留copy2和消费者完成后释放ob。
r3曾因wmem被两个DATAFLOW进程读取而前综合失败，r4已改为engine唯一AXI读取并经原FIFO装载单套权重。
最终20261008_t3_fix_r4协议/极值/25主机及P1-P2-W16完整full+budget CSim全部通过且源哈希匹配。
新P1 G2 tag20261008_t3_fix_r4在2026-10-08 12:26:41启动，交接时仍运行：Python6764/shell29344/HLS37548。
先核对build/host/m3_s2_synth_20261008_t3_fix_r4的running.json、results.json、8p1_pack.log及实际进程，
不要重复启动；工程build/hls/optimization_build/m3_s2_syn_8p1_pack_20261008_t3_fix_r4。
尚无新P1最终资源/主II/实际端口结论，P2综合未启动。收取完整结果并审查主schedule_loop、project_loop、
原ob真实端口与单核共享。旧review工具假设内存在engine，新内存在core_service，不得以空匹配判PASS。
若失败仍在T3修复；改源码后重做针对性回归和匹配的新完整CSim，再新P1。P1全部门禁过后才考虑P2。
6138460只是当前P2 W8 n16 C迭代，不是RTL周期；不得用局部II1、命令成功或C迭代声称整网/2ms通过。
固定W8A8、P2共享核、copy2、K7/H4、单套权重投影核、原ob；n16、PS_EMBED_PLUS_FULL、CLASS≤2.000000ms/patch。
外部0.310391ms仅假设，对应PL批周期≤5406748@200MHz。不用DEPENDENCE false；不擅转M3b/P3/第二ob/
PS双缓冲/K14/H8/重训。原XSA、Vitis平台和App不动，最终Build/下载由我做。
不自动T4，不设token预算，不push；结束执行四件套并直接贴下一轮可复制的完整交接提示词。
```
