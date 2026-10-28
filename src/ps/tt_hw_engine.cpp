// 板上 PL 后端（M2，D2）：通过 Vitis HLS 生成的驱动 XTt_engine 调 tt_engine 的 PROJ 模式，替换 v1.4 的 tt_hw_xil.cpp。
// 两者定义同一组 tt_pl_* 符号（tt_hw_switch.cpp 调用），应用只链接其中一个；tt_net.cpp、main_benchmark.cpp 不改。
// 不定义 TT_HW_RUNTIME_SWITCH 时本文件直接提供 tt_hw_* 接口。
//
// 与 v1.4 的区别：48 个投影的因子在 tt_pl_init 时一次装进片上（LOAD_W），之后每次调用只给层号与投影掩码。
// tt_hw.h 的接口仍传权重指针，驱动按"指针 − 已装载权重基址"反推 (层, 投影)：tt_net.cpp 的 layer_w 是
// weights + (layer·4 + proj)·NF。指针不在已装载数组内、n_tok ≠ 6、或 n_proj 与指针排布不符时不启动，打印一次并计数。
// n_proj = 1 时引擎把选中的投影写到它自己的输出口（Q/MLP → q_out，K → k_out，V → v_out），三个口都给 out_q，语义同 v1.4。
//
// cache 约定与 tt_hw_xil.cpp 相同（见其文件头）：x 启动前只清理（A53 用 dc cvac），输出与 stats 完成后 invalidate，
// 只在 CPU 可能写过输出缓冲时（outputs_clean = false）启动前 flush 输出；权重包拼好后整体清理一次。
// IP 的 m_axi 地址 32 位：所有 PL 缓冲必须在低 4 GB；激活块与 stats 按 cache 行对齐。
//
// TT_ENG_SELFCHECK（调试构建）：每次调用完成后用纯 PS 逐位实现（tt_hw_sim.cpp 的 tt_ps_proj）重算，逐元素比对
// 输出与 stats，每次完整前向（第 11 层 MLP 之后）打印累计结果。用于板上"PROJ 逐层逐位"的检查，计时无意义。
#include "tt_hw.h"
#include "tt_hw_engine.h"
#include "tt_net.h"
#include "tt_data.h"
#include "tt_engine_regs.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include <stdio.h>
#include <string.h>

static XTt_engine inst;
static struct {
    const int16_t *x, *wq, *wk, *wv;
    int16_t *q, *k, *v; int32_t *stats;
    u32 blk, layer, mask; int n_proj; bool busy;
} pending;
static bool initialized = false;
static bool outputs_clean = false;
static const int16_t *wbase = 0;               // 已装载进引擎的 weights_all 数组
static u32 last_ret = 0, n_rejected = 0, n_errors = 0;
void tt_pl_proj_wait();

// 权重包：weights_engine.bin 布局（tt_engine_regs.h）。M2 编译只读头与投影段，中间的 EMB / 分类头段保持 0。
static uint64_t wpkg[TT_ENGINE_WPKG16_BYTES / 8] __attribute__((aligned(TT_CACHE_LINE)));

static inline u32 round_line(u32 n) { return (n + (TT_CACHE_LINE - 1u)) & ~(u32)(TT_CACHE_LINE - 1u); }

// PS 写 → PL 读 只清理不作废（理由见 tt_hw_xil.cpp）
#if defined(__aarch64__)
static void clean_range(INTPTR adr, u32 len) {
    UINTPTR a = (UINTPTR)adr & ~(UINTPTR)(TT_CACHE_LINE - 1u);
    const UINTPTR end = (UINTPTR)adr + len;
    for (; a < end; a += TT_CACHE_LINE) __asm__ __volatile__("dc cvac, %0" : : "r"(a) : "memory");
    __asm__ __volatile__("dsb sy" : : : "memory");
}
#else
#define clean_range(a, l) Xil_DCacheFlushRange((a), (l))   // 主机测试：记为一次输入 flush 事件
#endif

