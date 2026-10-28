#ifndef TT_TYPES_H
#define TT_TYPES_H
// 与 model/quant.py 的 Fmt(DF=12, WF=14, MF=14) 一一对应。改这里必须同步改那边并重跑 fixed_point_sim.py。
#include <ap_fixed.h>
#include <ap_int.h>

#define TT_W    7        // 空间窗边长 I1 = I2
#define TT_J    54       // 光谱长度
#define TT_R    (TT_W * TT_J)          // 378：固定 i1 后剩余的 (i2, j) 元素数
#define TT_D    (TT_W * TT_W * TT_J)   // 2646：一个 token 的元素数
#define TT_NMAX 10       // 最多 token 数（重叠模型 9+1）
#define TT_NF   (2 * TT_W * TT_W + TT_J * TT_J)   // 3014：一个投影的因子元素数

#define TT_DF 12
#define TT_WF 14
#define TT_MF 14

typedef ap_fixed<16, 16 - TT_DF, AP_RND, AP_SAT> data_t;   // Q3.12  DDR 激活
typedef ap_fixed<16, 16 - TT_WF, AP_RND, AP_SAT> wt_t;     // Q1.14  因子矩阵
typedef ap_fixed<18, 18 - TT_MF, AP_RND, AP_SAT> mid_t;    // Q3.14  模 1/模 2 之后的片上中间量
typedef ap_fixed<48, 20>                          acc_t;   // 累加器：不舍入、不饱和

#ifdef TT_FM64
typedef ap_uint<64> fm_t;     // 4 个 Q3.12 int16 原始位，低地址在 15:0
#else
typedef data_t fm_t;
#endif
#ifdef TT_WT32
typedef ap_uint<32> wt_bus_t; // 2 个 Q1.14 int16 原始位，低地址在 15:0
#else
typedef wt_t wt_bus_t;
#endif

#ifdef TT_NORM_IN
// v1.4：in 是未归一化的 Q3.12 块，IP 先做每 token 归一化再投影；stats 每 token 一个 64 位字 {inv_q24[63:32], mean_q24[31:0]}
#ifndef TT_FM64
#error "TT_NORM_IN requires TT_FM64"
#endif
void tucker_proj(fm_t *in, fm_t *out_q, fm_t *out_k, fm_t *out_v, fm_t *stats,
                 wt_bus_t *w_q, wt_bus_t *w_k, wt_bus_t *w_v,
                 unsigned short n_tok, unsigned short n_proj);
#else
void tucker_proj(fm_t *in, fm_t *out_q, fm_t *out_k, fm_t *out_v,
                 wt_bus_t *w_q, wt_bus_t *w_k, wt_bus_t *w_v,
                 unsigned short n_tok, unsigned short n_proj);
#endif

#endif
