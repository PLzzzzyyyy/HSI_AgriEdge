// 板上串口切换整网：1=PS+PL，2=纯 PS，3=连续对比。替代 main.cpp 单独构建。
// 同时链接 tt_hw_sim.cpp、tt_hw_xil.cpp、tt_hw_switch.cpp，统一定义 TT_HW_RUNTIME_SWITCH。
#ifndef TT_HW_RUNTIME_SWITCH
#error "Build all sources with TT_HW_RUNTIME_SWITCH for the serial benchmark"
#endif
#include <stdio.h>
#include <cmath>
#include <algorithm>
#include "xparameters.h"
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
#include "xuartps_hw.h"
#include "tt_net.h"
#include "tt_hw.h"
#include "tt_hw_switch.h"
#include "tt_data.h"
#include "tt_block_app.h"

#define AL __attribute__((aligned(TT_CACHE_LINE)))
#ifndef TT_BENCH_RUNS
#define TT_BENCH_RUNS 10
#endif
static_assert(TT_BENCH_RUNS > 0, "TT_BENCH_RUNS must be positive");
static_assert(TT_DATA_N == 6 || TT_DATA_N == 10, "unsupported token count");
#if defined(XPAR_CPU_CORTEXA53_0_CPU_CLK_FREQ_HZ)
#define TT_CPU_NAME "Cortex-A53"
#define TT_CPU_HZ XPAR_CPU_CORTEXA53_0_CPU_CLK_FREQ_HZ
#else
#define TT_CPU_NAME "Cortex-A9"
#define TT_CPU_HZ XPAR_CPU_CORTEXA9_CORE_CLOCK_FREQ_HZ
#endif

enum { Q_CAPACITY = (TT_D * TT_NMAX + TT_CACHE_LINE / 2 - 1) & ~(TT_CACHE_LINE / 2 - 1) };   // int16 个数取整到整 cache 行
static AL int16_t g_x[Q_CAPACITY], g_oq[Q_CAPACITY], g_ok[Q_CAPACITY], g_ov[Q_CAPACITY];
static AL int32_t g_stats[TT_STATS_CAP];
static double times[TT_BENCH_RUNS];

static bool check_logits(const tt_real *logits, int best, double &max_error) {
    bool passed = best == TT_DATA_REF_ARGMAX;
    for (int c = 0; c < TT_CLASSES; c++) {
        const double d = fabs(logits[c] - tt_ref_logits[c]);
        if (!std::isfinite(logits[c]) || !std::isfinite(tt_ref_logits[c]) || d >= TT_LOGIT_TOL) passed = false;
        if (d > max_error) max_error = d;
    }
    return passed;
}

static unsigned long long board_clock() {
    XTime t;
    XTime_GetTime(&t);
    return (unsigned long long)t;
}

static double ticks_ms(unsigned long long ticks) {
    return (double)ticks * 1000.0 / COUNTS_PER_SECOND;
}