static bool addr_ok(const void *p, unsigned int align) {
    const unsigned long long a = (UINTPTR)p;
    return (a & (align - 1u)) == 0 && (a >> 32) == 0;
}

// 同步跑一次引擎（装载用），返回引擎返回值
static u32 run_sync(u32 mode, u32 n_patch) {
    XTt_engine_Set_w_ddr(&inst, (u32)(UINTPTR)wpkg);
    XTt_engine_Set_n_patch(&inst, n_patch);
    XTt_engine_Set_layer_lo(&inst, 0);
    XTt_engine_Set_layer_hi(&inst, 0);
    XTt_engine_Set_proj_mask(&inst, 0);
    XTt_engine_Set_mode(&inst, mode);
    XTt_engine_Start(&inst);
    while (!XTt_engine_IsDone(&inst)) { }
    return XTt_engine_Get_return(&inst);
}

int tt_eng_load_weights(const int16_t *weights_all, unsigned int ncls) {
    if (!initialized) return -1;
    tt_pl_proj_wait();
    if (!addr_ok(wpkg, TT_CACHE_LINE)) { printf("tt_eng: ERROR weight package %p not aligned or above 4 GB\n", (void *)wpkg); return -1; }
    memset(wpkg, 0, 64);
    const uint32_t head[4] = { TT_ENGINE_WPKG_MAGIC, 2u, ncls, 16u };   // magic、包版本、ncls、权重位宽
    memcpy(wpkg, head, sizeof(head));
    memcpy((char *)wpkg + TT_ENGINE_WPKG_PROJ, weights_all, TT_ENGINE_WPROJ16_BYTES);
    clean_range((INTPTR)wpkg, TT_ENGINE_WPKG16_BYTES);
    const u32 r = run_sync(TT_ENGINE_MODE_LOAD_W, 0);
    last_ret = r;
    if (TT_ENGINE_RET_ERR(r) != TT_ENGINE_ERR_OK || TT_ENGINE_RET_VERSION(r) != TT_ENGINE_VERSION || TT_ENGINE_RET_BITS(r) != 16) {
        printf("tt_eng: ERROR LOAD_W returned 0x%08x (err %u, version %u, bits %u; expected 0, %u, 16)\n",
               (unsigned)r, (unsigned)TT_ENGINE_RET_ERR(r), (unsigned)TT_ENGINE_RET_VERSION(r), (unsigned)TT_ENGINE_RET_BITS(r),
               (unsigned)TT_ENGINE_VERSION);
        wbase = 0;
        return r ? (int)r : -1;
    }
    wbase = weights_all;
    printf("tt_eng: weights loaded (48 projections, ncls %u), engine contract v%u, M2 int16\n", ncls, (unsigned)TT_ENGINE_VERSION);
    return 0;
}

int tt_pl_init() {
    if (initialized) { tt_pl_proj_wait(); return 0; }
    int st = XTt_engine_Initialize(&inst, 0);   // XPAR_XTT_ENGINE_0_DEVICE_ID
    if (st != XST_SUCCESS) { xil_printf("XTt_engine_Initialize failed %d\r\n", st); return st; }
    pending.busy = false;
    Xil_DCacheFlush();                          // 启动加载的 DDR 数据可能仍有脏行（同 tt_hw_xil.cpp）
    outputs_clean = true;
    initialized = true;
    if (!wbase) {
        st = tt_eng_load_weights(tt_weights, TT_CLASSES);
        if (st) { initialized = false; return st; }
    }
    return 0;
}

void tt_pl_flush_all() { tt_pl_proj_wait(); Xil_DCacheFlush(); outputs_clean = true; }

static bool reject(const char *why, const int16_t *wq, int n_tok, int n_proj) {
    if (n_rejected++ == 0)
        printf("tt_eng: ERROR call rejected (%s): w_q=%p base=%p n_tok=%d n_proj=%d\n", why, (const void *)wq, (const void *)wbase, n_tok, n_proj);
    return false;
}

