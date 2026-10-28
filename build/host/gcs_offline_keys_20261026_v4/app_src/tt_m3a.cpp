#include "tt_m3a.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include <string.h>
#if defined(__aarch64__)
#include "xil_io.h"
#include "xparameters.h"
#endif

namespace {
XTt_engine ip;
bool initialized = false, loaded = false, faulted = false;
bool executing = false;
TTM3aWaitService wait_service = nullptr;
void *wait_context = nullptr;
uint32_t wait_interval = 256;
unsigned int selected_device = 0;
uint32_t last_return = 0;
uint32_t last_cycles = 0;
alignas(64) uint64_t unused[8];
const uint64_t ADDRESS_LIMIT = UINT64_C(0x100000000);

bool span_ok(const void *p, size_t bytes) {
    const uint64_t a = (uintptr_t)p;
    return p && bytes && (a & 63u) == 0 && a < ADDRESS_LIMIT &&
           bytes <= ADDRESS_LIMIT - a;
}
bool overlap(const void *a, size_t na, const void *b, size_t nb) {
    return (uintptr_t)a < (uintptr_t)b + nb && (uintptr_t)b < (uintptr_t)a + na;
}
void clean(const void *p, uint32_t bytes) {
#if defined(__aarch64__)
    for (uintptr_t a = (uintptr_t)p, end = a + bytes; a < end; a += 64)
        __asm__ __volatile__("dc cvac, %0" : : "r"(a) : "memory");
    __asm__ __volatile__("dsb sy" : : : "memory");
#else
    Xil_DCacheFlushRange((INTPTR)p, bytes);
#endif
}
int ready() {
    if (faulted) return TT_M3A_RESET_REQUIRED;
    if (executing) return TT_M3A_BUSY;
    return initialized ? TT_M3A_OK : TT_M3A_NOT_READY;
}
void unused_ports() {
    const u32 a = (u32)(uintptr_t)unused;
    XTt_engine_Set_cube(&ip, a);
    XTt_engine_Set_q_out(&ip, a);
    XTt_engine_Set_k_out(&ip, a);
    XTt_engine_Set_v_out(&ip, a);
    XTt_engine_Set_stats_out(&ip, a);
    XTt_engine_Set_cube_w(&ip, 0);
    XTt_engine_Set_seg_row(&ip, 0);
    XTt_engine_Set_seg_col(&ip, 0);
    XTt_engine_Set_proj_mask(&ip, 0);
}
int execute(uint32_t max_polls) {
    // Remains true until completion/timeout handling has returned. A network
    // receive callback cannot change registers, weights or the registered hook.
    struct Owner { Owner(){executing=true;} ~Owner(){executing=false;} } owner;
    { TTMeasureScope phase(TT_MEASURE_SUBMIT);XTt_engine_Start(&ip); }
    TTMeasureScope waiting(TT_MEASURE_WAIT);
    uint32_t unsuccessful = 0;
    for (uint32_t i = 0; i < max_polls; ++i) {
        if (!XTt_engine_IsDone(&ip)) {
            if(wait_service && ++unsuccessful>=wait_interval) {
                unsuccessful=0;
                TTMeasureContext &m=tt_measure_context();
                const uint64_t start=m.record?m.clock():0;
                wait_service(wait_context);
                if(m.record){const uint64_t end=m.clock();if(end<start)m.record->valid=false;
                    else m.record->add(m.record->wait_service_us,end-start);
                    m.record->add(m.record->wait_service_calls,1);}
            }
            continue;
        }
        last_return = XTt_engine_Get_return(&ip);
        if (TT_ENGINE_RET_VERSION(last_return) != TT_ENGINE_VERSION ||
            TT_ENGINE_RET_BITS(last_return) != 18 || TT_ENGINE_RET_FRAC(last_return) != 12) {
            faulted = true;
            loaded = false;
            return TT_M3A_CONTRACT;
        }
        if (TT_ENGINE_RET_ERR(last_return) != TT_ENGINE_ERR_OK) {
            loaded = false;
            return TT_M3A_ENGINE;
        }
        last_cycles=XTt_engine_Get_cycles(&ip);
        // An unpatched HLS C zero must NEVER masquerade as a PL measurement.
        if(!last_cycles||last_cycles==TT_ENGINE_CYCLES_INVALID||tt_m3a_clock_hz()!=TT_M3A_CONFIGURED_PL_HZ){
            last_cycles=0;faulted=true;loaded=false;return TT_M3A_CONTRACT;
        }
        return TT_M3A_OK;
    }
    faulted = true;
    loaded = false;
    return TT_M3A_TIMEOUT;
}
} // namespace

size_t tt_m3a_output_bytes(uint32_t n, uint32_t lo, uint32_t hi, uint32_t kind, bool dump) {
    if (!n || n > TT_ENGINE_NPATCH_MAX || lo > hi || hi >= TT_ENGINE_LAYERS ||
        kind > TT_ENGINE_OUT_ATTENTION || (dump && kind != TT_ENGINE_OUT_FEAT) ||
        (kind == TT_ENGINE_OUT_ATTENTION && lo != 0) ||
        (kind != TT_ENGINE_OUT_FEAT && hi != TT_ENGINE_LAYERS - 1)) return 0;
    uint64_t bytes = (uint64_t)n * (kind == TT_ENGINE_OUT_CLASS ? TT_ENGINE_CLASS_BYTES :
                      kind == TT_ENGINE_OUT_LOGITS ? TT_ENGINE_LOGIT_STRIDE :
                      kind == TT_ENGINE_OUT_ATTENTION ? TT_ENGINE_ATTN_STRIDE : TT_ENGINE_OUT32_STRIDE);
    if (dump) bytes *= hi - lo + 1;
    bytes = (bytes + 63u) & ~UINT64_C(63);
    // Cache APIs and DMA registers are 32-bit; reject before truncating.
    return bytes <= UINT32_MAX ? (size_t)bytes : 0;
}

