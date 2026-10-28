// 主机端 / 板上纯 PS 的 tucker_proj v1.4 逐位仿真：token 归一化 + 整数投影，算法在 tt_ref_int.h。
// PC 上验证 tt_net.cpp；板上作为纯 PS 基线（与 tt_hw_xil.cpp 二选一，或定义 TT_HW_RUNTIME_SWITCH 同时链接）。
#include "tt_hw.h"
#include "tt_net.h"
#include "tt_ref_int.h"

static int16_t norm_buf[TT_D * TT_NMAX];   // 归一化后的输入块（PL 里是片上 xb）

void tt_ps_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_ref::normalize(x, norm_buf, stats, n_tok);
    tt_ref::project(norm_buf, out_q, w_q, n_tok);
    if (n_proj >= 2) tt_ref::project(norm_buf, out_k, w_k, n_tok);
    if (n_proj >= 3) tt_ref::project(norm_buf, out_v, w_v, n_tok);
}

// 软件后端没有异步：start 就地算完，wait 空操作
void tt_ps_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_ps_proj(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
void tt_ps_proj_wait() {}

#ifndef TT_HW_RUNTIME_SWITCH
int tt_hw_init() { return 0; }
void tt_hw_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_ps_proj(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
void tt_hw_proj_wait() {}
void tt_hw_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_ps_proj(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
#endif
