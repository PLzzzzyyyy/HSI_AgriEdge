# 2026-10-09 P2推进范围评审与n16口径

2026-10-09后续明确授权及结果：仅一次独立8p2_pack诊断综合已完成，tag20261009_p2_pack_diag_r1，复用匹配20261008_load_order_r1完整CSim，无改源/重跑。工具1748.578s exit0，runner门禁exit1，II20/depth33、LUT165586/117120、FF215011、DSP362、BRAM18 235、URAM13、HLS5.858ns；G2仍FAIL，无后台。权重/投影/ob单套，但exponential辅助实例1→2；下一仅建议双槽统计写回/选择网络的定点候选评审，待确认，不自动修改/新构建。报告report/m3_p2_packed_diagnostic.md，交接docs/m3_20261009_p2_diag_handoff.md。下方“实验待确认/未启动”是前轮历史，已被本段更新；原验收门禁与禁扩范围不变。

起点`6134841`。本轮仅核后台、最终回执、现有源码和证据；未改HLS/门禁，未启动CSim/HLS/OOC/RTL。LOAD及完整P1 n1结果复用，不重跑。

## 为什么是n16

- **n16是批量16个patch，不是16套核、16个上下文或16位精度。** P2表示`S2_P=2`，两个在途上下文共享一套权重/投影核，完成后槽位可接收后续patch。`16p2_plain`中的16才是数值模式；最终主线仍W8A8。
- 沿用16首先是为了同口径比较已有真板基线。`board/m3/20261007_acceptance/uart_user.txt:162`为旧串行`PS_EMBED_PLUS_FULL / CLASS / n=16 / runs=10`：平均批耗时58.018903ms，3.626181ms/patch，275.772patch/s；汇总见`report/perf_m3.md`。这不是新P2结果。
- 批处理有助于摊销启动/收尾开销并观察流水吞吐，但**没有证据证明16最优或已达到稳态**。源码允许count不超过64，P1/P2均支持批处理；P2不要求批量等于2、16或2的幂。当前不擅改已固定的主比较口径。
- 主指标为`(本批最后结果可读时间 − 本批首次PS准备时间) / 16`，包含窗口内PS准备/embed、接口和PL处理；不隐藏准备时间。它不是单patch响应延迟，也不是“n1耗时/16”。单路n1延迟与批均摊分列；已有DUMP诊断只保留自己的口径。
- 若均摊为2ms/patch，对应16个patch约32ms的批窗口，而非每个patch从到达到可读只等2ms。这是目标关系，不是实测。LOAD单列，若未来测量窗口包含LOAD须计入并说明。
- 2ms只是优化目标，无自定容差。**不要求n1先达到2ms才推进P2**；不将15322409个n1 DUMP周期除以16、除以2或减去部分写出等待，冒充n16/CLASS结果。

## 已核实证据与剩余阻塞

| 依据 | 支持的结论与限制 |
|---|---|
| 新P1 `20261008_load_order_r1`：II22/depth34，HLS LUT139501 > 117120 | 综合完成但G2前筛仍FAIL；II不是每patch周期，HLS资源估计不是实际占用 |
| 最终n1 `20261009_load_order_n1_r3`：simulate/results/running与日志尾一致，exit0/no timeout | 12层/logits/class/全guard、两次return0/四FIFO空/AXI排空PASS；DUMP15322409周期，不是P2/CLASS-only/n16/板上性能 |
| 旧r9 post-route：WNS−0.488ns、CLB98.14%、LUT79.20% | 真实setup与布局拥塞风险；不能只看剩余LUT。本轮无新OOC，不能冒充新LOAD候选/P2测量，也不能直接断言P2必定放不下 |
| `s2_internal.h`：x/xn/q/kv的Bank含`S2_P*662`；CoreMemory的xb/ob/权重不随P扩展 | P2增加上下文存储/状态，不是复制完整核；综合后仍须核单核/无隐藏复制，资源不能简单按P1乘2 |
| 新P1日志2788—2800及旧r9详细报告 | jobs_active_0/7反馈、ctx_sum写端口、slots_attn_0读端口仍受限；旧NORMAL乘inv布线路径为时序线索，不是全部II22根因证明 |

