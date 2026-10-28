#ifndef M3_S2_MATH_H
#define M3_S2_MATH_H
#include <cstdint>
#include <array>
#include <hls_stream.h>
#ifndef S2_NUM
#define S2_NUM 8
#endif
#ifndef S2_NATIVE
#define S2_NATIVE 0
#endif
namespace m3math {
enum Kind { NORM=0, RECIP=1, CONF=2, STOP=255 };
struct Request {
    int64_t sum;
    uint64_t square;
    uint32_t denominator;
    uint16_t tag;
    uint8_t kind;
};
struct Response {
    uint64_t value;
    int32_t mean,inv;
    uint16_t tag;
    uint8_t kind,error;
};
Response compute(Request request);
void service(hls::stream<Request> &request,hls::stream<Response> &response);
// C/CSim uses an immediate finite FIFO arithmetic model because sequential
// C cannot run two feedback-connected DATAFLOW processes concurrently. The
// synthesized path uses real request/response FIFO ready/valid handshakes.
bool try_issue(hls::stream<Request> &request,hls::stream<Response> &response,Request item);
void stop(hls::stream<Request> &request);
}
#endif
