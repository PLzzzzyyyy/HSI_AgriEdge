#ifndef M3_MATH_PROBE_H
#define M3_MATH_PROBE_H
#include "s2_math.h"
#include <ap_int.h>
typedef ap_uint<256> MathWord;
// Probe-only power-of-two memory stride. Production channels carry structs;
// dynamic C struct[24-byte] indexing synthesized divide-by3 +384-bit shifts.
inline MathWord request_word(m3math::Request r) {
    MathWord w=0;w.range(63,0)=uint64_t(r.sum);w.range(127,64)=r.square;
    w.range(159,128)=r.denominator;w.range(175,160)=r.tag;w.range(183,176)=r.kind;return w;
}
inline m3math::Request word_request(MathWord w) {
#pragma HLS INLINE
    m3math::Request r={};r.sum=int64_t(ap_int<64>(w.range(63,0)));r.square=uint64_t(w.range(127,64));
    r.denominator=uint32_t(w.range(159,128));r.tag=uint16_t(w.range(175,160));r.kind=uint8_t(w.range(183,176));return r;
}
inline MathWord response_word(m3math::Response r) {
#pragma HLS INLINE
    MathWord w=0;w.range(63,0)=r.value;w.range(95,64)=uint32_t(r.mean);w.range(127,96)=uint32_t(r.inv);
    w.range(143,128)=r.tag;w.range(151,144)=r.kind;w.range(159,152)=r.error;return w;
}
inline m3math::Response word_response(MathWord w) {
    m3math::Response r={};r.value=uint64_t(w.range(63,0));r.mean=int32_t(ap_int<32>(w.range(95,64)));
    r.inv=int32_t(ap_int<32>(w.range(127,96)));r.tag=uint16_t(w.range(143,128));
    r.kind=uint8_t(w.range(151,144));r.error=uint8_t(w.range(159,152));return r;
}
void m3_math_probe(const MathWord[64],MathWord[64],unsigned,unsigned,unsigned,unsigned[4]);
#endif
