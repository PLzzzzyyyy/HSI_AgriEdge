# 显式 X 存储写口候选

父候选 `../p2_arbiter_20261018`。由2026.1旧代码基线的具体HLS警告继续收敛：CONTEXT/RESIDUAL/IO_LOAD在同一X bank的多处条件写入，被综合成串行选择链；路径从CONTEXT数据和分支延伸到IO_LOAD控制。此前统计候选误绑定旧源的综合已撤回候选归因。

此版本保留原 X RAM、容量、分 bank、双端口、调度端口预算和单份权重/投影核。三个生产者只发布地址/数值/写使能，统一在每个已有 bank 上选择最多两个实际写入，不增加第二份 X 或 ob。没有加入 `DEPENDENCE inter false` 等忽略真实数据依赖的指令。

安全条件：原 dispatcher 保证每 bank 最多两个访问；同一上下文的 CONTEXT、RESIDUAL、IO_LOAD 生命周期互斥。并行写者来自不同上下文，地址不同。CPU 回归逐轮断言写者数量、地址范围和双写地址不同。NORM/HEAD/IO_DUMP 不会与同一上下文的这些写阶段并行；跨上下文地址不同，因此把写入汇总到本轮末尾保持被测 C 行为。

验证使用实际 IO worker 和实际 `commit_xwrites`：W8/W16 各 2,520 组加载边界、168 组双写选择组合 PASS，比较整个 X Bank 的预期内容，检查无额外写入。完整黄金、CLASS-only n1/n3/n16、32 个不同输入、10 个反压种子、LOAD 和 timeout drain PASS；W8 P1、W16 P2 的完整及多种子交错任务 PASS。

证据：项目 `.runtime-tmp/p2_xwrite_verify*.log`。原始统计候选和同条件基线均独立保留，未替换已部署硬件。此版本尚需 RTL、实际资源/时序和真实同口径吞吐验证；不得宣称“两倍加速”。

最终源码回归由 `run_native_regressions.py` 重跑并记录 `native_verification.json`，日志 `p2_xwrite_final*.log`。实际候选 ap_int 完整 CSim PASS（1分49秒），CSim及synthesis绑定审计都PASS。完整综合II5、估计12.292ns、LUT149067、FF118724、DSP417、BRAM18K217、URAM13；仍失败，不部署。后续只针对关键CONTEXT乘法的新候选位于 `../p2_ctxpipe_20261018`。

必须在本目录启动工具，并设置 `S2_AUDIT_PY` 为主项目 `.venv/Scripts/python.exe`，让流程在 CSim 和综合后自动核验实际源码；旧统计目录的误绑定综合已撤回归因。

复现 HLS：在项目根目录设置 `S2_ROOT=D:/FPGA.GAME/HSI_AgriEdge(1)/HSI_AgriEdge`（只读黄金数据），调用 `D:/AMDDesignTools/2026.1/Vitis/bin/vitis-run.bat --mode hls --tcl ip_optimization/p2_xwrite_20261018/run_hls_xc.tcl`。只允许写新目录 `hls_2026_xc`；既有输出不会重置。
