#ifndef M3_S2_INDEX_H
#define M3_S2_INDEX_H
#include "s2_engine.h"
#include <assert.h>
#if !S2_NATIVE
#include <ap_int.h>
#endif
namespace s2 {
// One 7x54 traversal. Active flat=0..377, row=0..6, col=0..53.
// After the last advance retain flat=378, row=7, col=0 until reset.
// Advance ONLY when the corresponding projection stage actually executes.
// No arithmetic narrowing of activations, tokens or the other workers here.
struct Index54 {
#if S2_NATIVE
    unsigned flat,row,col;
#else
    ap_uint<9> flat; // includes terminal 378, not merely the last address
    ap_uint<3> row;  // includes terminal 7
    ap_uint<6> col;  // 0..53; carry is detected before increment
#endif
    void reset() {
#pragma HLS INLINE
        flat=0;row=0;col=0;
    }
    bool advance() {
#pragma HLS INLINE
#ifndef __SYNTHESIS__
        assert(unsigned(flat)<378);
#endif
        flat=flat+1;
        if (col==53) { col=0;row=row+1; }
        else col=col+1;
        return flat==378;
    }
};
}
#endif
