#include "tt_block_app.h"
#include "tt_block_data.h"
#include "tt_block_render.h"
#include "tt_data.h"
#include "tt_hw.h"
#include "tt_hw_switch.h"
#include "xil_cache.h"
#if defined(__has_include)
#if __has_include("xtime_l.h")
#include "xtime_l.h"
#else
/* 2026.1 BSP 不再把 xtime_l.h 复制到导出 include；XTime_GetTime 与 COUNTS_PER_SECOND 由 xiltimer 提供 */
#include "xiltimer.h"
#endif
#else
#include "xtime_l.h"
#endif
#include <cmath>
#include <stdio.h>
#include <string.h>

#define AL __attribute__((aligned(TT_CACHE_LINE)))
static_assert(TT_BLOCK_SIZE == TT_BLOCK_SIDE, "Regenerate a 64x64 block for this renderer");
static_assert(TT_BLOCK_BANDS == 270, "Patch extraction requires 270 bands");
enum {
    DN = TT_D * 6,
    Q_CAPACITY = (DN + TT_CACHE_LINE / 2 - 1) & ~(TT_CACHE_LINE / 2 - 1),   // int16 capacity rounded to a complete cache line
    PATCH_SIZE = TT_BLOCK_BANDS * TT_W * TT_W,
    PATCH_CAPACITY = (PATCH_SIZE + 7) & ~7,
    PAIR_RUNS = 10,
    PRED_CAPACITY = (TT_PRED_BMP_BYTES + TT_CACHE_LINE - 1) & ~(TT_CACHE_LINE - 1)
};
struct WorkStorage {
    AL int16_t x[Q_CAPACITY], q[Q_CAPACITY], k[Q_CAPACITY], v[Q_CAPACITY];
    AL int32_t stats[TT_STATS_CAP];
    TTWork view() { TTWork w = {x, q, k, v, stats}; return w; }
};
static WorkStorage storage[2];
static AL float patches[2][PATCH_CAPACITY];

// Named, stable buffers for the Vitis debugger. Size is published only after flush.
AL uint8_t tt_board_labels[TT_BLOCK_PIXELS];
AL uint8_t tt_board_prediction_bmp[PRED_CAPACITY];
volatile unsigned tt_board_prediction_bytes = 0;

namespace {
unsigned long long now() { XTime t; XTime_GetTime(&t); return (unsigned long long)t; }
double ms(unsigned long long ticks) { return (double)ticks * 1000.0 / COUNTS_PER_SECOND; }
bool valid_logits(const tt_real *logits, int best) {
    if (best < 0 || best >= TT_CLASSES) return false;
    for (int c = 0; c < TT_CLASSES; ++c) if (!std::isfinite(logits[c])) return false;
    return true;
}
bool select_block(const TTNet &net) {
    if (net.N != 6 || net.seq != 5 || strcmp(TT_DATA_MODEL, TT_BLOCK_MODEL) != 0) {
        printf("Block requires matching unoverlapping N=6 weights and block data\n");
        return false;
    }
    tt_clock = 0;
    if (tt_hw_select(TT_BACKEND_PL)) { printf("Block: PL initialization failed\n"); return false; }
    return true;
}
void extract(int index, float *patch) {
    tt_patch_extract(tt_block_region, TT_BLOCK_RW, index / TT_BLOCK_SIZE, index % TT_BLOCK_SIZE, patch);
}
void export_images() {
    const size_t pred_bytes = tt_prediction_render_bmp(tt_board_prediction_bmp, sizeof(tt_board_prediction_bmp), tt_board_labels);
    if (!pred_bytes) { printf("BMP rendering failed\n"); return; }
    Xil_DCacheFlushRange((INTPTR)tt_board_labels, sizeof(tt_board_labels));
    Xil_DCacheFlushRange((INTPTR)tt_board_prediction_bmp, sizeof(tt_board_prediction_bmp));
    tt_board_prediction_bytes = (unsigned)pred_bytes;
    printf("\nBMP READY: PS rendered the actual board predictions into DDR.\n");
    printf("In Vitis XSCT, select the application core (7020: Cortex-A9 #0, ZU5EV: Cortex-A53 #0), suspend if needed, then paste:\n");
    printf("mrd -bin -file D:/HSI_AgriEdge/board/board_prediction.bmp -size b 0x%08lx %lu\n",
           (unsigned long)(UINTPTR)tt_board_prediction_bmp, (unsigned long)pred_bytes);
    printf("Open the BMP on the PC. Read it before starting another block run.\n");
    fflush(stdout);
}
} // namespace

