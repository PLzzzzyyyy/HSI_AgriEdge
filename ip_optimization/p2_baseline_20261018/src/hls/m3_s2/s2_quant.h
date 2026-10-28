#ifndef M3_S2_QUANT_H
#define M3_S2_QUANT_H
#include <cassert>
#ifndef S2_NATIVE
#define S2_NATIVE 0
#endif
#if !S2_NATIVE
#include <ap_int.h>
#endif
namespace s2 {
// W8 only: package load checks exponent in [0,24]; DF=MF=4.
// Seven products fit signed18, 54 products fit signed21. Not LN/head.
template<int W>
#if S2_NATIVE
inline int projection_quant8(int x,int exponent) {
#else
inline ap_int<8> projection_quant8(ap_int<W> x,int exponent) {
#endif
#pragma HLS INLINE
    static_assert(W==18 || W==21,"proven W8 dot-product widths only");
#ifndef __SYNTHESIS__
    assert(exponent>=0 && exponent<=24);
#endif
    // One W+1-bit arithmetic barrel shift, preserving a guard bit.
    // floor(x/2^e) + guard = floor((x+2^(e-1))/2^e), including negative
    // half-LSB ties. e=0 has zero guard; e>=W produces zero after rounding.
#if S2_NATIVE
    assert(x>=-(1<<(W-1)) && x<(1<<(W-1)));
    int guarded=(x*2)>>exponent;
    int q=(guarded>>1)+(guarded&1);
    return q<-128?-128:q>127?127:q;
#else
    ap_uint<5> e=exponent;
    ap_int<W+1> doubled=ap_int<W+1>(x)<<1;
    ap_int<W+1> guarded=doubled>>e;
    ap_int<W+1> q=(guarded>>1)+ap_uint<1>(guarded[0]);
    return q<-128?ap_int<8>(-128):q>127?ap_int<8>(127):ap_int<8>(q);
#endif
}
}
#endif
