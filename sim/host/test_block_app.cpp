// Host control-path test of the actual board app. Inference and Xilinx services
// are mocked; rendering uses the actual implementation behind counted wrappers.
// g++ -O2 -std=c++11 -Isim/host/xil_stubs -o build/host/test_block_app.exe
//     sim/host/test_block_app.cpp src/ps/tt_block_app.cpp src/ps/tt_block_data.c
#include "../../src/ps/tt_block_app.h"
#include "../../src/ps/tt_block_data.h"
#include "../../src/ps/tt_block_render.h"
#include "../../src/ps/tt_hw_switch.h"
#include "xil_stubs/xil_cache.h"
#include "xil_stubs/xtime_l.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

// Rename only the renderer's public entry points to observe which one the
// real app calls, without duplicating the palette or image implementation.
#define tt_prediction_render_bmp real_prediction_render_bmp
#define tt_block_render_bmp real_block_render_bmp
#include "../../src/ps/tt_block_render.cpp"
#undef tt_prediction_render_bmp
#undef tt_block_render_bmp

const float tt_block_region[] = {0.0f};  // extraction is mocked; never dereferenced
tt_clock_fn tt_clock = 0;
extern uint8_t tt_board_labels[TT_BLOCK_PIXELS];
extern uint8_t tt_board_prediction_bmp[];
extern volatile unsigned tt_board_prediction_bytes;

enum Fault { NONE, WARMUP_NAN, PAIR_DIFF, SERIAL_INF, PAIR_NAN, PAIR_BAD_ARGMAX, RENDER_FAIL };
static Fault fault;
static int serial_calls, pair_calls, select_calls, render_calls, triptych_calls;
static int select_status;
static XTime ticks;
static std::vector<int> extracted, serial_indices, paired_indices;
struct Flush { INTPTR address; u32 bytes; };
static std::vector<Flush> flushes;

static int predicted_label(int index) {
    // Corners must pass the app's preflight reference check. All other labels
    // deliberately vary independently of PC reference and ground-truth maps.
    if (index == 0 || index == TT_BLOCK_PIXELS - 1) return tt_block_ref[index];
    return index % TT_CLASSES + 1;
}

static unsigned long long dummy_clock() { return 123; }
static void reset(Fault next = NONE) {
    fault = next;
    serial_calls = pair_calls = select_calls = render_calls = triptych_calls = select_status = 0;
    ticks = 0;
    extracted.clear(); serial_indices.clear(); paired_indices.clear(); flushes.clear();
    tt_clock = dummy_clock;
    // This deliberately represents a previously exported image. A failed run
    // must invalidate publication and may not make the previous image current.
    tt_board_prediction_bytes = TT_PRED_BMP_BYTES;
}

static void check_storage(const TTWork &work) {
    const uintptr_t ptrs[] = {(uintptr_t)work.x, (uintptr_t)work.out_q, (uintptr_t)work.out_k,
                             (uintptr_t)work.out_v, (uintptr_t)work.stats};
    for (int i = 0; i < 5; ++i) assert(ptrs[i] % 32 == 0);
    const size_t lengths[] = {(TT_D * 6 * sizeof(int16_t) + 31) & ~31u, (TT_D * 6 * sizeof(int16_t) + 31) & ~31u,
                             (TT_D * 6 * sizeof(int16_t) + 31) & ~31u, (TT_D * 6 * sizeof(int16_t) + 31) & ~31u,
                             TT_STATS_CAP * sizeof(int32_t)};
    for (int i = 0; i < 5; ++i) for (int j = i + 1; j < 5; ++j)
        assert(ptrs[i] + lengths[i] <= ptrs[j] || ptrs[j] + lengths[j] <= ptrs[i]);
}

int tt_hw_select(TTBackend mode) {
    assert(mode == TT_BACKEND_PL && tt_clock == 0);
    ++select_calls;
    return select_status;
}
void XTime_GetTime(XTime *out) { ticks += 1000; *out = ticks; }
void Xil_DCacheFlushRange(INTPTR address, u32 bytes) {
    assert(tt_board_prediction_bytes == 0);  // publication must follow both flushes
    assert((uintptr_t)address % 32 == 0 && bytes % 32 == 0);
    assert(render_calls == 1 && triptych_calls == 0);
    flushes.push_back({address, bytes});
}

