# 2026-10-08 r9 P1核OOC布局布线后交接

本轮短任务T3-D1已完成，无后台。提交定位`git log -1 -- report/m3_r9_p1_route.md`；此前r9实现/完整CSim/HLS/OOC证据2e81a26，授权交接6cedf4d。以下可复制：

```text
继续 D:\HSI_AgriEdge，按短任务执行。先读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/m3_2ms_task_plan.md、report/m3_r9_p1_route.md及本交接；按需读取双方memory/相关pitfalls。详细r9技术继承docs/m3_20261008_t3_r9_handoff.md和docs/m3_20261008_r9_diagnostics_handoff.md，但其中旧“建议未批准/尚未启动P&R”已失效。

用户已批准受控诊断/验证顺序调整；最终应主动采用P2共享核双上下文流水，以n16/PS_EMBED_PLUS_FULL/CLASS批均摊每像素耗时争取2ms，不要求先单路n1做到2ms。2ms只是优化目标、没有数值容差，不拿C迭代或n1外推n16，不把流水均摊冒充单点响应。资源/时序/正确性仍要真实合法。

当前无相关构建后台；先核实际进程和最终回执，不盲目重跑。r9完整CSim、HLS、独立OOC综合，以及本轮P1核OOC P&R均已结束。新RTL小批诊断/IP导出/集成系统/P2综合尚未启动。
本轮tag20261008_r9_p1_route_r1复用原DCP、同Vivado2020.2/xazu5ev-sfvc784-1-i/5ns；1560.750秒exit0，175447条可布线网络全完成、路由错误0、黑盒0。LUT92762/79.20%、FF97270、DSP418、BRAM101.5Tile、URAM13；CLB14368/14640=98.14%、拥塞level5。不能凭LUT剩余比例认定P2/系统余量足够，也不先判P2一定不可行。
最终WNS−0.488/TNS−18.119，154 setup失败；WHS+0.019/THS0仅OOC模型。最差NORMAL源码119–120的33×32 LUT乘法，数据5.468ns中布线3.845ns/70.318%；不是全部II22根因。缺HD.CLK_SRC及200输入/314输出延迟，DRC187警告+4提示、methodology535警告。P1核OOC≠P1集成诊断系统≠最终P2完整系统，不宣称200MHz/2ms或G3/G4通过。
现有G2前筛FAIL不变：主II22/depth34，HLS LUT141958>117120；投影II1不能冒充主II。保留自动前筛，不因FAIL阻止已批准的诊断，也不改门槛装作PASS。

下一短轮只做已授权的P1完整12层小批RTL诊断：优先独立复用匹配源码/RTL/综合数据库，先n1核数值、事务、真实背压、排空和原始周期，界定成本后再决定n16；不能用原TB smoke的一层冒充完整12层，也不要无边界直接跑full/budget全部调用。确需重生成须说明理由并保留原证据；改HLS源就必须新针对性回归/完整CSim/新tag P1。保留r9，不自动开r10追II1，不自动P2/完整T4/T5。

保持W8A8、最终P2共享核/copy2、K7/H4、单套权重投影核、原ob、消费者完成才RELEASE及r7/r8/r9修订；不扩M3b/P3/第二ob/PS双缓冲/K14/H8/重训，不恢复旧overlap_v2。P1只是诊断前置，不是最终串行终点。
原旧系统CTRL/FM/WT不适配r9 control/wmem/inmem/outmem；如后续做系统必须在新目录真实集成PS/AXI/时钟复位/约束，不覆盖旧工程、不原样跑旧系统充数。

本轮证据report/m3_impl/20261008_r9_p1_route/含失败/最终zip、manifest、summary、capture.py。capture.py只复核归档、不启动综合，须匹配build树。原DCP SHA fe8591606a8c7858ca9414b97f94fb5b4f01399b22f90e14b95f6b638ef1419a；最终DCP在build/host/m3_s2_impl_20261008_r9_p1_route_r1/s2_engine_routed.dcp，99959836字节、SHA8043a2b25e54d06f6a0040b2067fa697b091618e0869099a5bbaf40e10330ed0。首轮current_design句柄误判top的42.547秒失败已保留，runner已改用dcp.xml身份验证，11门禁测试PASS。
原XSA SHA9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652不变；旧XSA、Vitis平台/App不动，最终Build/下载由用户做。不默认生成/替换bit/XSA，不自动上板，不设token预算、不push。

新任务必须等待结束、核对进程退出/最终回执/报告后再常规收尾，不带运行综合交接。执行提交/进度/踩坑/记忆四件套，同步双方可访问memory及MEMORY.md，落实llm_log/evidence/复现入口；保留无关未跟踪工作，不改独占skill。最后简短汇报并贴可复制交接提示词，不自动串行跑完整目标。
```
