// PC 回归：真实 tt_net + 整数后端；PL 桩延迟到 wait 执行，并检查在飞数据未被修改。
// g++ -O2 -std=c++11 -DTT_HW_RUNTIME_SWITCH -o build/host/test_backend_switch.exe
//     sim/host/test_backend_switch.cpp src/ps/tt_net.cpp src/ps/tt_hw_sim.cpp
//     src/ps/tt_hw_switch.cpp src/ps/tt_data.c
#include "../../src/ps/tt_net.h"
#include "../../src/ps/tt_hw_switch.h"
#include "../../src/ps/tt_data.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <algorithm>
#include <vector>

void tt_ps_proj(const int16_t *, int16_t *, int16_t *, int16_t *, int32_t *,
                const int16_t *, const int16_t *, const int16_t *, int, int);
static int init_calls = 0, init_status = 7, pl_calls = 0, ps_calls = 0;
static int qkv_calls = 0, mlp_calls = 0;
static int flush_calls = 0, completed_calls = 0;
static struct {
    const int16_t *in, *wq, *wk, *wv;
    int16_t *oq, *ok, *ov; int32_t *st;
    int n, projections;
    bool busy;
    std::vector<int16_t> input, weights_q, weights_k, weights_v, output_q, output_k, output_v;
} pending;
static unsigned long long clock_ticks = 0;
static unsigned long long test_clock() { return ++clock_ticks; }

int tt_pl_init() { assert(!pending.busy); init_calls++; return init_status; }
void tt_pl_flush_all() { assert(!pending.busy); flush_calls++; }
void tt_pl_proj_start(const int16_t *in, int16_t *oq, int16_t *ok, int16_t *ov, int32_t *st,
                const int16_t *wq, const int16_t *wk, const int16_t *wv, int n, int projections) {
    assert(!pending.busy);
    pl_calls++;
    if (projections == 3) qkv_calls++;
    else if (projections == 1) mlp_calls++;
    else assert(false);
    pending.in = in; pending.oq = oq; pending.ok = ok; pending.ov = ov; pending.st = st;
    pending.wq = wq; pending.wk = wk; pending.wv = wv;
    pending.n = n; pending.projections = projections;
    pending.input.assign(in, in + TT_D * n);
    pending.weights_q.assign(wq, wq + TT_NF);
    pending.output_q.assign(oq, oq + TT_D * n);
    if (projections >= 2) {
        pending.weights_k.assign(wk, wk + TT_NF);
        pending.output_k.assign(ok, ok + TT_D * n);
    }
    if (projections >= 3) {
        pending.weights_v.assign(wv, wv + TT_NF);
        pending.output_v.assign(ov, ov + TT_D * n);
    }
    pending.busy = true;
}

void tt_pl_proj_wait() {
    if (!pending.busy) return;
    assert(std::equal(pending.input.begin(), pending.input.end(), pending.in));
    assert(std::equal(pending.weights_q.begin(), pending.weights_q.end(), pending.wq));
    assert(std::equal(pending.output_q.begin(), pending.output_q.end(), pending.oq));
    if (pending.projections >= 2) {
        assert(std::equal(pending.weights_k.begin(), pending.weights_k.end(), pending.wk));
        assert(std::equal(pending.output_k.begin(), pending.output_k.end(), pending.ok));
    }
    if (pending.projections >= 3) {
        assert(std::equal(pending.weights_v.begin(), pending.weights_v.end(), pending.wv));
        assert(std::equal(pending.output_v.begin(), pending.output_v.end(), pending.ov));
    }
    tt_ps_proj(pending.in, pending.oq, pending.ok, pending.ov, pending.st, pending.wq, pending.wk, pending.wv,
               pending.n, pending.projections);
    pending.busy = false;
    completed_calls++;
}