P2能让不同patch的独立阶段交错，但不能让两个投影同时使用单核，不能绕过全局调度反馈、共享端口或原ob所有权。保持投影完成不等于消费完成，消费完成及真实RELEASE握手后才允许复用ob。盲目进一步分割数组不保证吞吐/资源双赢。

## 最小下一步：建议待确认，不在本轮启动

**建议下一短轮只做一次独立P2 packed诊断综合**，获得真实P2调度/资源/结构反馈，避免无P2数据时盲开r10或追单路2ms。

1. 须用户明确允许“P1 G2仍FAIL时单独诊断P2”的顺序例外。最终P2方向已确定，不等于这次实验已获准；原r9诊断授权也不自动延伸为新P2/OOC/系统全跑。保留门禁代码和FAIL事实。
2. 复用`20261008_load_order_r1`的`8p2_pack`完整CSim及SHA匹配源码快照。启动前只核回执/SHA/占用，匹配则不重复CSim/P1/n1；不匹配则停止说明差异，不偷偷改源或补跑。
3. 只用`--only 8p2_pack`和独立新tag；保持W8A8/copy2/K7H4、单权重/投影核、原ob及消费者完成才RELEASE，不改HLS、阈值、接口或原XSA/平台/App。
4. **实验出口**：工具完成/失败/超时回执及进程退出；主schedule_loop II/depth/反馈与端口告警；LUT/FF/DSP/BRAM/URAM及容量；投影/权重实例数与上下文存储映射；保存原日志/SHA。诊断完成不等于G2 PASS，更不等于2ms。
5. 得到结果即停；若资源/调度仍阻塞，据P2实证提出下一处最小修改或是否值得独立OOC的建议，另行确认。**不自动r10/OOC/P2 RTL/n16/T4/T5。**

授权后可复用入口（仅列出，未执行；新tag须确认未存在）：

```powershell
D:/pytorch/python.exe tools/run_m3_s2_synth.py --tag <独立新tag> --csim-tag 20261008_load_order_r1 --only 8p2_pack --timeout 2700
```

runner已支持单独P2，并会在自身前筛失败后exit1/停止；无需删门禁。默认P1/P2串行配置会在P1失败处停下，不应无修改重复默认命令。

## 后续验证出口（不是本轮启动清单）

- P2正确性：匹配完整黄金、双槽不同输入/奇数批尾部、KV/xb/ob生命周期、真实背压、输出顺序、全guard及FIFO/AXI排空；P1 n1不重跑，但不能替代新的P2验证。
- 性能：获准并建立匹配P2 RTL后才测n16 CLASS原始批总周期、fill/drain和逐patch完成间隔；批均摊与n1延迟分列。PS端到端实测与RTL/BFM分列，旧外部0.310391ms只是假设，不能拼为新实测。
- 实现：实际资源/单核/无隐藏复制、最终完整系统200MHz setup/hold/DRC仍须核验。OOC仅辅助，不擅设HLS超额容忍比例；2ms非硬门槛不等于正确性/时序可放宽。
- 不扩M3b/P3/第二ob/PS双缓冲/K14H8/重训。原XSA/平台/App不动，最终用户Build/下载。

## 只读复核与恢复入口

- 本轮核验摘要`report/m3_p2_review/20261009/receipts.json`：仅进程、最终回执/日志SHA及CSim源码匹配，不替代原RTL证明。
- 原回执：`build/host/m3_s2_rtl_20261009_load_order_n1_r3/{simulate,results,running}.json`及`simulate.log`尾；监督目录`build/host/m3_s2_supervisor_20261009_load_order_n1_r3/`。核进程须匹配命令，不只看旧PID。
- 冻结证据仍为`report/m3_rtl/20261008_load_order/`（7份运行归档）、`report/m3_worker_r9_g2.md`、`report/m3_r9_p1_route.md`；本轮不修改旧归档，不重跑capture中的既有测试。
- 恢复CLAUDE.md → CODEX_CONTEXT.md顶部 → 本文及`docs/m3_2ms_task_plan.md`。停在建议待确认的出口，不自动执行综合命令。提交定位`git log -1 -- docs/m3_20261009_p2_scope_review.md`。
