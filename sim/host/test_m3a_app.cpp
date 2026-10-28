// Host harness: actual serial HLS C model for correctness, synthetic golden
// transport for the 12 performance cases. Its clock numbers are NOT performance.
#include "m3a_bench.h"
#include "m3a_vectors.h"
#include "tt_m3a.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include "xtime_l.h"
#include "tt_engine.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

static unsigned starts;
static std::string fault;
static uint64_t clock_ticks;
static struct {
    u32 x_in,cube,x_out,q_out,k_out,v_out,stats_out,w_ddr;
    u32 cube_w,seg_row,seg_col,n_patch,layer_lo,layer_hi,proj_mask,mode,ret;
    bool busy;
} r;
static void need(bool b, const char *msg) { if (!b) { std::printf("HARNESS FAIL %s\n", msg); std::exit(2); } }
static void idle() { need(!r.busy, "access after timeout/during DMA"); }
void XTime_GetTime(XTime *t) { *t = ++clock_ticks; }
int XTt_engine_Initialize(XTt_engine *,int) { idle(); return XST_SUCCESS; }
void XTt_engine_Start(XTt_engine *) { idle(); ++starts; r.busy = true; }
u32 XTt_engine_IsDone(XTt_engine *) {
    if ((fault == "load-timeout" && starts == 1) || (fault == "timeout" && starts == 2)) return 0;
    unsigned cycles = 0;
    if (starts <= 7) {
        r.ret = tt_engine((const u64 *)(uintptr_t)r.x_in, (const u64 *)(uintptr_t)r.cube,
            (u64 *)(uintptr_t)r.x_out, (u64 *)(uintptr_t)r.q_out, (u64 *)(uintptr_t)r.k_out,
            (u64 *)(uintptr_t)r.v_out, (u64 *)(uintptr_t)r.stats_out, (const u64 *)(uintptr_t)r.w_ddr,
            r.cube_w,r.seg_row,r.seg_col,r.n_patch,r.layer_lo,r.layer_hi,r.proj_mask,r.mode,&cycles);
    } else {
        need(r.mode == (TT_ENGINE_MODE_FULL | TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_LOGITS)) ||
             r.mode == (TT_ENGINE_MODE_FULL | TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_CLASS)), "perf not normal FULL");
        need(r.layer_lo == 0 && r.layer_hi == 11, "perf layer range");
        for (unsigned p = 0; p < r.n_patch; ++p)
            need(!std::memcmp((const unsigned char *)(uintptr_t)r.x_in + p * TT_ENGINE_IN_STRIDE,
                             m3a_input_a, TT_ENGINE_IN_BYTES), "both timing scopes must use same A");
        const unsigned kind = (r.mode & TT_ENGINE_MODE_OUT_MASK) >> TT_ENGINE_MODE_OUT_SHIFT;
        uint32_t *out = (uint32_t *)(uintptr_t)r.x_out;
        if (kind == TT_ENGINE_OUT_LOGITS)
            for (unsigned p = 0; p < r.n_patch; ++p) std::memcpy(out + p * 32, m3a_logits, 128);
        else {
            for (unsigned p = 0; p < r.n_patch; ++p) out[p] = m3a_classes[0];
            if (r.n_patch % 2) out[r.n_patch] = 0;
        }
        r.ret = (18u<<24) | (12u<<16) | (TT_ENGINE_VERSION<<8);
    }
    if (fault == "contract" && starts == 1) r.ret = 0;
    if ((fault == "mismatch" && starts == 2) || (fault == "timed-mismatch" && starts == 9))
        ((uint32_t *)(uintptr_t)r.x_out)[0] ^= 1;
    if (fault == "guard" && starts == 9) {
        const unsigned kind = (r.mode & TT_ENGINE_MODE_OUT_MASK) >> TT_ENGINE_MODE_OUT_SHIFT;
        const size_t bytes = tt_m3a_output_bytes(r.n_patch, 0, 11, kind, false);
        ((unsigned char *)(uintptr_t)r.x_out)[bytes] = 0;
    }
    r.busy = false;
    clock_ticks += 1000; // deliberately synthetic
    return 1;
}
u32 XTt_engine_Get_return(XTt_engine *) { idle(); return r.ret; }
u32 XTt_engine_Get_cycles(XTt_engine *) { return 12345; } // OFFLINE SYNTHETIC CLOCK
#define SET(n) void XTt_engine_Set_##n(XTt_engine *,u32 v) { idle(); r.n=v; }
SET(x_in) SET(cube) SET(x_out) SET(q_out) SET(k_out) SET(v_out) SET(stats_out) SET(w_ddr)
SET(cube_w) SET(seg_row) SET(seg_col) SET(n_patch) SET(layer_lo) SET(layer_hi) SET(proj_mask) SET(mode)
void Xil_DCacheFlushRange(INTPTR a,u32 n) { idle(); need(!(a&63)&&n&&!(n&63),"flush span"); }
void Xil_DCacheInvalidateRange(INTPTR a,u32 n) { idle(); need(!(a&63)&&n&&!(n&63),"invalidate span"); }
void Xil_DCacheFlush() { need(false,"whole cache"); }

int main(int argc, char **argv) {
    fault = argc == 2 ? argv[1] : "none";
    std::puts("HOST TEST ONLY: correctness=serial HLS C model; PERF=synthetic transport/clock, NOT measurements");
    const bool ok = m3a_benchmark();
    need(ok == (fault == "none"), "App success/failure gate");
    if (fault == "none") need(starts == 139, "7 correctness/load + 12*(warmup+10 runs)");
    else if (fault == "load-timeout" || fault == "contract") need(starts == 1, "stop at load");
    else if (fault == "timeout" || fault == "mismatch") need(starts == 2, "stop at first FULL");
    else need(starts == 9, "stop at first timed failure");
    std::printf("M3A_APP_HOST PASS mode=%s starts=%u\n", fault.c_str(), starts);
    return 0;
}
