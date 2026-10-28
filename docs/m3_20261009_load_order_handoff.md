# 2026-10-09 LOAD最小修复与完整P1 n1诊断收尾

起点4534b70。本轮已按用户授权完成LOAD最小三阶段修复、针对性回归、新完整CSim、新P1和完整n1诊断；无相关后台。提交定位`git log -1 -- report/m3_load_order_fix.md`。

```text
继续 D:\HSI_AgriEdge，按短任务执行。先读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/m3_2ms_task_plan.md、report/m3_load_order_fix.md及本交接。先核后台和最终回执，不重复启动已经完成的CSim/HLS/n1。

用户已授权的LOAD最小修复完成：仅s2_engine.cpp LOAD块改为真实发送权重→CORE_LOAD请求握手→读取ACK三阶段，phase循环PIPELINE off，write_nb/read_nb成功才推进。不预灌响应/force/假依赖，不扩架构。

主机33项、worker24项、新四套full+budget CSim PASS；新P1 tag20261008_load_order_r1综合1053.343s完成，II22/depth34，LUT139501/FF183460/DSP358/BRAM18=229/URAM13。G2仍FAIL，前筛规则未改。本轮没有新OOC；原r9 OOC LUT79.20%/CLB98.14%、5ns WNS−0.488ns的FAIL保留，不能当新候选实测。

最终n1 tag20261009_load_order_n1_r3正常结束：编译73.204s、仿真19915.094s（工具墙钟）。LOAD真实请求→ACK→STOP、cq22994/cr1收发匹配，事务3679261周期；完整12层n1 DUMP为15322409个ap_start→ap_done周期。12层各63504字节、logits128字节、class4字节、全766176字节输出内存及guard均逐字节PASS；两次return0、四FIFO空、AXI排空PASS。meta[1]=599482是循环计数，不是RTL周期。

这仅是P1单样本A的DUMP/确定性背压诊断，不是CLASS-only/n16/P2/系统/G3全套或板上性能。不要外推n16，也不要先追单路n1 2ms。最终仍主动P2共享核双上下文，n16/PS_EMBED_PLUS_FULL/CLASS均摊争取2ms；2ms仅优化目标，无自定容差。

保留失败：r1诊断台网名错误8.234s编译失败；r2通过LOAD并进入n1，但恢复时进程全无/主机已重启，日志止9800000/out32598，无最终回执。recovery.json只记录未知终止原因的未完成审计，不伪造exit/timeout。旧r9的275755及r2的9800000都不是推理时延。

证据report/m3_rtl/20261008_load_order/：7份zip、manifest/summary、cycle_review/load_order_review、监督/进程检查、capture.py。capture只核SHA/归档/Python门禁，不启动硬件工具；31条Python测试不是RTL证明的替代。完整仿真入口tools/run_m3_s2_rtl_diag.py --tag <新tag> --synth-tag <匹配P1tag> --timeout 43200，已有结果不重跑。

下一短轮先结合本次实际结果与G2/OOC阻塞评审P2共享核双上下文推进的具体范围；不自动r10/P2综合/n16/T4/T5全跑。保留W8A8/copy2/K7H4/单权重投影核/原ob及消费者完成才RELEASE，不扩M3b/P3/第二ob/PS双缓冲/K14H8/重训。

原XSA SHA9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652复核不变，原平台/App未改，最终用户Build/下载。仅本任务路径本地提交、不push，原未跟踪工作保留。结束前核后台/最终回执，再四件套；同步双方可访问memory及MEMORY索引、llm_log/evidence/复现入口，不改独占skill。
```
