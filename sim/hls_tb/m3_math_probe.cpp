#include "m3_math_probe.h"
#if !S2_NATIVE
#include <ap_int.h>
#endif
using namespace m3math;
static void client(const MathWord input[64],MathWord output[64],unsigned count,unsigned cutoff,
                   unsigned hold,unsigned stats[4],hls::stream<Request> &rq,hls::stream<Response> &rs) {
#pragma HLS INLINE off
    unsigned tick=0,full=0,held=0;
    unsigned limit=count<cutoff?count:cutoff;if (limit>64)limit=64;
#if S2_NATIVE
    unsigned sent=0,retired=0,n=limit;
#else
    ap_uint<7> sent=0,retired=0,n=limit;
#endif
    while (retired<n) {
#pragma HLS PIPELINE II=1
        if (sent<n) {
            if (try_issue(rq,rs,word_request(input[sent]))) ++sent;
            else ++full;
        }
        if (tick++>=hold) {
            Response r;
            if (rs.read_nb(r)) output[retired++]=response_word(r);
        } else ++held;
    }
    // Stop only after every accepted request has returned; no stale FIFO
    // response is allowed to survive a later top-level invocation.
    stop(rq);stats[0]=retired;stats[1]=full;stats[2]=held;stats[3]=sent;
}
void m3_math_probe(const MathWord input[64],MathWord output[64],unsigned count,unsigned cutoff,
                   unsigned hold,unsigned stats[4]) {
    hls::stream<Request> rq("math_request");hls::stream<Response> rs("math_response");
#pragma HLS STREAM variable=rq depth=2
#pragma HLS STREAM variable=rs depth=2
#ifdef __SYNTHESIS__
#pragma HLS DATAFLOW
    client(input,output,count,cutoff,hold,stats,rq,rs);
    service(rq,rs);
#else
    client(input,output,count,cutoff,hold,stats,rq,rs);
#endif
}