int tt_m3a_init(unsigned int device_id) {
    if (faulted) return TT_M3A_RESET_REQUIRED;
    if (executing) return TT_M3A_BUSY;
    if (initialized) return device_id == selected_device ? TT_M3A_OK : TT_M3A_ARGUMENT;
    if (!span_ok(unused, sizeof(unused))) return TT_M3A_BUFFER;
    if (XTt_engine_Initialize(&ip, device_id) != XST_SUCCESS) return TT_M3A_INIT;
    initialized = true;
    selected_device = device_id;
    return TT_M3A_OK;
}

int tt_m3a_load_weights(const void *package, size_t bytes, uint32_t max_polls) {
    last_cycles=0;
    int status = ready();
    if (status) return status;
    if (!max_polls || bytes != TT_ENGINE_WPKG16_BYTES) return TT_M3A_ARGUMENT;
    if (!span_ok(package, bytes)) return TT_M3A_BUFFER;
    uint32_t head[4];
    memcpy(head, package, sizeof(head));
    if (head[0] != TT_ENGINE_WPKG_MAGIC || head[1] != 2 || !head[2] ||
        head[2] > TT_ENGINE_NCLS_MAX || head[3] != 16) return TT_M3A_ARGUMENT;
    loaded = false;
    clean(package, (uint32_t)bytes);
    unused_ports();
    XTt_engine_Set_x_in(&ip, (u32)(uintptr_t)unused);
    XTt_engine_Set_x_out(&ip, (u32)(uintptr_t)unused);
    XTt_engine_Set_w_ddr(&ip, (u32)(uintptr_t)package);
    XTt_engine_Set_n_patch(&ip, 0);
    XTt_engine_Set_layer_lo(&ip, 0);
    XTt_engine_Set_layer_hi(&ip, 0);
    XTt_engine_Set_mode(&ip, TT_ENGINE_MODE_LOAD_W);
    status = execute(max_polls);
    loaded = status == TT_M3A_OK;
    return status;
}

int tt_m3a_run(const TTM3aJob &j, uint32_t max_polls) {
    last_cycles=0;
    const int state = ready();
    if (state) return state;
    if (!loaded) return TT_M3A_NOT_READY;
    const size_t out_bytes = tt_m3a_output_bytes(j.n_patch, j.layer_lo, j.layer_hi, j.output_kind, j.dump);
    if (!max_polls || !out_bytes) return TT_M3A_ARGUMENT;
    const size_t in_bytes = (size_t)j.n_patch * TT_ENGINE_IN_STRIDE;
    if (j.input_capacity < in_bytes || j.output_capacity < out_bytes ||
        !span_ok(j.input, in_bytes) || !span_ok(j.output, out_bytes) ||
        overlap(j.input, in_bytes, j.output, out_bytes)) return TT_M3A_BUFFER;
    { TTMeasureScope cache(TT_MEASURE_CACHE_PREPARE);
    clean(j.input, (uint32_t)in_bytes);
    // Caller may have filled guards or reused dirty output cache lines.
    Xil_DCacheFlushRange((INTPTR)j.output, (u32)out_bytes);
    }
    TTMeasureScope submit(TT_MEASURE_SUBMIT);
    unused_ports();
    XTt_engine_Set_x_in(&ip, (u32)(uintptr_t)j.input);
    XTt_engine_Set_x_out(&ip, (u32)(uintptr_t)j.output);
    // No LOAD_W: resident weights are used; never dereference a stale caller package.
    XTt_engine_Set_w_ddr(&ip, (u32)(uintptr_t)unused);
    XTt_engine_Set_n_patch(&ip, j.n_patch);
    XTt_engine_Set_layer_lo(&ip, j.layer_lo);
    XTt_engine_Set_layer_hi(&ip, j.layer_hi);
    XTt_engine_Set_mode(&ip, TT_ENGINE_MODE_FULL | TT_ENGINE_MODE_OUT(j.output_kind) |
                           (j.dump ? TT_ENGINE_MODE_DUMP : 0u));
    submit.finish();
    const int status = execute(max_polls);
    if (status == TT_M3A_OK) {
        TTMeasureScope complete(TT_MEASURE_CACHE_COMPLETE);
        Xil_DCacheInvalidateRange((INTPTR)j.output, (u32)out_bytes);
        tt_measure_pl(last_cycles,j.n_patch);
    }
    return status;
}
uint32_t tt_m3a_last_return() { return last_return; }
uint32_t tt_m3a_last_cycles() { return last_cycles; }
uint32_t tt_m3a_clock_hz() {
#if defined(__aarch64__)
    // CRL addresses/masks: installed 2020.2 PMUFW crl_apb.h and platform psu_init.
    return tt_m3a_decode_clock(XPAR_PSU_PSS_REF_CLK_FREQ_HZ,Xil_In32(0xff5e0030u),
        Xil_In32(0xff5e0038u),Xil_In32(0xff5e00c0u),Xil_In32(0xff5e0040u));
#else
    return TT_M3A_CONFIGURED_PL_HZ; // HOST FIXTURE ONLY, never hardware evidence
#endif
}
int tt_m3a_set_wait_service(TTM3aWaitService service,void *context,uint32_t interval) {
    if(faulted)return TT_M3A_RESET_REQUIRED;
    if(executing)return TT_M3A_BUSY;
    if((service && !interval) || (!service && context))return TT_M3A_ARGUMENT;
    wait_service=service;wait_context=context;wait_interval=interval;
    return TT_M3A_OK;
}
