# 2026-10-08 r9 P1 n1 RTL诊断后交接

本轮T3-D2停在已复现的LOAD自锁；未进入12层n1。所有相关后台已结束。提交定位`git log -1 -- report/m3_r9_p1_rtl_n1.md`。以下可复制：

```text
继续 D:\HSI_AgriEdge，按短任务执行。先读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/m3_2ms_task_plan.md、report/m3_r9_p1_rtl_n1.md及本交接；之前OOC报告report/m3_r9_p1_route.md的失败结论仍有效。先核进程和回执，不盲目重跑。

最新：r9原P1 RTL复用诊断已结束，无后台。最终20261008_r9_n1_direct_r4编译67.719s、仿真245.796s，LOAD在cycle275755因50000周期无事务进展自动Fatal；壳exit0不等于PASS。最后进展225755、权重读23987、cq/cr收发全0。load_done=1/load_return=1，engine state5被空cr阻塞，权重发送未启动，worker state2等请求。生成RTL state5先要求cr响应才能去state6/7发送权重，state8才发LOAD请求，已动态+静态闭环定位响应先于请求自锁。未修源，未重综合。

完整12层n1根本尚未开始：没有逐层数值、完整背压/排空或n1完成周期PASS；275755只是失败观察截点，不是推理时延，不外推n16。暂不跑n16。原G2 FAIL和OOC LUT79.20%/CLB98.14%、5ns WNS−0.488ns保留，不能当系统/P2或G3/G4通过。

下一短轮先确认仅修LOAD请求/响应排序的授权和最小方案，不自动开r10、改源或新综合。若用户明确授权改HLS，保持W8A8/P2共享核copy2/K7H4/单权重投影核/原ob及消费者完成才RELEASE，做真实请求→ACK阶段，不预灌响应/force/假依赖；须针对性回归+新完整CSim+新tag P1，再重做完整n1诊断。不得把旧RTL复用当成修改后的验证。

最终仍主动采用P2共享核双上下文流水，以n16/PS_EMBED_PLUS_FULL/CLASS均摊每像素争取2ms，不要求先单路n1到2ms；2ms仅优化目标、无擅设容差。不扩M3b/P3/第二ob/PS双缓冲/K14H8/重训，不自动T4/T5全跑。

当前诊断有效入口tools/run_m3_s2_rtl_diag.py，新tag；只复用原RTL/五个FP模型，不综合。旧tools/run_m3_s2_rtl_n1.py是失败cosim尝试，depth指令不更新旧数据库，别原样再跑。源码与初始化文件按SHA核验，readmemh数据须在仿真CWD。report/m3_rtl/20261008_r9_n1/有8次记录/manifest/summary/load_order_review.json/capture.py；capture只核证据不启动硬件工具。两次人工中断已获许可并保留记录，最终看门狗正常结束。

原XSA SHA9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652不变，原平台/App不动，最终用户Build/下载。不自动生成替换bit/XSA或上板。新任务等待结束并核进程/最终回执后再四件套；同步双方可访问memory与MEMORY索引、llm_log/evidence/复现入口，保留无关工作，不push、不设token预算、不改独占skill。
```
