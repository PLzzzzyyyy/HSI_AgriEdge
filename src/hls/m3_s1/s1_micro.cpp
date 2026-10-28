#include "s1_micro.h"
void s1_dot(const ap_int<8> x[54], const ap_int<8> w0[54],
            const ap_int<8> w1[54], ap_int<21> y[2]) {
    ap_int<21> a = 0, b = 0;
dot54:
    for (int j = 0; j < 54; ++j) {
#pragma HLS PIPELINE II=1
        ap_int<18> lo, hi;
#if TT_S1_PACK
        s1_pair(x[j], w0[j], w1[j], lo, hi);
#else
        ap_int<16> m0 = x[j] * w0[j];
        ap_int<16> m1 = x[j] * w1[j];
#pragma HLS BIND_OP variable=m0 op=mul impl=dsp
#pragma HLS BIND_OP variable=m1 op=mul impl=dsp
        lo = m0; hi = m1;
#endif
        a += lo; b += hi;
    }
    y[0] = a; y[1] = b;
}
void s1_copy(unsigned op, unsigned ctx, const s1_act in[2646], s1_act out[2646]) {
    static s1_act ob[2][7][216];
    static s1_act blk[4][TT_S1_P * 662];
#pragma HLS ARRAY_PARTITION variable=ob complete dim=1
#pragma HLS ARRAY_PARTITION variable=ob complete dim=2
#pragma HLS ARRAY_PARTITION variable=blk complete dim=1
#pragma HLS BIND_STORAGE variable=ob type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=blk type=ram_t2p impl=bram
    if (ctx >= TT_S1_P) return;
    if (op == 0) {
load_ob:
        for (int p = 0; p < 2646; ++p) {
#pragma HLS PIPELINE II=1
            int a = p / 378, b = (p / 54) % 7, c = p % 54;
            ob[a & 1][b][(a >> 1) * 54 + c] = in[p];
        }
    } else if (op == 1) {
copy2:
        for (int p = 0; p < 2646; p += 2) {
#pragma HLS PIPELINE II=1
            // Even 54/378 ensure that a pair cannot cross an ob bank.
            int a = p / 378, b = (p / 54) % 7, c = p % 54;
            s1_act v0 = ob[a & 1][b][(a >> 1) * 54 + c];
            s1_act v1 = ob[a & 1][b][(a >> 1) * 54 + c + 1];
            for (int h = 0; h < 4; ++h) {
#pragma HLS UNROLL
                if (h == p % 4) blk[h][ctx * 662 + p / 4] = v0;
                if (h == (p + 1) % 4) blk[h][ctx * 662 + (p + 1) / 4] = v1;
            }
        }
    } else if (op == 2) {
read_blk:
        for (int p = 0; p < 2646; ++p) {
#pragma HLS PIPELINE II=1
            out[p] = blk[p % 4][ctx * 662 + p / 4];
        }
    }
}