void tt_patch_extract(const float *region, int rw, int row, int col, float *patch) {
    assert(region == tt_block_region && rw == TT_BLOCK_RW);
    assert(row >= 0 && row < 64 && col >= 0 && col < 64);
    assert((uintptr_t)patch % 32 == 0);
    extracted.push_back(row * 64 + col);
    patch[0] = (float)(row * 64 + col);
    patch[270 * 49 - 1] = -patch[0];
}

static int classify(const float *patch, tt_real *logits) {
    const int index = (int)patch[0];
    assert(index >= 0 && index < TT_BLOCK_PIXELS && patch[270 * 49 - 1] == -patch[0]);
    const int best = predicted_label(index) - 1;
    for (int c = 0; c < TT_CLASSES; ++c) logits[c] = c == best ? 10.0f : -1.0f;
    return best;
}
int tt_forward(const TTNet &net, TTWork &work, const float *patch, tt_real *logits) {
    assert(net.N == 6 && net.seq == 5 && tt_clock == 0);
    check_storage(work);
    ++serial_calls;
    const int index = (int)patch[0];
    serial_indices.push_back(index);
    const int best = classify(patch, logits);
    if (fault == SERIAL_INF && serial_calls > 20 && index == 1234)
        logits[0] = std::numeric_limits<float>::infinity();
    return best;
}
void tt_forward_pair(const TTNet &net, TTWork &a, TTWork &b, const float *pa, const float *pb,
                     tt_real *la, tt_real *lb, int *ba, int *bb) {
    assert(net.N == 6 && net.seq == 5 && tt_clock == 0);
    check_storage(a); check_storage(b);
    assert(a.x != b.x && a.stats != b.stats && a.out_q != b.out_q && a.out_k != b.out_k && a.out_v != b.out_v);
    assert(pa != pb);
    ++pair_calls;
    paired_indices.push_back((int)pa[0]); paired_indices.push_back((int)pb[0]);
    *ba = classify(pa, la); *bb = classify(pb, lb);
    if (fault == WARMUP_NAN && pair_calls == 1) la[0] = std::numeric_limits<float>::quiet_NaN();
    if (fault == PAIR_DIFF && pair_calls == 2) lb[0] += 0.25f;
    if (pair_calls > 11 && (int)pb[0] == 1235) {
        if (fault == PAIR_NAN) lb[0] = std::numeric_limits<float>::quiet_NaN();
        if (fault == PAIR_BAD_ARGMAX) *bb = TT_CLASSES;
    }
}

size_t tt_prediction_render_bmp(uint8_t *bmp, size_t capacity, const uint8_t *labels) {
    assert(tt_board_prediction_bytes == 0 && flushes.empty());
    assert(bmp == tt_board_prediction_bmp && labels == tt_board_labels);
    assert(labels != tt_block_ref && labels != tt_block_gt);
    ++render_calls;
    if (fault == RENDER_FAIL) return 0;
    return real_prediction_render_bmp(bmp, capacity, labels);
}
size_t tt_block_render_bmp(uint8_t *, size_t, const uint8_t *, const uint8_t *, const uint8_t *) {
    ++triptych_calls;
    assert(false && "board app must not export a comparison image");
    return 0;
}