// 额外跑一次带时钟回调的完整前向。输出全部在前向结束后进行，不计入上面的 10 次加速比。
static bool print_profile(const TTNet &net, TTWork &wk) {
    printf("\n--- %s detail: one extra profiled forward, excluded from benchmark mean ---\n", tt_hw_backend_name());
    tt_profile_reset();
    tt_real logits[TT_CLASSES];
    tt_clock = board_clock;
    XTime start, stop;
    XTime_GetTime(&start);
    const int best = tt_forward(net, wk, tt_patch, logits);
    XTime_GetTime(&stop);
    tt_clock = 0;
    double error = 0;
    const bool passed = check_logits(logits, best, error);
    const double total = ticks_ms(stop - start);
    printf("Profile forward: %.3f ms, max|dlogit|=%.3e -> %s\n", total, error, passed ? "PASS" : "FAIL");
    printf("%-22s %10s %8s\n", "segment (12 layers)", "ms", "% full");
    unsigned long long segment_ticks = 0;
    for (int s = 0; s < TT_PROF_N; s++) {
        const char *label = tt_prof_name[s];
        if (tt_hw_backend() == TT_BACKEND_PS) {
            if (s == TT_PROF_PL_QKV) label = "PS software qkv";
            if (s == TT_PROF_PL_MLP) label = "PS software mlp";
        }
        const double ms = ticks_ms(tt_prof[s]);
        segment_ticks += tt_prof[s];
        printf("  %-20s %10.3f %8.1f\n", label, ms, total > 0 ? ms * 100.0 / total : 0);
    }
    const double layer_sum = ticks_ms(segment_ticks);
    printf("  %-20s %10.3f\n", "12-layer sum", layer_sum);
    printf("  %-20s %10.3f\n", "embed/head/overhead", total - layer_sum);
    printf("Projection backend: %s (PL timings include driver/cache/wait)\n", tt_hw_backend_name());
    printf("\n%-5s %9s %9s %9s %9s %9s %9s\n",
           "layer", "total ms", "PL qkv", "scores", "ctx+res", "PL mlp", "mlp res");
    for (int l = 0; l < TT_LAYERS; l++) {
        printf("%5d %9.3f", l, ticks_ms(tt_layer_ticks[l]));
        for (int s = 0; s < TT_PROF_N; s++) printf(" %9.3f", ticks_ms(tt_layer_prof[l][s]));
        printf("\n");
    }
    printf("Detail includes timer bookkeeping; speedup uses the unprofiled mean above.\n");
    return passed;
}

struct BenchmarkResult {
    bool passed;
    double mean_ms, median_ms;
    tt_real logits[TT_CLASSES];
};

static BenchmarkResult run_test(const TTNet &net, TTWork &wk, TTBackend backend) {
    BenchmarkResult result = {};
    if (tt_hw_select(backend)) {
        printf("Backend selection failed\n");
        return result;
    }
    printf("\n=== %s full-network benchmark ===\n", tt_hw_backend_name());
    printf("model=%s pixel=%s gt=%d N=%d runs=%d\n", TT_DATA_MODEL, TT_DATA_PIXEL, TT_DATA_GT, TT_DATA_N, TT_BENCH_RUNS);
    tt_clock = 0;
    Xil_DCacheFlush();  // 每组采用相同预热条件；PL 调用内的 cache 维护计入推理时间。
    tt_real logits[TT_CLASSES];
    double max_error = 0;
    printf("Warming up...\n");
    int best = tt_forward(net, wk, tt_patch, logits);
    if (!check_logits(logits, best, max_error)) {
        printf("Warmup FAIL: argmax=%d ref=%d max|diff|=%.3e\n", best, TT_DATA_REF_ARGMAX, max_error);
        return result;
    }
    printf("Warmup PASS\n");

    double sum = 0;
    bool passed = true;
    for (int r = 0; r < TT_BENCH_RUNS; r++) {
        XTime start, stop;
        XTime_GetTime(&start);
        best = tt_forward(net, wk, tt_patch, logits);
        XTime_GetTime(&stop);
        times[r] = (double)(stop - start) * 1000.0 / COUNTS_PER_SECOND;
        sum += times[r];
        const bool run_pass = check_logits(logits, best, max_error);
        passed = passed && run_pass;
        printf("forward run %2d: %.3f ms, argmax=%d, %s\n", r + 1, times[r], best, run_pass ? "PASS" : "FAIL");
    }
    std::sort(times, times + TT_BENCH_RUNS);
    const double median = (times[(TT_BENCH_RUNS - 1) / 2] + times[TT_BENCH_RUNS / 2]) / 2;
    printf("%s: mean=%.3f ms, median=%.3f ms, min=%.3f ms, max=%.3f ms\n",
           tt_hw_backend_name(), sum / TT_BENCH_RUNS, median, times[0], times[TT_BENCH_RUNS - 1]);
    printf("max|dlogit|=%.3e, argmax=%d ref=%d -> %s\n", max_error, best, TT_DATA_REF_ARGMAX, passed ? "PASS" : "FAIL");
    for (int c = 0; c < TT_CLASSES; c++)
        printf("class %d: computed=%+.9f reference=%+.9f\n", c, logits[c], tt_ref_logits[c]);
    result.passed = passed;
    result.mean_ms = sum / TT_BENCH_RUNS;
    result.median_ms = median;
    for (int c = 0; c < TT_CLASSES; c++) result.logits[c] = logits[c];
    const bool profile_passed = print_profile(net, wk);
    result.passed = result.passed && profile_passed;
    return result;
}

