// XTt_engine 驱动的主机实现：寄存器存进结构体，由 HLS C 模型 tt_engine()（src/hls/tt_engine.cpp，与 IP 同一组
// -DTT_DB / -DTT_K3 编译）执行。模拟异步：Start 只置忙，第一次 IsDone 返回 0，第二次才跑模型并返回 1；
// 忙时调用任何 setter 或 cache 操作都算驱动违约（abort）。寄存器是 32 位地址，测试程序的缓冲必须在低 4 GB
// （链接 -Wl,--image-base=0x10000000 -Wl,--disable-dynamicbase，缓冲用静态数组）。
#include "../../../src/hls/tt_engine.h"
#include "xtt_engine.h"
#include <cstdio>
#include <cstdlib>

static struct {
    u32 x_in, cube, x_out, q_out, k_out, v_out, stats_out, w_ddr, cube_w, seg_row, seg_col, n_patch, layer_lo, layer_hi, proj_mask, mode;
    u32 ret; int polls; bool busy;
} r;

bool xtt_model_busy() { return r.busy; }
static void idle(const char *what) {
    if (r.busy) { std::printf("DRIVER VIOLATION: %s while engine busy\n", what); std::abort(); }
}
template <class T> static T *ptr(u32 a) { return (T *)(uintptr_t)a; }

int XTt_engine_Initialize(XTt_engine *, int) { idle("Initialize"); return XST_SUCCESS; }
void XTt_engine_Start(XTt_engine *) { idle("Start"); r.busy = true; r.polls = 0; }
u32 XTt_engine_IsDone(XTt_engine *) {
    if (!r.busy) return 1;
    if (++r.polls == 1) return 0;
    unsigned int cycles = 0;
    r.ret = tt_engine(ptr<const u64>(r.x_in), ptr<const u64>(r.cube), ptr<u64>(r.x_out), ptr<u64>(r.q_out), ptr<u64>(r.k_out),
                      ptr<u64>(r.v_out), ptr<u64>(r.stats_out), ptr<const u64>(r.w_ddr), r.cube_w, r.seg_row, r.seg_col,
                      r.n_patch, r.layer_lo, r.layer_hi, r.proj_mask, r.mode, &cycles);
    r.busy = false;
    return 1;
}
u32 XTt_engine_Get_return(XTt_engine *) { idle("Get_return"); return r.ret; }
u32 XTt_engine_Get_cycles(XTt_engine *) { return 12345; } // OFFLINE SYNTHETIC CLOCK
#define SETTER(name) void XTt_engine_Set_##name(XTt_engine *, u32 v) { idle("Set_" #name); r.name = v; }
SETTER(x_in) SETTER(cube) SETTER(x_out) SETTER(q_out) SETTER(k_out) SETTER(v_out) SETTER(stats_out) SETTER(w_ddr)
SETTER(cube_w) SETTER(seg_row) SETTER(seg_col) SETTER(n_patch) SETTER(layer_lo) SETTER(layer_hi) SETTER(proj_mask) SETTER(mode)
