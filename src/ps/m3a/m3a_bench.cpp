// Serial M3a board baseline. No M2 owner or layer-wise PS calls.
#include "m3a_bench.h"
#include "m3a_vectors.h"
#include "m3a_package.h"
#include "tt_m3a.h"
#include "tt_net.h"
#include "tt_data.h"
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
#include "xil_cache.h"
#include <stdio.h>
#include <string.h>
#include <limits.h>

#ifndef M3A_BENCH_RUNS
#define M3A_BENCH_RUNS 10
#endif
#ifndef M3A_BENCH_BATCH
#define M3A_BENCH_BATCH 16
#endif
#ifndef M3A_MAX_POLLS
#define M3A_MAX_POLLS 100000000u
#endif
static_assert(M3A_BENCH_RUNS > 0 && M3A_BENCH_RUNS <= 1000, "bounded repeat count");
static_assert(M3A_BENCH_BATCH >= 3 && M3A_BENCH_BATCH <= 64, "bounded static DDR buffers");
static_assert(TT_DATA_N == 6 && TT_CLASSES == 9, "LongKou n6 fixture only");
static_assert(M3A_MAX_POLLS > 0, "polls is an iteration bound, not milliseconds");

namespace {
enum { IN_WORDS = TT_ENGINE_IN_STRIDE / 2, OUT_BYTES = 12 * TT_ENGINE_OUT32_STRIDE };
alignas(64) int16_t input[M3A_BENCH_BATCH * IN_WORDS];
alignas(64) uint32_t output[(OUT_BYTES + 64) / 4];
const TTNet net = {6, 5, tt_weights, tt_cls_token, tt_pos_embed, tt_classifier_w, tt_classifier_b};
unsigned mismatches;

uint64_t now() { XTime t; XTime_GetTime(&t); return (uint64_t)t; }
double ms(uint64_t ticks) { return (double)ticks * 1000.0 / COUNTS_PER_SECOND; }
bool status_ok(int rc, const char *stage) {
    if (rc == TT_M3A_OK) return true;
    printf("FAIL %s driver=%d last_return=0x%08lx (may be stale on timeout)\n",
           stage, rc, (unsigned long)tt_m3a_last_return());
    puts("ABORT: no more DMA/buffer access. External PL reset and App restart required.");
    return false;
}
bool compare(const void *actual, const void *expected, size_t bytes, const char *name) {
    if (!memcmp(actual, expected, bytes)) return true;
    const unsigned char *a = (const unsigned char *)actual, *b = (const unsigned char *)expected;
    size_t first = 0, bad = 0;
    for (size_t i = 0; i < bytes; ++i) if (a[i] != b[i]) { if (!bad) first = i; ++bad; }
    ++mismatches;
    printf("FAIL %s byte_mismatches=%lu first=%lu got=%02x expected=%02x\n",
           name, (unsigned long)bad, (unsigned long)first, a[first], b[first]);
    return false;
}
TTM3aJob job(unsigned n, unsigned kind, unsigned lo = 0, bool dump = false) {
    TTM3aJob j = {input, sizeof(input), output, sizeof(output), n, lo, 11, kind, dump};
    return j;
}
void prepare(unsigned n, bool embed, bool alternate = true) {
    memset(input, 0, n * TT_ENGINE_IN_STRIDE);
    for (unsigned i = 0; i < n; ++i) {
        if (embed) tt_embed(net, tt_patch, input + i * IN_WORDS);
        else memcpy(input + i * IN_WORDS, alternate && i % 2 ? m3a_input_b : m3a_input_a, TT_ENGINE_IN_BYTES);
    }
}
bool result(unsigned n, unsigned kind, bool all_a) {
    bool ok = true;
    for (unsigned i = 0; i < n; ++i) {
        const unsigned ref = all_a ? 0 : i % 2;
        if (kind == TT_ENGINE_OUT_LOGITS)
            ok &= compare(output + i * 32, m3a_logits + ref * 32, 128, "LOGITS32");
        else ok &= compare(output + i, m3a_classes + ref, 4, "CLASS+confidence");
    }
    if (kind == TT_ENGINE_OUT_CLASS && n % 2) {
        const uint32_t zero = 0;
        ok &= compare(output + n, &zero, 4, "CLASS odd tail");
    }
    return ok;
}
void guard_prepare(const TTM3aJob &j) {
    memset(output, 0xa5, sizeof(output));
    const size_t span = tt_m3a_output_bytes(j.n_patch, j.layer_lo, j.layer_hi, j.output_kind, j.dump);
    Xil_DCacheFlushRange((INTPTR)((unsigned char *)output + span), 64);
}
bool guard_check(const TTM3aJob &j) {
    const size_t span = tt_m3a_output_bytes(j.n_patch, j.layer_lo, j.layer_hi, j.output_kind, j.dump);
    Xil_DCacheInvalidateRange((INTPTR)((unsigned char *)output + span), 64);
    unsigned char guard[64]; memset(guard, 0xa5, sizeof(guard));
    return compare((const unsigned char *)output + span, guard, sizeof(guard), "output guard");
}
bool checked_run(const TTM3aJob &j) {
    guard_prepare(j);
    if (!status_ok(tt_m3a_run(j, M3A_MAX_POLLS), "FULL")) return false;
    return guard_check(j);
}
bool correctness() {
    prepare(1, true);
    if (!compare(input, m3a_input_a, TT_ENGINE_IN_BYTES, "PS embed vs golden A")) return false;
    puts("PASS PS embed vs golden A (all 15876 int16 values)");
    prepare(3, false);
    if (!checked_run(job(3, TT_ENGINE_OUT_LOGITS)) || !result(3, TT_ENGINE_OUT_LOGITS, false)) return false;
    printf("PASS A/B/A LOGITS32; A_q16=");
    for (unsigned c = 0; c < 9; ++c) printf("%s%ld", c ? "," : "", (long)(int32_t)output[c]);
    puts("");
    if (!checked_run(job(3, TT_ENGINE_OUT_CLASS)) || !result(3, TT_ENGINE_OUT_CLASS, false)) return false;
    printf("PASS A/B/A CLASS+confidence+odd_tail; A=0x%08lx B=0x%08lx (labels zero-based)\n",
           (unsigned long)output[0], (unsigned long)output[1]);
    prepare(1, false);
    if (!checked_run(job(1, TT_ENGINE_OUT_FEAT, 0, true))) return false;
    for (unsigned l = 0; l < 12; ++l) {
        if (!compare(output + l * (TT_ENGINE_OUT32_STRIDE / 4),
                     m3a_layers_a + l * TT_ENGINE_BLK_ELEMS,
                     TT_ENGINE_OUT32_BYTES, "DUMP layer")) return false;
        printf("PASS DUMP layer=%u elements=%u\n", l, (unsigned)TT_ENGINE_BLK_ELEMS);
    }
    // Resume from the ACTUAL layer-4 dump, not a substituted golden buffer.
    const int32_t *layer4 = (const int32_t *)(output + 4 * (TT_ENGINE_OUT32_STRIDE / 4));
    memset(input, 0, TT_ENGINE_IN_STRIDE);
    for (unsigned i = 0; i < TT_ENGINE_BLK_ELEMS; ++i) {
        if (layer4[i] < INT16_MIN || layer4[i] > INT16_MAX) { puts("FAIL resume would truncate 18-bit FEAT"); return false; }
        input[i] = (int16_t)layer4[i];
    }
    if (!checked_run(job(1, TT_ENGINE_OUT_FEAT, 5)) ||
        !compare(output, m3a_layers_a + 11 * TT_ENGINE_BLK_ELEMS, TT_ENGINE_OUT32_BYTES, "resume FEAT")) return false;
    if (!checked_run(job(1, TT_ENGINE_OUT_CLASS, 5)) || !result(1, TT_ENGINE_OUT_CLASS, true)) return false;
    puts("PASS resume actual DUMP L4 -> L5..11 FEAT/CLASS");
    prepare(1, true);
    if (!checked_run(job(1, TT_ENGINE_OUT_LOGITS)) || !result(1, TT_ENGINE_OUT_LOGITS, true)) return false;
    puts("M3A_CORRECTNESS PASS mismatches=0");
    return true;
}
bool measure(unsigned n, unsigned kind, bool embed) {
    const TTM3aJob j = job(n, kind);
    const char *scope = embed ? "PS_EMBED_PLUS_FULL" : "PREEMBED_FULL";
    const char *out = kind == TT_ENGINE_OUT_LOGITS ? "LOGITS" : "CLASS";
    // Same repeated A patch in BOTH scopes: timing deltas must not mix A/B inputs.
    prepare(n, embed, false);
    if (!checked_run(j) || !result(n, kind, true)) return false;
    uint64_t times[M3A_BENCH_RUNS], total = 0, low = UINT64_MAX, high = 0;
    for (unsigned run = 0; run < M3A_BENCH_RUNS; ++run) {
        guard_prepare(j);
        const uint64_t start = now();
        if (embed) for (unsigned p = 0; p < n; ++p) tt_embed(net, tt_patch, input + p * IN_WORDS);
        const int rc = tt_m3a_run(j, M3A_MAX_POLLS);
        const uint64_t stop = now();
        if (!status_ok(rc, "TIMED FULL")) return false;
        if (stop <= start) { puts("FAIL timer not monotonic/nonzero"); return false; }
        if (!guard_check(j) || !result(n, kind, true)) return false;
        const uint64_t t = stop - start;
        times[run] = t; total += t;
        if (t < low) low = t;
        if (t > high) high = t;
    }
    // No UART traffic within the timed repeat loop, including between repeats.
    for (unsigned r = 0; r < M3A_BENCH_RUNS; ++r)
        printf("SAMPLE scope=%s out=%s n=%u run=%u ticks=%llu\n", scope, out, n, r, (unsigned long long)times[r]);
    printf("PERF scope=%s out=%s n=%u runs=%u total_ticks=%llu mean_batch_ms=%.6f min_batch_ms=%.6f max_batch_ms=%.6f ms_per_patch=%.6f patches_per_s=%.3f\n",
           scope, out, n, (unsigned)M3A_BENCH_RUNS, (unsigned long long)total,
           ms(total) / M3A_BENCH_RUNS, ms(low), ms(high), ms(total) / (M3A_BENCH_RUNS * n),
           (double)COUNTS_PER_SECOND * (M3A_BENCH_RUNS * n) / total);
    return true;
}
} // namespace