static void run(TTBackend mode, bool profile = false) {
    static int16_t x[TT_D * TT_NMAX], oq[TT_D * TT_NMAX], ok[TT_D * TT_NMAX], ov[TT_D * TT_NMAX];
    static int32_t st[TT_STATS_CAP];
    TTNet net = { TT_DATA_N, TT_DATA_N - 1, tt_weights, tt_cls_token, tt_pos_embed, tt_classifier_w, tt_classifier_b };
    TTWork wk = { x, oq, ok, ov, st };
    tt_real logits[TT_CLASSES];
    assert(tt_hw_select(mode) == 0);
    tt_profile_reset();
    for (int l = 0; l < TT_LAYERS; l++) {
        assert(tt_layer_ticks[l] == 0);
        for (int s = 0; s < TT_PROF_N; s++) assert(tt_layer_prof[l][s] == 0);
    }
    for (int s = 0; s < TT_PROF_N; s++) assert(tt_prof[s] == 0);
    tt_clock = profile ? test_clock : 0;
    const int before = pl_calls;
    const int best = tt_forward(net, wk, tt_patch, logits);
    tt_clock = 0;
    assert(best == TT_DATA_REF_ARGMAX);
    double error = 0;
    for (int c = 0; c < TT_CLASSES; c++) {
        assert(std::isfinite(logits[c]));
        const double d = fabs(logits[c] - tt_ref_logits[c]);
        assert(d < TT_LOGIT_TOL);
        if (d > error) error = d;
    }
    assert(pl_calls - before == (mode == TT_BACKEND_PL ? 24 : 0));
    assert(!pending.busy && completed_calls == pl_calls);
    for (int s = 0; s < TT_PROF_N; s++) {
        unsigned long long sum = 0;
        for (int l = 0; l < TT_LAYERS; l++) {
            const auto ticks = tt_layer_prof[l][s];
            assert(profile ? ticks > 0 : ticks == 0);
            sum += ticks;
        }
        assert(sum == tt_prof[s]);
    }
    for (int l = 0; l < TT_LAYERS; l++) {
        unsigned long long sum = 0;
        for (int s = 0; s < TT_PROF_N; s++) sum += tt_layer_prof[l][s];
        assert(sum == tt_layer_ticks[l]);
    }
    if (mode == TT_BACKEND_PS) ps_calls++;
    printf("%s: full forward PASS, PL stub calls=%d, max|dlogit|=%.3e, profile=%s\n", tt_hw_backend_name(), pl_calls - before, error, profile ? "on" : "off");
}

static void test_pending_switch() {
    static int16_t in[TT_D * TT_NMAX], oq[TT_D * TT_NMAX], ok[TT_D * TT_NMAX], ov[TT_D * TT_NMAX];
    static int32_t st[TT_STATS_CAP];
    assert(tt_hw_select(TT_BACKEND_PL) == 0);
    const int flush_before = flush_calls;
    const int completed_before = completed_calls;
    tt_hw_proj_start(in, oq, ok, ov, st, tt_weights, tt_weights, tt_weights, TT_DATA_N, 1);
    assert(pending.busy && completed_calls == completed_before);
    assert(tt_hw_select(static_cast<TTBackend>(99)) != 0);
    assert(tt_hw_backend() == TT_BACKEND_PL && pending.busy);
    assert(tt_hw_select(TT_BACKEND_PL) == 0);  // 重选相同后端不 flush 或丢弃在飞调用
    assert(pending.busy && flush_calls == flush_before);
    assert(tt_hw_select(TT_BACKEND_PS) == 0);  // 先按 PL 后端 wait，再切换
    assert(!pending.busy && completed_calls == completed_before + 1);
    tt_hw_proj_wait();
    assert(completed_calls == completed_before + 1);
    assert(tt_hw_select(TT_BACKEND_PL) == 0);
    assert(flush_calls == flush_before + 1);
    tt_hw_proj_start(in, oq, ok, ov, st, tt_weights, tt_weights, tt_weights, TT_DATA_N, 1);
    tt_hw_proj_start(in, oq, ok, ov, st, tt_weights, tt_weights, tt_weights, TT_DATA_N, 1);
    assert(pending.busy && completed_calls == completed_before + 2);  // 再次 start 先排空
    tt_hw_proj_wait();
    tt_hw_proj_wait();
    assert(!pending.busy && completed_calls == completed_before + 3);
    assert(init_calls == 2);
}

int main() {
    assert(tt_hw_init() == 0 && init_calls == 0);
    run(TT_BACKEND_PS);
    assert(init_calls == 0);
    assert(tt_hw_select(TT_BACKEND_PL) == 7);  // 初始化失败不改变后端
    assert(tt_hw_backend() == TT_BACKEND_PS);
    assert(flush_calls == 0);
    init_status = 0;
    run(TT_BACKEND_PL);
    assert(init_calls == 2);
    run(TT_BACKEND_PS, true);
    run(TT_BACKEND_PL, true);
    assert(init_calls == 2);  // 初始化成功后重用
    assert(qkv_calls == 24 && mlp_calls == 24 && ps_calls == 2);
    assert(flush_calls == 2);
    assert(tt_hw_select(static_cast<TTBackend>(99)) != 0);
    assert(tt_hw_backend() == TT_BACKEND_PL);
    test_pending_switch();
    printf("PASS: PS/PL/PS/PL routing, failed init, init reuse and golden outputs (PL mocked)\n");
    printf("PASS: profiling on/off, reset, per-layer/stage totals and unchanged golden logits\n");
    printf("PASS: delayed PL completion, immutable in-flight buffers, pending switch/start and idle wait\n");
}
