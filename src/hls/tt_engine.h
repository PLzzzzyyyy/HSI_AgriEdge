#ifndef TT_ENGINE_H
#define TT_ENGINE_H
// tt_engine 的 HLS 侧声明与编译参数。契约（参数语义、DDR 布局、模式位、错误码）在 tt_engine_regs.h，架构在 docs/engine_arch.md。
// 编译配置（docs/engine_arch.md §4.7）：
//   TT_DB       片上激活位宽：16 = M2 编译（PROJ 模式，Q3.12，与 v1.4 逐位相同，FULL 返回 ERR_MODE）；
//               18 = M3a 编译（Q5.12，FULL 块输入 + 分类头，另保留 PROJ 作逐层调试口，输出饱和到 int16）
//   TT_K3       mode3 每拍位置数：7（E1，默认）或 14（E2）
//   TT_W_BANKS  片上权重库数，当前只实现 1
#include "tt_types.h"
#include "tt_engine_regs.h"

#ifndef TT_DB
#define TT_DB 16
#endif
#if TT_DB != 16 && TT_DB != 18
#error "TT_DB must be 16 (M2) or 18 (M3a)"
#endif
#define TT_M3 (TT_DB == 18)
#ifndef TT_M3_OVERLAP
#define TT_M3_OVERLAP 0
#endif
#if (TT_M3_OVERLAP != 0 && TT_M3_OVERLAP != 1) || (TT_M3_OVERLAP && !TT_M3)
#error "TT_M3_OVERLAP must be 0 or 1 and is only supported with TT_DB=18"
#endif
typedef ap_fixed<TT_DB, TT_DB - TT_DF, AP_RND, AP_SAT> act_t;   // 片上激活（xb、ob）：M2 = data_t，M3 = Q5.12

#ifndef TT_K3
#define TT_K3 7
#endif
#if TT_K3 != 7 && TT_K3 != 14
#error "TT_K3 must be 7 or 14"
#endif
#define TT_KA (TT_K3 / 7)                      // mode3 一组同时算的 a 行数（每行 7 个位置）
#define TT_G  ((TT_W + TT_KA - 1) / TT_KA)     // 每 token 的 mode3 组数
#define TT_M3G ((TT_J + 3) / 4)                // M3 驻留字阵列数：一个 64 位字装 4 个 c
#ifndef TT_W_BANKS
#define TT_W_BANKS 1
#endif
#if TT_W_BANKS != 1
#error "D2 implements TT_W_BANKS = 1 only"
#endif

#define TT_N        TT_ENGINE_N                // 引擎固定 6 个 token
#define TT_NPROJ    (TT_ENGINE_LAYERS * TT_ENGINE_NPROJ)   // 48
#define TT_BEATS    (TT_D * TT_N / 4)          // 一个块 3969 个 64 位字
#define TT_IN_WORDS (TT_ENGINE_IN_STRIDE / 8)  // 3976：patch 跨距（64 位字）
#define TT_ST_WORDS (TT_ENGINE_STATS_STRIDE / 8)
#define TT_WPKG_WORDS (TT_ENGINE_WPKG16_BYTES / 8)          // 60072
#define TT_WPROJ_W0   (TT_ENGINE_WPKG_PROJ / 8)             // 23904
#define TT_WPROJ_WORDS (TT_ENGINE_WPROJ16_BYTES / 8)        // 36168

typedef ap_uint<64> u64;

unsigned int tt_engine(const u64 *x_in, const u64 *cube, u64 *x_out, u64 *q_out, u64 *k_out, u64 *v_out, u64 *stats_out,
                       const u64 *w_ddr, unsigned int cube_w, unsigned int seg_row, unsigned int seg_col, unsigned int n_patch,
                       unsigned int layer_lo, unsigned int layer_hi, unsigned int proj_mask, unsigned int mode,
                       unsigned int *cycles);

#endif