// 权重指针 → (层, 投影掩码)
static bool map_call(const int16_t *wq, const int16_t *wk, const int16_t *wv, int n_tok, int n_proj, u32 &layer, u32 &mask) {
    if (!wbase) return reject("no weights loaded", wq, n_tok, n_proj);
    if (n_tok != TT_ENGINE_N) return reject("engine supports 6 tokens only", wq, n_tok, n_proj);
    const long off = (long)(wq - wbase);
    if (off < 0 || off >= (long)TT_LAYERS * 4 * TT_NF || off % TT_NF) return reject("w_q not inside loaded weights", wq, n_tok, n_proj);
    const u32 pid = (u32)(off / TT_NF), p = pid & 3u;
    layer = pid >> 2;
    if (n_proj == 1) { mask = 1u << p; return true; }
    if (n_proj < 1 || n_proj > 3 || p != 0 || wk != wq + TT_NF || (n_proj == 3 && wv != wq + 2 * TT_NF))
        return reject("n_proj does not match q/k/v weight layout", wq, n_tok, n_proj);
    mask = n_proj == 2 ? (TT_ENGINE_PROJ_Q | TT_ENGINE_PROJ_K) : TT_ENGINE_PROJ_QKV;
    return true;
}

void tt_pl_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    if (pending.busy) tt_pl_proj_wait();
    u32 layer = 0, mask = 0;
    if (!map_call(w_q, w_k, w_v, n_tok, n_proj, layer, mask)) return;
    static bool reported = false;
    if (!reported && !(addr_ok(x, 8) && addr_ok(out_q, 8) && addr_ok(out_k, 8) && addr_ok(out_v, 8) && addr_ok(stats, 8))) {
        printf("tt_eng: ERROR PL buffers must be 8-byte aligned and below 4 GB (x=%p q=%p k=%p v=%p stats=%p)\n",
               (const void *)x, (void *)out_q, (void *)out_k, (void *)out_v, (void *)stats);
        reported = true;
    }
    int16_t *ok = n_proj == 1 ? out_q : out_k;
    int16_t *ov = n_proj == 1 ? out_q : out_v;
    const u32 blk = round_line((u32)TT_ENGINE_IN_BYTES);
    clean_range((INTPTR)x, blk);
    if (!outputs_clean) {
        Xil_DCacheFlushRange((INTPTR)out_q, blk);
        if (n_proj >= 2) Xil_DCacheFlushRange((INTPTR)out_k, blk);
        if (n_proj >= 3) Xil_DCacheFlushRange((INTPTR)out_v, blk);
        Xil_DCacheFlushRange((INTPTR)stats, TT_ENGINE_STATS_STRIDE);
    }
    XTt_engine_Set_x_in(&inst, (u32)(UINTPTR)x);
    XTt_engine_Set_cube(&inst, 0);
    XTt_engine_Set_x_out(&inst, 0);
    XTt_engine_Set_q_out(&inst, (u32)(UINTPTR)out_q);
    XTt_engine_Set_k_out(&inst, (u32)(UINTPTR)ok);
    XTt_engine_Set_v_out(&inst, (u32)(UINTPTR)ov);
    XTt_engine_Set_stats_out(&inst, (u32)(UINTPTR)stats);
    XTt_engine_Set_w_ddr(&inst, (u32)(UINTPTR)wpkg);
    XTt_engine_Set_cube_w(&inst, 0);
    XTt_engine_Set_seg_row(&inst, 0);
    XTt_engine_Set_seg_col(&inst, 0);
    XTt_engine_Set_n_patch(&inst, 1);
    XTt_engine_Set_layer_lo(&inst, layer);
    XTt_engine_Set_layer_hi(&inst, layer);
    XTt_engine_Set_proj_mask(&inst, mask);
    XTt_engine_Set_mode(&inst, 0);              // PROJ，不装载，库 0
    pending.x = x; pending.wq = w_q; pending.wk = w_k; pending.wv = w_v;
    pending.q = out_q; pending.k = out_k; pending.v = out_v; pending.stats = stats;
    pending.blk = blk; pending.layer = layer; pending.mask = mask; pending.n_proj = n_proj;
    pending.busy = true;
    XTt_engine_Start(&inst);
}

