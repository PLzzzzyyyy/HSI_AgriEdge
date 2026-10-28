#ifndef TT_M3A_H
#define TT_M3A_H
// M3a int16 FULL-only baseline driver. Single owner, synchronous calls.
// Do not link/use concurrently with the M2 tt_hw_engine.cpp owner of the same IP.
#include <stddef.h>
#include <stdint.h>
#include "tt_engine_regs.h"
#include "tt_measure.h"

enum TTM3aStatus {
    TT_M3A_OK = 0,
    TT_M3A_ARGUMENT = -1,
    TT_M3A_BUFFER = -2,
    TT_M3A_NOT_READY = -3,
    TT_M3A_INIT = -4,
    TT_M3A_TIMEOUT = -5,
    TT_M3A_CONTRACT = -6,
    TT_M3A_ENGINE = -7,
    TT_M3A_RESET_REQUIRED = -8,
    TT_M3A_BUSY = -9
};

struct TTM3aJob {
    const int16_t *input;  // Packed DDR blocks, each TT_ENGINE_IN_STRIDE bytes.
    size_t input_capacity;
    void *output;
    size_t output_capacity;
    uint32_t n_patch;
    uint32_t layer_lo, layer_hi;
    uint32_t output_kind; // TT_ENGINE_OUT_CLASS / LOGITS / FEAT.
    bool dump;            // Only FEAT. Layer-major, then patch-major.
};

// Cache-isolated allocations: base aligned to 64, whole DMA span below 4 GiB.
// Returned output size includes 64-byte cache padding (CLASS odd count writes
// a complete 64-bit last word). Zero means invalid/overflowing shape.
size_t tt_m3a_output_bytes(uint32_t n_patch, uint32_t lo, uint32_t hi,
                          uint32_t output_kind, bool dump);
int tt_m3a_init(unsigned int device_id = 0);
// Exact exported weights_engine.bin, not the M2 zero-filled projection package.
int tt_m3a_load_weights(const void *package, size_t bytes, uint32_t max_polls);
int tt_m3a_run(const TTM3aJob &job, uint32_t max_polls);
uint32_t tt_m3a_last_return();
// Last successful hardware invocation only. Zero on rejected/failed/timeout.
// ABI4 cycle counter; frequency validated by tt_m3a_clock_hz(), NOT PS polls.
uint32_t tt_m3a_last_cycles();
// Fixed standalone clock contract: configured PS reference 33,333,000 Hz,
// RPLL FBDIV48 / DIV2 / PL0 DIVISOR0=4 / DIVISOR1=1. Nominal target is 200MHz.
// Vivado ACT_FREQMHZ uses floating arithmetic (199.998001); integer divider
// arithmetic gives 199,998,000 Hz. Neither is a crystal/oscilloscope measurement.
#define TT_M3A_CONFIGURED_PL_HZ 199998000u
inline uint32_t tt_m3a_decode_clock(uint32_t ref,uint32_t pll,uint32_t frac,uint32_t pl,uint32_t lock){
    return ref==33333000u&&(pll&0x07717f09u)==0x00013000u&&!(frac&0x80000000u)&&
        (pl&0x013f3f07u)==0x01010402u&&(lock&2u)?uint32_t(uint64_t(ref)*48/2/4):0;
}
uint32_t tt_m3a_clock_hz(); // read-only CRL registers on A53; zero if mismatched
// Optional main-thread service while polling PL. Disabled unless registered.
// The callback must be bounded/nonthrowing, must not access any DMA buffers or
// IP/cache owner, and must not block on work which requires this call to finish.
// It may service network/timers and queue commands for a later safe boundary.
// Mutating driver entry points reject callback reentry with BUSY, before MMIO
// or cache effects. Not an ISR/thread synchronization API. Set only when idle.
// interval counts unsuccessful polls, NOT time. nullptr/nullptr disables it.
using TTM3aWaitService = void (*)(void *context);
int tt_m3a_set_wait_service(TTM3aWaitService service, void *context,
                            uint32_t poll_interval = 256);
// max_polls is an iteration bound, NOT milliseconds. Timeout does not stop DMA:
// driver becomes unusable until external PL reset and application restart.
// Do not read/reuse/free pending buffers or call another IP owner on timeout.
#endif