bool m3a_benchmark() {
    mismatches = 0;
    puts("M3A_SERIAL_BASELINE v1");
    printf("package=%s source=%s expected_xsa_sha256=%s\n", M3A_PACKAGE_ID, M3A_SOURCE_REV, M3A_XSA_SHA256);
    puts("Expected serial XSA only; software cannot identify the programmed bitstream hash.");
    printf("timer_hz=%llu runs=%u batch=%u max_polls=%lu PS_backend=%s\n",
           (unsigned long long)COUNTS_PER_SECOND, (unsigned)M3A_BENCH_RUNS,
           (unsigned)M3A_BENCH_BATCH, (unsigned long)M3A_MAX_POLLS, tt_net_backend_name());
    puts("Timer: driver input clean + output flush + MMIO + FULL + poll + output invalidate.");
    puts("PS_EMBED_PLUS_FULL adds PS tt_embed on preprocessed CHW patch; no extract/normalize/I-O.");
    puts("Weights loaded once, measured separately. DUMP/checks/UART/warmup excluded from PERF.");
    if (!status_ok(tt_m3a_init(), "INIT")) return false;
    const uint64_t start = now();
    const int rc = tt_m3a_load_weights(m3a_weights, sizeof(m3a_weights), M3A_MAX_POLLS);
    const uint64_t stop = now();
    if (!status_ok(rc, "LOAD_W")) return false;
    if (stop <= start) { puts("FAIL load timer"); return false; }
    printf("LOAD_W PASS bytes=%lu ticks=%llu ms=%.6f return=0x%08lx\n", (unsigned long)sizeof(m3a_weights),
           (unsigned long long)(stop - start), ms(stop - start), (unsigned long)tt_m3a_last_return());
    if (!correctness()) return false;
    const unsigned batches[] = {1, 3, M3A_BENCH_BATCH};
    for (unsigned b = 0; b < 3; ++b) {
        if (b == 2 && M3A_BENCH_BATCH == 3) continue;
        for (unsigned k = 0; k < 2; ++k) {
            const unsigned kind = k ? TT_ENGINE_OUT_CLASS : TT_ENGINE_OUT_LOGITS;
            if (!measure(batches[b], kind, false) || !measure(batches[b], kind, true)) return false;
        }
    }
    printf("M3A_BASELINE PASS mismatches=%u\n", mismatches);
    return true;
}
