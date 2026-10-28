#include "s2_internal.h"
#include "s2_quant.h"
#ifndef M3_QUANT_OLD
#define M3_QUANT_OLD 0
#endif
void m3_quant_micro(ap_int<18> x7[14],ap_int<21> x54[7],
                    int e1,int e2,int e3,ap_int<8> out[21]) {
#pragma HLS PIPELINE II=1
#pragma HLS ARRAY_PARTITION variable=x7 complete
#pragma HLS ARRAY_PARTITION variable=x54 complete
#pragma HLS ARRAY_PARTITION variable=out complete
    for (int i=0;i<14;++i) {
#pragma HLS UNROLL
        int e=i<7?e1:e2;
#if M3_QUANT_OLD
        out[i]=s2::quant(int64_t(x7[i]),e);
#else
        out[i]=s2::projection_quant8<18>(x7[i],e);
#endif
    }
    for (int i=0;i<7;++i) {
#pragma HLS UNROLL
#if M3_QUANT_OLD
        out[14+i]=s2::quant(int64_t(x54[i]),e3);
#else
        out[14+i]=s2::projection_quant8<21>(x54[i],e3);
#endif
    }
}
