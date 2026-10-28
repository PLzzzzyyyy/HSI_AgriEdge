#include "m3a_bench.h"
#include "xil_cache.h"
#include <stdio.h>

int main() {
    Xil_ICacheEnable();
    Xil_DCacheEnable();
    setvbuf(stdout, nullptr, _IONBF, 0);
    const bool ok = m3a_benchmark();
    printf("M3A_APP_END %s\n", ok ? "PASS" : "FAIL");
    // A timed-out DMA may still be active: no exit handler/cache disable/retry.
    puts("HALTED: save UART log. Reprogram PL + restart App before another run.");
    for (;;) { }
}
