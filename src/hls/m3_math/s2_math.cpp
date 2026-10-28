#include "s2_math.h"
#include <cmath>
#if !S2_NATIVE
#include <ap_int.h>
#endif
#ifdef __SYNTHESIS__
#include <hls_math.h>
#endif
namespace m3math {
Response compute(Request r) {
#pragma HLS INLINE off
    Response y={};y.tag=r.tag;y.kind=r.kind;
    if (r.kind==NORM) {
        const int df=S2_NUM==8?4:12;
        uint64_t var=uint64_t(2646)*r.square-uint64_t(r.sum*r.sum);
        y.mean=int32_t((r.sum*(INT64_C(1)<<(24-df)))/2646);
#ifdef __SYNTHESIS__
        float inv=(S2_NUM==8?42328.0f:10835968.0f)/hls::sqrt(float(var));
#else
        float inv=(S2_NUM==8?42328.0f:10835968.0f)/sqrtf(float(var));
#endif
        if (!(inv<=127.0f)) inv=127.0f;
        y.inv=int32_t(inv*16777216.0f);
    } else if ((r.kind==RECIP || r.kind==CONF) && r.denominator>=(1u<<24) && r.denominator<=(24u<<24)) {
        // One exp(0)=2^24 always occurs in a legal row/head. At most24
        // positive Q24 terms, hence denominator fits29 bits, nonzero.
#if S2_NATIVE
        y.value=(UINT64_C(1)<<(r.kind==RECIP?47:40))/r.denominator;
#else
        ap_uint<48> numerator=r.kind==RECIP?(UINT64_C(1)<<47):(UINT64_C(1)<<40);
        ap_uint<29> denominator=r.denominator;
        y.value=uint64_t(numerator/denominator);
#endif
        if (r.kind==CONF && y.value>65535) y.value=65535;
    } else y.error=1;
    return y;
}
void service(hls::stream<Request> &request,hls::stream<Response> &response) {
#pragma HLS INLINE off
    while (true) {
#pragma HLS PIPELINE off
        // A blocking read in an auto-pipelined feedback server can stall
        // the entire pipeline on an empty request FIFO, including the last
        // pending response. Finish one request before reading the next.
        Request item=request.read();
        if (item.kind==STOP) return;
        response.write(compute(item));
    }
}
bool try_issue(hls::stream<Request> &request,hls::stream<Response> &response,Request item) {
#pragma HLS INLINE
#ifdef __SYNTHESIS__
    (void)response;return request.write_nb(item);
#else
    (void)request;
    if (response.size()>=2) return false;
    response.write(compute(item));return true;
#endif
}
void stop(hls::stream<Request> &request) {
#pragma HLS INLINE
#ifdef __SYNTHESIS__
    Request end={};end.kind=STOP;request.write(end);
#else
    (void)request;
#endif
}
}
