# M3a INT8/P2 下一对话执行提示词

以下提示词供用户复制到新对话后作为该轮任务范围；本文件落盘不代表本轮已经执行S1。

```text
继续 D:\HSI_AgriEdge。S0成果提交099dee8；先用git log/status核对当前HEAD，保留用户及其他会话改动。

先读取CLAUDE.md、CODEX_CONTEXT.md、.claude/progress.md最新相关条目、相关踩坑及双方项目记忆；再读取：
- report/m3_stage_budget.md
- report/m3_s0/inputs.json（summary.json只按需查看相关情景）
- docs/m3_next_round_plan.md
- report/perf_m3.md
并按需核对docs/engine_arch.md、model/engine_ref.py、INT8精度报告和既有黄金向量。

下一版方向已确定：保留M3a分工（PS前端/embed，PL十二层和分类头），做W8A8＋P2共享核分阶段流水＋copy2。首版保持K7/H4，不做M3b，不优先做P3、第二ob、PS双缓冲或K14/H8整网加宽。INT8打包先验证可行性，不预设自动提速两倍。

本轮从S1开始实际写代码和测试，不重做S0、不只给计划：
1. 先核对既有INT8整数契约、QAT权重、量化/舍入/饱和/矩阵指数和入口黄金。外部int16容器不代表仍用INT16数值格式；不重训，不要求与INT16 logits逐位相同。
2. 新增独立候选小核，验证INT8双乘的符号修正、解包、54项累加、极值与随机输入及实际DSP映射。打包失败不等于INT8容量路线必然失败，分别报告。
3. 验证跨上下文深度打包、copy2地址/双口供给和有限buffer所有权。保留单套权重/投影核；重点覆盖K/V别名、ob持有到消费结束、跨层回流、背压、输入串扰与输出顺序。不得直接删ob，把同bank四写冲突藏起来。
4. 调度/候选接口保持位宽和P可配置，同一结构用P1对照、P2验证；不先写一套不可复用架构再重写INT8。S0约28.5%成本未可靠归因，尽量用已有材料定位，否则明确保留未知。

允许新增独立候选源码、脚本、主机测试，以及必要的独立小核/存储适配器HLS 2020.2 CSim、综合和RTL cosim。先检查任务占用，独立命名/目录，保存参数、源快照、日志及完成回执。不得直接启动整网优化综合、整网RTL或Vivado系统实现；不得替换XSA、重建用户平台或修改用户App。S1完成后报告G1通过/失败及下一步S2方案，等我确认再集成整网。

冻结边界：
- 原串行M3a数值、12层DUMP、续算和批处理全部PASS；单patch含PS embed LOGITS3.628719ms，n16含embed CLASS3.626181ms/patch、275.772patch/s。
- 完整UART/用户Build日志已归档，不再索要或要求重测。
- build/vivado/tt_m3a_zu5ev.xsa及用户m3a_plat/test_m3a保持不变；原串行实现默认行为不变。TT_M3_OVERLAP默认0，已停止overlap_v2不恢复。
- M1/M2/C3已过项不重测，SYSMON暂缓。模型估计、HLS/RTL和真板结果分开，不将单项加速倍数相乘。
- 用户负责后续胜者的Vitis Build/下载。按项目约定保存协作日志/证据/复现入口、进度和双方memory索引；只提交本轮明确路径，不push。

先给简短执行顺序，然后开始S1最小算术/存储测试。遇到数值契约或资源门槛失败，应说明并提出回退，不擅自改变精度门槛或开启整网构建。
```
