// Host test of tt_hw_xil.cpp itself; models cache-call ordering, not physical cache hardware.
// g++ -O2 -std=c++11 -Isim/host/xil_stubs -o build/host/test_hw_cache.exe
//     sim/host/test_hw_cache.cpp src/ps/tt_hw_xil.cpp
#include "../../src/ps/tt_hw.h"
#include "../../src/ps/tt_net.h"
#include "xil_stubs/xtucker_proj.h"
#include <cassert>
#include <cstdio>
#include <vector>

enum Kind { INIT, FLUSH_ALL, FLUSH_RANGE, START, DONE, INVALIDATE };
struct Event { Kind kind; INTPTR address; u32 length; };
static std::vector<Event> events;
static bool hw_busy;
static int init_status = 7, init_calls, polls;
static void event(Kind k, INTPTR a = 0, u32 n = 0) { events.push_back({k, a, n}); }
int XTucker_proj_Initialize(XTucker_proj *, int) {
    assert(!hw_busy); init_calls++; event(INIT); return init_status;
}
void XTucker_proj_Start(XTucker_proj *) {
    assert(!hw_busy); hw_busy = true; polls = 0; event(START);
}
int XTucker_proj_IsDone(XTucker_proj *) {
    assert(hw_busy);
    if (++polls == 1) return 0;
    hw_busy = false; event(DONE); return 1;
}
#define SETTER(name) void XTucker_proj_Set_##name(XTucker_proj *, u32) { assert(!hw_busy); }
SETTER(in_r) SETTER(out_q) SETTER(out_k) SETTER(out_v) SETTER(stats)
SETTER(w_q) SETTER(w_k) SETTER(w_v) SETTER(n_tok) SETTER(n_proj)
void Xil_DCacheFlush() { assert(!hw_busy); event(FLUSH_ALL); }
void Xil_DCacheFlushRange(INTPTR address, u32 length) {
    assert(!hw_busy); event(FLUSH_RANGE, address, length);
}
void Xil_DCacheInvalidateRange(INTPTR address, u32 length) {
    assert(!hw_busy); event(INVALIDATE, address, length);
}
int xil_printf(const char *, ...) { return 0; }
void tt_pl_flush_all();

enum { CAP = (TT_D * TT_NMAX + 15) & ~15, WCAP = (TT_NF + 15) & ~15 };
alignas(32) static int16_t input[CAP], oq[CAP], ok[CAP], ov[CAP], weights[3][WCAP];
alignas(32) static int32_t st[TT_STATS_CAP];
static u32 sbytes(int n) { return (2 * n * sizeof(int32_t) + 31u) & ~31u; }
static u32 bytes(int n) { return (TT_D * n * sizeof(int16_t) + 31u) & ~31u; }
static void launch(int n, int projections) {
    tt_hw_proj_start(input, oq, ok, ov, st, weights[0], weights[1], weights[2], n, projections);
}
static void check(size_t index, Kind kind, const void *p = 0, u32 n = 0) {
    assert(index < events.size());
    const Event &e = events[index];
    assert(e.kind == kind && e.address == (INTPTR)p && e.length == n);
}
static int count(Kind kind) {
    int c = 0;
    for (size_t i = 0; i < events.size(); i++) c += events[i].kind == kind;
    return c;
}

int main() {
    // A failed init must not flush anything (the PL is not ours yet).
    assert(tt_hw_init() == 7 && events.size() == 1);
    check(0, INIT);
    init_status = 0;
    assert(tt_hw_init() == 0 && init_calls == 2);
    check(1, INIT); check(2, FLUSH_ALL);  // PL-only startup cleans dirty boot data (weights, zeroed .bss buffers)
    events.clear();
    tt_hw_proj_wait();
    assert(events.empty());

    // Steady state after the global flush: only the input is flushed, weights and outputs are not.
    launch(6, 3);
    assert(hw_busy && events.size() == 2);
    check(0, FLUSH_RANGE, input, bytes(6));
    check(1, START);
    tt_hw_proj_wait();
    assert(!hw_busy && events.size() == 7);
    check(2, DONE);
    check(3, INVALIDATE, oq, bytes(6));
    check(4, INVALIDATE, ok, bytes(6));
    check(5, INVALIDATE, ov, bytes(6));
    check(6, INVALIDATE, st, sbytes(6));
    tt_hw_proj_wait();
    assert(events.size() == 7);
    for (int i = 0; i < 3; i++)                        // weights are never flushed per call
        for (size_t e = 0; e < events.size(); e++) assert(events[e].address != (INTPTR)weights[i]);

    // The CPU reading outputs between calls (clean lines) does not bring the per-call output flush back.
    events.clear();
    launch(10, 1);
    check(0, FLUSH_RANGE, input, bytes(10));
    check(1, START);
    assert(events.size() == 2);
    tt_pl_flush_all();  // must wait/invalidate before a full flush
    assert(!hw_busy && events.size() == 6);
    check(2, DONE); check(3, INVALIDATE, oq, bytes(10)); check(4, INVALIDATE, st, sbytes(10)); check(5, FLUSH_ALL);

    events.clear();
    launch(6, 1);
    launch(10, 1);  // a second start drains the previous call first
    check(0, FLUSH_RANGE, input, bytes(6)); check(1, START);
    check(2, DONE); check(3, INVALIDATE, oq, bytes(6)); check(4, INVALIDATE, st, sbytes(6));
    check(5, FLUSH_RANGE, input, bytes(10)); check(6, START);
    assert(hw_busy);
    assert(tt_hw_init() == 0 && init_calls == 2);  // re-init drains, never loses pending output
    assert(!hw_busy && events.size() == 10);
    check(7, DONE); check(8, INVALIDATE, oq, bytes(10)); check(9, INVALIDATE, st, sbytes(10));
    assert(count(FLUSH_ALL) == 0);                   // re-init of a live driver does not flush again
    printf("PASS: real driver init failure/reuse, idle wait, deferred completion and start serialization\n");
    printf("PASS: input flushed per call, weights never, outputs and stats only invalidated after PL; global flush safe\n");
}
