#include "s2_index.h"
#ifndef M3_INDEX_OLD
#define M3_INDEX_OLD 0
#endif
// Controlled enable/reset, fixed 64-bit words: no struct-stride arithmetic.
// Only the address generator is under test, NOT projection RAM arbitration.
void m3_index_micro(const uint8_t command[1024],uint64_t trace[1024]) {
#if M3_INDEX_OLD
    int flat=0;
#else
    s2::Index54 index;index.reset();
#endif
index_loop:
    for (int n=0;n<1024;++n) {
#pragma HLS PIPELINE II=1
        const unsigned op=command[n];
#if M3_INDEX_OLD
        if (op&2) flat=0;
        const int row=flat/54,col=flat%54;
        const uint64_t before=uint64_t(flat)|(uint64_t(row)<<9)|(uint64_t(col)<<12);
        if ((op&1) && flat<378) ++flat;
        trace[n]=before|(uint64_t(flat)<<18)|(uint64_t(flat==378)<<27);
#else
        if (op&2) index.reset();
        const uint64_t before=uint64_t(index.flat)|(uint64_t(index.row)<<9)|(uint64_t(index.col)<<12);
        if ((op&1) && index.flat<378) index.advance();
        trace[n]=before|(uint64_t(index.flat)<<18)|(uint64_t(index.flat==378)<<27);
#endif
    }
}