bool tt_block_check(const TTNet &net) {
    if (!select_block(net)) return false;
    TTWork a = storage[0].view(), b = storage[1].view();
    // Two different windows, from opposite corners of the selected block.
    extract(0, patches[0]); extract(TT_BLOCK_PIXELS - 1, patches[1]);
    tt_real serial[2][TT_CLASSES], paired[2][TT_CLASSES];
    int sa, sb, pa, pb;
    tt_forward_pair(net, a, b, patches[0], patches[1], paired[0], paired[1], &pa, &pb);
    if (!valid_logits(paired[0], pa) || !valid_logits(paired[1], pb)) {
        printf("PAIR CHECK FAIL: warmup produced invalid logits\n"); return false;
    }
    unsigned long long serial_ticks = 0, pair_ticks = 0;
    double max_diff = 0;
    for (int run = 0; run < PAIR_RUNS; ++run) {
        const unsigned long long t0 = now();
        sa = tt_forward(net, a, patches[0], serial[0]);
        sb = tt_forward(net, b, patches[1], serial[1]);
        const unsigned long long t1 = now();
        tt_forward_pair(net, a, b, patches[0], patches[1], paired[0], paired[1], &pa, &pb);
        const unsigned long long t2 = now();
        serial_ticks += t1 - t0; pair_ticks += t2 - t1;
        bool ok = valid_logits(serial[0], sa) && valid_logits(serial[1], sb)
               && valid_logits(paired[0], pa) && valid_logits(paired[1], pb)
               && sa == pa && sb == pb && pa + 1 == tt_block_ref[0]
               && pb + 1 == tt_block_ref[TT_BLOCK_PIXELS - 1]
               && memcmp(serial, paired, sizeof(serial)) == 0;
        for (int i = 0; i < 2; ++i) for (int c = 0; c < TT_CLASSES; ++c) {
            const double d = fabs((double)serial[i][c] - paired[i][c]);
            if (d > max_diff) max_diff = d;
        }
        if (!ok) {
            printf("PAIR CHECK FAIL run=%d: sequential=%d/%d pair=%d/%d PC=%d/%d diff=%.3e\n",
                   run + 1, sa, sb, pa, pb, tt_block_ref[0] - 1, tt_block_ref[TT_BLOCK_PIXELS - 1] - 1, max_diff);
            return false;
        }
    }
    printf("PAIR CHECK PASS: %d repeats, two distinct patches, sequential/pair logits bitwise equal\n", PAIR_RUNS);
    const double seq_ms = ms(serial_ticks) / (PAIR_RUNS * 2), pair_ms = ms(pair_ticks) / (PAIR_RUNS * 2);
    printf("PAIR BENCH: sequential %.3f ms/pixel; pipelined %.3f ms/pixel; ratio %.3fx\n",
           seq_ms, pair_ms, pair_ms > 0 ? seq_ms / pair_ms : 0);
    printf("Pipelined ms/pixel is two-patch throughput; excludes extraction/validation/UART.\n");
    return true;
}

void tt_block_run(const TTNet &net, bool pipelined) {
    tt_board_prediction_bytes = 0;
    memset(tt_board_labels, TT_BLOCK_UNKNOWN, sizeof(tt_board_labels));
    printf("\n=== BOARD 64x64 %s inference ===\n", pipelined ? "pipelined" : "sequential");
    printf("origin=(%d,%d), zero-based; model=%s; 4096 pixels\n", TT_BLOCK_ROW0, TT_BLOCK_COL0, TT_BLOCK_MODEL);
    if (!tt_block_check(net)) { printf("Block stopped before inference; no new BMP is available\n"); return; }
    TTWork a = storage[0].view(), b = storage[1].view();
    unsigned long long extraction_ticks = 0, inference_ticks = 0;
    int completed = 0, agreement = 0, labeled = 0, correct = 0;
    int mismatch_shown = 0;
    const unsigned long long wall_start = now();
    const int step = pipelined ? 2 : 1;
    for (int index = 0; index < TT_BLOCK_PIXELS; index += step) {
        tt_real la[TT_CLASSES], lb[TT_CLASSES];
        int pa = -1, pb = -1;
        const unsigned long long t0 = now();
        extract(index, patches[0]);
        if (pipelined) extract(index + 1, patches[1]);
        const unsigned long long t1 = now();
        if (pipelined) tt_forward_pair(net, a, b, patches[0], patches[1], la, lb, &pa, &pb);
        else pa = tt_forward(net, a, patches[0], la);
        const unsigned long long t2 = now();
        extraction_ticks += t1 - t0; inference_ticks += t2 - t1;
        if (!valid_logits(la, pa) || (pipelined && !valid_logits(lb, pb))) {
            printf("Block FAIL at local pixel %d: invalid logits; no completed BMP exported\n", index);
            return;
        }
        for (int k = 0; k < step; ++k) {
            const int p = index + k;
            const uint8_t label = (uint8_t)((k == 0 ? pa : pb) + 1);
            tt_board_labels[p] = label;
            agreement += label == tt_block_ref[p];
            if (label != tt_block_ref[p] && mismatch_shown++ < 8)
                printf("Mismatch local=(%d,%d) board=%u PC=%u\n", p / TT_BLOCK_SIZE, p % TT_BLOCK_SIZE,
                       (unsigned)label, (unsigned)tt_block_ref[p]);
            if (tt_block_gt[p] != 0) { ++labeled; correct += label == tt_block_gt[p]; }
            ++completed;
        }
        if (completed % 256 == 0) {
            printf("Block %d/%d; compute %.3f ms/pixel; PC agreement %d/%d\n", completed, TT_BLOCK_PIXELS,
                   ms(extraction_ticks + inference_ticks) / completed, agreement, completed);
            fflush(stdout);
        }
    }
    const unsigned long long inference_end = now();
    printf("\nBLOCK COMPLETE: %d/%d predictions\n", completed, TT_BLOCK_PIXELS);
    printf("Network only: %.3f ms/pixel, %.3f s total\n", ms(inference_ticks) / completed, ms(inference_ticks) / 1000.0);
    printf("Patch extraction + normalization: %.3f ms/pixel\n", ms(extraction_ticks) / completed);
    printf("Compute incl. extraction: %.3f ms/pixel; loop wall incl. progress UART: %.3f s\n",
           ms(extraction_ticks + inference_ticks) / completed, ms(inference_end - wall_start) / 1000.0);
    printf("Board vs PC fixed labels: %d/%d (%.4f%%); all-label check %s\n", agreement, completed,
           agreement * 100.0 / completed, agreement == completed ? "PASS" : "DIFFERENCES");
    printf("Ground-truth OA (nonzero labels only): %d/%d (%.4f%%)\n", correct, labeled,
           labeled ? correct * 100.0 / labeled : 0);
    const unsigned long long render_start = now();
    export_images();
    printf("Rendering + flush + export instructions: %.3f ms (outside inference timing)\n", ms(now() - render_start));
}