static void menu() {
    printf("\n[1] PL acceleration   [2] PS-only   [3] Compare both\n");
    printf("[4] 64x64 pipelined + BMP   [5] Quick pair check   [6] 64x64 sequential + BMP\n");
    printf("Send ASCII 1..6 (HEX mode off). Block outputs are rendered on PS, read using XSCT.\n");
    fflush(stdout);
}

int main() {
    Xil_ICacheEnable();
    Xil_DCacheEnable();
    tt_clock = 0;
    printf("\n=== TT serial benchmark ===\n");
    printf("%s clock (BSP)=%lu Hz, timer=%lu Hz; PS glue float32 (%s), PL normalize+projection v1.4, int16 x; tol=%g\n",
           TT_CPU_NAME, (unsigned long)TT_CPU_HZ, (unsigned long)COUNTS_PER_SECOND,
           tt_net_backend_name(), (double)TT_LOGIT_TOL);
    printf("Scope: preprocessed patch -> embed -> 12 layers -> 9 logits; batch=1\n");
    printf("One warmup + %d timed forwards (profiling off) + one separate detail forward per mode\n", TT_BENCH_RUNS);
    printf("Validation and serial output outside timing\n");
    if (tt_hw_init()) return 1;
    TTNet net = { TT_DATA_N, TT_DATA_N - 1, tt_weights, tt_cls_token, tt_pos_embed, tt_classifier_w, tt_classifier_b };
    TTWork wk = { g_x, g_oq, g_ok, g_ov, g_stats };
    menu();
    while (true) {
        const char key = (char)XUartPs_RecvByte(STDIN_BASEADDRESS);
        if (key == '\r' || key == '\n' || key == ' ') continue;
        if (key == '1') {
            run_test(net, wk, TT_BACKEND_PL);
        } else if (key == '2') {
            run_test(net, wk, TT_BACKEND_PS);
        } else if (key == '3') {
            // 先纯 PS，再 PL，确保覆盖 CPU 写输出缓冲后交还 PL 的切换路径。
            const BenchmarkResult ps = run_test(net, wk, TT_BACKEND_PS);
            const BenchmarkResult pl = run_test(net, wk, TT_BACKEND_PL);
            double difference = 0;
            for (int c = 0; c < TT_CLASSES; c++) {
                const double d = fabs(ps.logits[c] - pl.logits[c]);
                if (d > difference) difference = d;
            }
            if (ps.passed && pl.passed && difference < 1e-4 && pl.mean_ms > 0 && pl.median_ms > 0) {
                printf("\nCOMPARE PASS: PS-only %.3f ms / PS+PL %.3f ms = %.3fx speedup (mean)\n",
                       ps.mean_ms, pl.mean_ms, ps.mean_ms / pl.mean_ms);
                printf("Median speedup=%.3fx; PS-only vs PS+PL max|dlogit|=%.3e\n",
                       ps.median_ms / pl.median_ms, difference);
            } else {
                printf("COMPARE FAIL: no speedup reported; max|dlogit|=%.3e\n", difference);
            }
        } else if (key == '4') {
            tt_block_run(net, true);
        } else if (key == '5') {
            tt_block_check(net);
        } else if (key == '6') {
            tt_block_run(net, false);
        } else {
            printf("Unknown key: send 1..6\n");
        }
        menu();
    }
}
