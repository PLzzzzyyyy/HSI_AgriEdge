# 请求仲裁前移候选（待 HLS）

父候选 `../p2_stats_io_20261018`，包含统计单写回和固定通道输入解包。

2026.1 旧代码基线报告主调度 II=9、估计时钟周期18.407ns，LUT155428/117120；不能直接交付。此前统计候选的 HLS 路径绑定错误，实际也编译了旧代码，该候选的 HLS 结论已撤回。基线关键路径经过多个共享 `core.valid` 决策。本候选在每轮入口按原来 NORMAL→PROJECT→COPY→RESIDUAL 优先级选择唯一请求者，各生产者使用独立 ready/valid；最后仍只有一个 FIFO writer、一个投影核和一套权重。阻塞、响应和清零顺序不变。

本地完整黄金、n1/n3/n16 CLASS-only、32 个不同输入、反复 LOAD、错误排空/超时恢复均 PASS。full/budget/stress 的完整输出与原代码逐字节一致。

补充 10 个反压种子（含 0x7fffffff/0x80000000/0xffffffff），在 W8 P2、W8 P1、W16 P2 上逐位比较交错 A/B/A 的 12 层最终 logits、类别和写保护，PASS。真实 IO worker 的 W16 边界测试也 PASS。

日志位于项目 `.runtime-tmp/p2_arbiter_native_*.log`、`p2_arbiter_verify0.log`、`p2_arbiter_verify1.log`、`p2_arbiter_verify2.log`。当前尚无该候选 HLS/RTL/实现/上板吞吐结果，不代表已加速。

HLS 入口 `run_hls_xc.tcl`，仅写本目录的新 `hls_2026_xc`；先 ap_int 完整 CSim 再综合，器件 XCZU5EV-2、5ns、uncertainty1.35ns。等同条件基线综合结束后启动。已部署 DP 应用和 FPGA 硬件保持原版本。
