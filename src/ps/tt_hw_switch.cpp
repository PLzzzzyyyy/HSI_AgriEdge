// 运行时切换：所有源文件统一定义 TT_HW_RUNTIME_SWITCH，避免默认包装函数重复定义。
#ifdef TT_HW_RUNTIME_SWITCH
#include "tt_hw_switch.h"

int tt_pl_init();
void tt_pl_flush_all();
void tt_pl_proj_start(const int16_t *, int16_t *, int16_t *, int16_t *, int32_t *,
                      const int16_t *, const int16_t *, const int16_t *, int, int);
void tt_pl_proj_wait();
void tt_ps_proj_start(const int16_t *, int16_t *, int16_t *, int16_t *, int32_t *,
                      const int16_t *, const int16_t *, const int16_t *, int, int);
void tt_ps_proj_wait();

static TTBackend selected = TT_BACKEND_PS;
static bool pl_ready = false;
static bool pending = false;
static TTBackend pending_backend = TT_BACKEND_PS;

int tt_hw_init() { return 0; }  // 纯 PS 模式可在不访问 PL 寄存器的情况下运行

int tt_hw_select(TTBackend backend) {
    if (backend != TT_BACKEND_PS && backend != TT_BACKEND_PL) return 1;
    if (backend == selected) return 0;
    // 必须先按启动时的后端收尾，再初始化/切换，尤其不能在 PL 写 DDR 时整体 flush。
    tt_hw_proj_wait();
    if (backend == TT_BACKEND_PL && !pl_ready) {
        const int status = tt_pl_init();
        if (status) return status;
        pl_ready = true;
    }
    // 切到 PL 前整体 flush：纯 PS 后端用 CPU 写过 PL 的输出缓冲与 stats，PL 驱动此后不再逐次 flush 输出（见 tt_hw_xil.cpp）。
    if (backend == TT_BACKEND_PL && selected == TT_BACKEND_PS) tt_pl_flush_all();
    selected = backend;
    return 0;
}

TTBackend tt_hw_backend() { return selected; }
const char *tt_hw_backend_name() {
    return selected == TT_BACKEND_PL ? "PS+PL" : "PS-only";
}

void tt_hw_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_hw_proj_wait();
    pending_backend = selected;
    if (selected == TT_BACKEND_PL)
        tt_pl_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
    else
        tt_ps_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
    pending = true;
}

void tt_hw_proj_wait() {
    if (!pending) return;
    if (pending_backend == TT_BACKEND_PL) tt_pl_proj_wait();
    else tt_ps_proj_wait();
    pending = false;
}

void tt_hw_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_hw_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
    tt_hw_proj_wait();
}
#endif
