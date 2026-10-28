#ifndef M3_S1_MICRO_H
#define M3_S1_MICRO_H
#include <ap_int.h>
#ifndef TT_S1_BITS
#define TT_S1_BITS 8
#endif
#ifndef TT_S1_P
#define TT_S1_P 2
#endif
#ifndef TT_S1_PACK
#define TT_S1_PACK 1
#endif
static_assert(TT_S1_BITS == 8 || TT_S1_BITS == 18, "activation width");
static_assert(TT_S1_P == 1 || TT_S1_P == 2, "context count");
typedef ap_int<TT_S1_BITS> s1_act;
// One shared activation, two weights; unpack BEFORE accumulation.
inline void s1_pair(ap_int<8> x, ap_int<8> w0, ap_int<8> w1,
                    ap_int<18>& lo, ap_int<18>& hi) {
#pragma HLS INLINE
    ap_int<27> a = (ap_int<27>(w1) << 18) + ap_int<27>(w0);
    ap_int<35> product = a * x;
#pragma HLS BIND_OP variable=product op=mul impl=dsp
    lo = product.range(17, 0);
    hi = ap_int<18>(product >> 18) + (lo < 0 ? 1 : 0);
}
void s1_dot(const ap_int<8> x[54], const ap_int<8> w0[54],
            const ap_int<8> w1[54], ap_int<21> y[2]);
// Single-token representative of six token-bank groups. Caller owns the ob.
// op0 fills the SINGLE ob; op1 copies into a context; op2 reads a context.
void s1_copy(unsigned op, unsigned ctx, const s1_act in[2646], s1_act out[2646]);
#endif
