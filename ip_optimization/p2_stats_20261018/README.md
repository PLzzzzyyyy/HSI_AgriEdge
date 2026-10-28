# P2 统计写回重构候选（进行中）

依据 `docs/m3_20261009_p2_diag_handoff.md`、`docs/m3_2ms_task_plan.md`，继续用户授权的约两倍吞吐优化。现用 AXU5EV-E 硬件不变；7020 项目历史中的 M3 后续方案针对 ZU5EV，此目录单独验证其 P2 共享投影核心候选。

## 变更

仅重构 CONTEXT、RESIDUAL、IO_LOAD 对 `slot_sum/slot_square` 的更新：各生产者输出增量，由完全展开、常量槽索引的统一提交循环完成写回和清零。保留 64 位累计、原有依赖、单份权重与投影核心、W8A8、P=2、K=7、H=4 和 LOAD 握手。没有重训、改精度或复制整核。

旧源位于 `D:/FPGA.GAME/HSI_AgriEdge(1)/HSI_AgriEdge`，只读；`baseline_manifest.json` 记录其哈希。新综合输入哈希在 `hls_input_hashes.json`。

## 已完成

- g++ 本地完整回归：12 层逐层黄金结果、交错 A/B/A、反压、分层续算、超时后复用，PASS。
- 本地 budget 回归：CLASS-only n=1/3/16、混合输入、尾部写保护、超时排空，PASS。
- 本地 stress 回归：32 个不同汉川输入及对应权重，全部 logits 和类别黄金比较、尾部保护，PASS。
- W8 P1、W16 P2 完整黄金回归 PASS。
- 用相同 g++ 选项编译原代码，full/budget/stress 的完整标准输出与新代码逐字节一致（含所有生命周期计数、交错等待和逻辑迭代计数）。这证明被测 C 行为没有变化，不代表 RTL 调度相同。
- 日志：项目 `.runtime-tmp/p2_stats_native_full.log` 和 `p2_stats_native_budget.log`。日志中的迭代数不是硬件周期，不能据此宣称加速。

## 当前工具运行

2026.1 不包含旧工程 `xazu5ev-sfvc784-1-i` 器件，首次运行在 set_part 失败，证据保留在 `hls_2026` 和 `.runtime-tmp/p2_stats_hls_2026.log`。

按本机文档 `tools/vivado/README.md` 改用实际板卡 `xczu5ev-sfvc784-2-i`，5 ns、uncertainty 1.35 ns，脚本 `run_hls_xc.tcl`，输出 `hls_2026_xc`，日志 `.runtime-tmp/p2_stats_hls_2026_xc.log`。**该次 HLS CSim 和综合不能作为本候选证据**，具体原因见下节。手工 g++ 指定候选绝对源文件的 native 回归仍有效。

## 验收仍需完成

HLS 完整 C 仿真、资源与主循环调度检查、匹配条件下的比较、RTL 动态功能验证、独立实现与系统时序检查、真实 n16 同口径吞吐实测。旧 P2 有资源和时序失败记录，不能直接拿来烧录。

只有数值、资源、时序和真板吞吐全部满足后，才能替换部署并宣称约两倍加速；当前没有这种结论。

## 2026.1 综合绑定错误（已撤回候选结论）

工具虽然正常结束，但 `hls.app` 把绝对输入路径改为 `src/hls/...`，实际 CSim makefile 使用 `../../../../../../src/hls/...`，解析到了原项目根目录。预处理文件里不存在 `StatsDelta`。因此本目录的 HLS 数值和功能结果都是旧代码的，不能归因于统计写回候选。

旧代码基线：II9、估计18.407ns、LUT155428/117120、FF164050、DSP417、BRAM18K217、URAM13。主循环模块 LUT85217，其中 mux38619、表达式37268；engine_task LUT96047，core_service LUT52300。警告包含 IO_LOAD 连续索引/存储选择及跨生产者 core.valid 控制链。基线实际源的11个文件哈希均与记录的原代码匹配，基线数据有效。后续候选不以此冒充改善结果。

原始错误证据和 `hls_binding_audit.json` 均保留。后续在候选目录设置工作目录并显式 `cd $ROOT`；CSim 后核验实际 makefile 解析路径，综合后再次核验预处理内容和冻结哈希，核验失败即停止。最新候选 `../p2_xwrite_20261018`；结果用 `../collect_hls_results.py` 汇总，未核验的报告不列为有效完成。
