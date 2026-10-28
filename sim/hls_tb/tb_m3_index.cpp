#include "s2_index.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static unsigned checks=0;
static void check(const s2::Index54 &index, unsigned flat) {
    ++checks;
    if (unsigned(index.flat)!=flat || unsigned(index.row)!=flat/54 ||
        unsigned(index.col)!=flat%54) {
        fprintf(stderr,"INDEX_MISMATCH flat=%u got=%u/%u/%u\n",flat,
                unsigned(index.flat),unsigned(index.row),unsigned(index.col));
        exit(1);
    }
}
int main() {
    s2::Index54 index;
    uint32_t rng=0x8a3754u;
    // Every active position and terminal state, with deterministic idle gaps.
    // Repeated reset models reuse; every possible prefix also gets aborted.
    for (unsigned trial=0;trial<400;++trial) {
        index.reset();check(index,0);
        unsigned length=trial<379?trial:378;
        for (unsigned flat=0;flat<length;++flat) {
            rng=rng*1664525u+1013904223u;
            for (unsigned idle=0;idle<(rng&7u);++idle) check(index,flat);
            bool done=index.advance();
            check(index,flat+1);
            if (done!=(flat+1==378)) return 2;
        }
        check(index,length);
        if (length==378) for (int idle=0;idle<64;++idle) check(index,378);
    }
    printf("M3_INDEX_PASS checks=%u\n",checks);
    return 0;
}