#ifdef TT_ENG_SELFCHECK
void tt_ps_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj);
static int16_t ref_q[TT_D * TT_ENGINE_N], ref_k[TT_D * TT_ENGINE_N], ref_v[TT_D * TT_ENGINE_N];
static int32_t ref_st[TT_STATS_CAP];
static u32 chk_calls = 0, chk_bad_calls = 0;
static unsigned long long chk_bad_elems = 0;

static u32 count_diff(const int16_t *a, const int16_t *b, int n) {
    u32 d = 0;
    for (int i = 0; i < n; i++) d += a[i] != b[i];
    return d;
}

static void selfcheck() {
    const int n = TT_D * TT_ENGINE_N, np = pending.n_proj;
    tt_ps_proj(pending.x, ref_q, ref_k, ref_v, ref_st, pending.wq, pending.wk, pending.wv, TT_ENGINE_N, np);
    const u32 dq = count_diff(pending.q, ref_q, n);
    const u32 dk = np >= 2 ? count_diff(pending.k, ref_k, n) : 0;
    const u32 dv = np >= 3 ? count_diff(pending.v, ref_v, n) : 0;
    u32 ds = 0;
    for (int i = 0; i < 2 * TT_ENGINE_N; i++) ds += pending.stats[i] != ref_st[i];
    chk_calls++;
    if (dq | dk | dv | ds) {
        chk_bad_calls++;
        chk_bad_elems += dq + dk + dv + ds;
        printf("tt_eng selfcheck: layer %u mask 0x%x mismatches q %u k %u v %u stats %u\n",
               (unsigned)pending.layer, (unsigned)pending.mask, (unsigned)dq, (unsigned)dk, (unsigned)dv, (unsigned)ds);
    }
    if (pending.layer == TT_LAYERS - 1 && (pending.mask & TT_ENGINE_PROJ_MLP))
        printf("tt_eng selfcheck: %u calls, %u mismatching calls, %llu mismatching values -> %s\n",
               (unsigned)chk_calls, (unsigned)chk_bad_calls, chk_bad_elems, chk_bad_calls ? "FAIL" : "PASS");
}
#endif

void tt_pl_proj_wait() {
    if (!pending.busy) return;
    while (!XTt_engine_IsDone(&inst)) { }
    Xil_DCacheInvalidateRange((INTPTR)pending.q, pending.blk);
    if (pending.n_proj >= 2) Xil_DCacheInvalidateRange((INTPTR)pending.k, pending.blk);
    if (pending.n_proj >= 3) Xil_DCacheInvalidateRange((INTPTR)pending.v, pending.blk);
    Xil_DCacheInvalidateRange((INTPTR)pending.stats, TT_ENGINE_STATS_STRIDE);
    pending.busy = false;
    last_ret = XTt_engine_Get_return(&inst);
    if (TT_ENGINE_RET_ERR(last_ret) != TT_ENGINE_ERR_OK && n_errors++ == 0)
        printf("tt_eng: ERROR engine returned 0x%08x (layer %u mask 0x%x)\n", (unsigned)last_ret, (unsigned)pending.layer, (unsigned)pending.mask);
#ifdef TT_ENG_SELFCHECK
    selfcheck();
#endif
}

void tt_pl_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_pl_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
    tt_pl_proj_wait();
}

unsigned int tt_eng_last_ret() { return last_ret; }
unsigned int tt_eng_rejected() { return n_rejected; }
unsigned int tt_eng_errors() { return n_errors; }

#ifndef TT_HW_RUNTIME_SWITCH
int tt_hw_init() { return tt_pl_init(); }
void tt_hw_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_pl_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
void tt_hw_proj_wait() { tt_pl_proj_wait(); }
void tt_hw_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_pl_proj(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
#endif