static void corners(const std::vector<int> &indices, int calls) {
    assert(indices.size() >= (size_t)calls * 2);
    for (int i = 0; i < calls; ++i) assert(indices[2 * i] == 0 && indices[2 * i + 1] == 4095);
}
static void linear(const std::vector<int> &indices, size_t prefix) {
    assert(indices.size() == prefix + TT_BLOCK_PIXELS);
    for (int i = 0; i < TT_BLOCK_PIXELS; ++i) assert(indices[prefix + i] == i);
}
static unsigned le32(const uint8_t *p) {
    return (unsigned)p[0] | ((unsigned)p[1] << 8) | ((unsigned)p[2] << 16) | ((unsigned)p[3] << 24);
}
static void complete_image() {
    assert(select_calls == 1 && render_calls == 1 && triptych_calls == 0);
    assert(tt_board_prediction_bytes == TT_PRED_BMP_BYTES && flushes.size() == 2);
    assert(flushes[0].address == (INTPTR)tt_board_labels && flushes[0].bytes == TT_BLOCK_PIXELS);
    assert(flushes[1].address == (INTPTR)tt_board_prediction_bmp);
    assert(flushes[1].bytes == ((TT_PRED_BMP_BYTES + 31) & ~31u));
    assert(tt_board_prediction_bmp[0] == 'B' && tt_board_prediction_bmp[1] == 'M');
    assert(le32(tt_board_prediction_bmp + 2) == TT_PRED_BMP_BYTES);
    assert(le32(tt_board_prediction_bmp + 18) == 512 && le32(tt_board_prediction_bmp + 22) == 512);
    int differences = 0;
    const unsigned char rgb[9][3] = {{255,0,0},{238,154,0},{255,255,0},{0,255,0},{0,255,207},
                                   {0,160,255},{0,0,255},{176,0,255},{255,182,193}};
    for (int i = 0; i < TT_BLOCK_PIXELS; ++i) {
        const int label = predicted_label(i);
        assert(tt_board_labels[i] == label);
        differences += label != tt_block_ref[i];
        // Verify every actual BMP pixel, including orientation and 8x expansion.
        for (int dy = 0; dy < 8; ++dy) for (int dx = 0; dx < 8; ++dx) {
            const int y = i / 64 * 8 + dy, x = i % 64 * 8 + dx;
            const uint8_t *p = tt_board_prediction_bmp + 54 + (511 - y) * TT_PRED_BMP_STRIDE + x * 3;
            assert(p[0] == rgb[label - 1][2] && p[1] == rgb[label - 1][1] && p[2] == rgb[label - 1][0]);
        }
    }
    assert(differences > 1000);  // Detect any PC-reference substitution.
}

int main() {
    const TTNet net = {6, 5, 0, 0, 0, 0, 0};
    reset();
    tt_board_prediction_bytes = 0;
    assert(tt_block_check(net));
    assert(serial_calls == 20 && pair_calls == 11 && extracted.size() == 2 && render_calls == 0);
    corners(extracted, 1); corners(serial_indices, 10); corners(paired_indices, 11);
    std::puts("PASS app preflight: one warmup, ten comparisons, distinct corner patches");

    reset(); tt_block_run(net, false);
    assert(serial_calls == 20 + 4096 && pair_calls == 11);
    linear(extracted, 2); linear(serial_indices, 20); corners(paired_indices, 11);
    complete_image();
    std::puts("PASS app sequential: all 4096 coordinates, independent predicted-label BMP, flush before publication");

    reset(); tt_block_run(net, true);
    assert(serial_calls == 20 && pair_calls == 11 + 2048);
    linear(extracted, 2); linear(paired_indices, 22); corners(serial_indices, 10);
    complete_image();
    std::puts("PASS app pipeline: 2048 pairs, all 4096 coordinates, actual labels rendered independently");

    const Fault failures[] = {WARMUP_NAN, PAIR_DIFF, SERIAL_INF, PAIR_NAN, PAIR_BAD_ARGMAX};
    for (Fault f : failures) {
        reset(f); tt_block_run(net, f != SERIAL_INF);
        assert(tt_board_prediction_bytes == 0 && render_calls == 0 && flushes.empty());
        if (f == SERIAL_INF) assert(tt_board_labels[1233] != TT_BLOCK_UNKNOWN && tt_board_labels[1234] == TT_BLOCK_UNKNOWN);
        if (f == PAIR_NAN || f == PAIR_BAD_ARGMAX)
            assert(tt_board_labels[1233] != TT_BLOCK_UNKNOWN && tt_board_labels[1234] == TT_BLOCK_UNKNOWN && tt_board_labels[1235] == TT_BLOCK_UNKNOWN);
    }
    reset(RENDER_FAIL); tt_block_run(net, true);
    assert(render_calls == 1 && flushes.empty() && tt_board_prediction_bytes == 0);
    reset(); select_status = 7; tt_block_run(net, true);
    assert(extracted.empty() && render_calls == 0 && tt_board_prediction_bytes == 0);
    reset(); TTNet invalid = net; invalid.N = 10; invalid.seq = 9; tt_block_run(invalid, true);
    assert(select_calls == 0 && extracted.empty() && tt_board_prediction_bytes == 0);
    std::puts("PASS app failures: preflight mismatch, NaN/Inf, bad argmax, renderer/init/model failure publish no BMP");
    return 0;
}
