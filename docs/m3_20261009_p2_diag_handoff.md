# 2026-10-09 P2 packed单次诊断收尾与下一短轮

本轮起点d35bb75；已完成一次明确授权的独立P2 packed诊断，后台全部退出。本轮提交定位：

```powershell
git log -1 -- report/m3_p2_packed_diagnostic.md
```

## 恢复顺序

1. CLAUDE.md；CODEX_CONTEXT.md顶部。
2. report/m3_p2_packed_diagnostic.md；docs/m3_2ms_task_plan.md。
3. 只核当前相关后台与 `report/m3_p2_synth/20261009_p2_pack_diag_r1/{runner_final,final_audit,summary}.json`，不要重复启动已完成任务。

## 本轮出口

- tag20261009_p2_pack_diag_r1，只跑8p2_pack。完整复用20261008_load_order_r1的CSim冻结源码；未改HLS/门禁/接口，未重跑CSim/P1/n1。
- HLS2020.2工具1748.578s正常exit0/no timeout；runner按原门禁exit1。主II20/depth33，LUT165586/117120、FF215011/234240、DSP362、BRAM18 235、URAM13；HLS5.858ns。G2仍FAIL，非实际占用/时序/2ms通过。
- 对照P1 II22/depth34、LUT139501、FF183460、4.769ns：II略降而资源/时钟恶化；资源增量集中engine_task，mux LUT+22779。active0/7、ctx_sum写/attn读端口仍限；CONTEXT饱和→平方为本次HLS关键路径。
- 生成层级权重/投影核及原ob/xb各单套，四类上下文存储各24bank深度662→1324；**exponential辅助模块1→2**，真实辅助复制不能省略。它仅解释+461LUT/+520FF/+4DSP/+2BRAM18，不是主要LUT增量。
- 三份zip共419归档文件，manifest/summary/verify可离线核；13 sidecar SHA完整性PASS。原XSA和旧回执SHA不变，无后台；完整数据库留build，不删除。
- 没有新OOC/P2 RTL/n16/T4/T5；旧r9 WNS−0.488/CLB98.14% FAIL保留，P1 n1 DUMP15322409周期不外推CLASS/批吞吐。

## 下一步仅建议，尚未授权实施

优先定点审 `slot_sum/slot_square` 双槽统计读改写/提交选择网络，给一个最小候选及验证出口；当前证据不足以承诺哪处修改能使资源/II/时钟全部达标。不要同时混入exp共享、CONTEXT全分割或广泛改位宽；exp副本可独立审，但收益不足以作为整体面积解决方案。

若用户授权实施，验证范围须先明确：旧新统计写回/清零/交错完成等价及边界→匹配完整CSim→一次独立新P2综合及结构/资源/调度比较；新P1或P2 RTL按风险另获明确授权。失败保留，不自动重试或串联OOC/n16。最终P2动态功能、同口径性能和系统实现仍未完成。

## 下一短轮提示词

```text
继续 D:\HSI_AgriEdge，先核当前提交及后台，不重跑已完成的CSim/P1/n1/P2诊断。
先读CLAUDE.md、CODEX_CONTEXT.md顶部、report/m3_p2_packed_diagnostic.md和本交接。
本轮只做定点方案评审，不改源、不启动硬件工具：沿已归档P2绑定/调度及资源报告，定位slot_sum/slot_square双槽统计读改写/提交选择网络的主要成本，提出一个最小重构候选。
出口：确切源码/RTL证据、哪些成本已归因/仍未确定、唯一候选修改路径与等价条件、针对性验证范围；不足以证明则明确说明。等我确认后才修改或验证。
保留G2 FAIL及P2 II20/LUT165586/HLS5.858ns事实，明确exponential辅助实例1→2，不把单投影核等同于全局无复制。
保持W8A8/copy2/K7H4、P2共享单权重/投影核、原ob和消费者完成才RELEASE；不扩架构，不自动r10/OOC/P2 RTL/n16/T4/T5。
最终n16/PS_EMBED_PLUS_FULL/CLASS均摊争取2ms，无自定容差，不要求n1先2ms、不除2/16外推。原XSA/平台/App不动，最终用户Build/下载。
结果出来即停，按授权四件套收尾，仅提交本任务，不push，给下一短轮建议。
```

## 仅只读复核

```powershell
D:/pytorch/python.exe report/m3_p2_synth/20261009_p2_pack_diag_r1/verify.py
D:/pytorch/python.exe report/m3_p2_synth/20261009_p2_pack_diag_r1/audit.py
```

本轮tag已使用；capture拒绝覆盖冻结证据，复核不要重新综合。新增辅助实例复制坑，进度/llm_log/evidence/复现及双边memory/索引同步；无新依赖/许可/独立技能，不改skill目录。原无关工作保留，不push。
