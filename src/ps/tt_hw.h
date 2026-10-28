#ifndef TT_HW_H
#define TT_HW_H
// PL 算子 tucker_proj（v1.4：片上 token 归一化 + 投影）的调用抽象。两份实现：
//   tt_hw_sim.cpp  逐位整数实现（算法 tt_ref_int.h，与 src/hls/tucker_proj.cpp 一致），用于 PC 测试或板上纯 PS 基线
//   tt_hw_xil.cpp  板上：写寄存器、启动、轮询完成，含 cache 维护
//   定义 TT_HW_RUNTIME_SWITCH：同时编译两者与 tt_hw_switch.cpp，通过 tt_hw_select() 切换。
// 接口：x 是未归一化的 Q3.12 块 [D*n_tok]；算子先做每 token 归一化再投影；stats 收 2*n_tok 个 int32
// （mean_q24[n], inv_q24[n] 交错，定义见 tt_ref_int.h），PS 残差用它复原归一化值。stats 缓冲至少 TT_STATS_CAP 个 int32、按 cache 行对齐、独占 cache 行。
// 启动与等待分开，PS 可以在 PL 计算期间处理另一个 patch（tt_forward_pair）。同一时刻只允许一个调用在飞。
// start 至 wait 之间，x/权重保持不变，输出与 stats 不得由 CPU 读写；双 patch 必须使用独立工作缓冲。
// 再次 start 会先等待前一次调用；无在飞调用时 wait 为空操作。接口供单线程调用。
// 板上驱动只 flush x、只 invalidate 输出和 stats：权重是常量；PL 模式下 CPU 只读输出缓冲（干净行）。
// 若有代码用 CPU 写 PL 输出缓冲（纯 PS 后端就是），切回 PL 前必须整体 flush（tt_hw_switch 已做）。
#include <stdint.h>

#define TT_STATS_CAP 32   // int32 个数：2*TT_NMAX = 20 → 128 字节，整数个 cache 行（32 或 64 字节）

// PL 直接读写的缓冲（x、out_*、stats）必须按 cache 行对齐、容量按 cache 行取整、不与其他数据共用尾行：
// 驱动对输出做 invalidate，共用行会丢掉别人的脏数据。A9 行 32 字节，A53 行 64 字节。
#if defined(__aarch64__)
#define TT_CACHE_LINE 64
#else
#define TT_CACHE_LINE 32
#endif

int  tt_hw_init();
void tt_hw_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj);
void tt_hw_proj_wait();
// 同步调用 = start + wait
void tt_hw_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj);

#endif
