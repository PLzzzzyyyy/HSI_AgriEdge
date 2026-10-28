#include "m3_math_probe.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
using namespace m3math;
static uint32_t rng=0x8616abcd;
static unsigned next() {rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
static Response reference(Request r) {
    Response y={};y.tag=r.tag;y.kind=r.kind;
    if (r.kind==NORM) {
        uint64_t var=uint64_t(2646)*r.square-uint64_t(r.sum*r.sum);
        y.mean=int32_t((r.sum*(INT64_C(1)<<(24-(S2_NUM==8?4:12))))/2646);
        float inv=(S2_NUM==8?42328.0f:10835968.0f)/std::sqrt(float(var));
        if (!(inv<=127.0f)) inv=127.0f;
        y.inv=int32_t(inv*16777216.0f);
    } else if ((r.kind==RECIP || r.kind==CONF) && r.denominator>=(1u<<24) && r.denominator<=(24u<<24)) {
        y.value=(UINT64_C(1)<<(r.kind==RECIP?47:40))/r.denominator;
        if (r.kind==CONF && y.value>65535) y.value=65535;
    } else y.error=1;
    return y;
}
static void same(Response a,Response b) {
    if (a.tag!=b.tag || a.kind!=b.kind || a.mean!=b.mean || a.inv!=b.inv || a.value!=b.value || a.error!=b.error) {
        std::printf("M3_MATH_FAIL tag=%u got=%d,%d,%llu expected=%d,%d,%llu\n",a.tag,a.mean,a.inv,
                    (unsigned long long)a.value,b.mean,b.inv,(unsigned long long)b.value);std::exit(1);
    }
}
static Request norm(unsigned mode,unsigned tag) {
    Request r={};r.tag=tag;r.kind=NORM;
    const int lo=S2_NUM==8?-128:-131072,hi=S2_NUM==8?127:131071;
    for (int i=0;i<2646;++i) {
        int x=mode==0?0:mode==1?lo:mode==2?hi:mode==3?(i&1?hi:lo):lo+int(next()%unsigned(hi-lo+1));
        r.sum+=x;r.square+=uint64_t(int64_t(x)*x);
    }
    return r;
}
int main() {
    for (unsigned i=0;i<1000;++i) {Request r=norm(i%5,i);same(compute(r),reference(r));}
    for (unsigned k=RECIP;k<=CONF;++k) for (unsigned i=0;i<100000;++i) {
        Request r={};r.kind=k;r.tag=i%65536;r.denominator=(1u<<24)+(next()%(23u<<24));
        same(compute(r),reference(r));
    }
    for (unsigned k=RECIP;k<=CONF;++k) for (unsigned d:{0u,(1u<<24)-1,(1u<<24),(24u<<24),(24u<<24)+1}) {
        Request r={};r.kind=k;r.denominator=d;same(compute(r),reference(r));
    }
    Request in[64];MathWord packed[64],out[64];unsigned meta[4];
    for (unsigned i=0;i<64;++i) {
        in[i]=norm(i%5,100+i);
        if (i%3) {in[i].kind=i%3;in[i].denominator=(1u<<24)+i*987654;}
        packed[i]=request_word(in[i]);
    }
    // End-of-stream, odd count, forced receive hold, early cutoff+drain, reuse.
    const unsigned ns[6]={0,1,7,32,32,3},cuts[6]={0,1,7,32,5,3};
    for (unsigned run=0;run<6;++run) {
        for (unsigned i=0;i<64;++i) {Response sentinel={};sentinel.tag=0xffff;out[i]=response_word(sentinel);}
        m3_math_probe(packed,out,ns[run],cuts[run],run==3?2000:0,meta);
        unsigned n=cuts[run]<ns[run]?cuts[run]:ns[run];
        if (meta[0]!=n || meta[3]!=n) {std::puts("M3_MATH_BAD_COUNT");return 1;}
        for (unsigned i=0;i<n;++i) same(word_response(out[i]),reference(in[i]));
        for (unsigned i=n;i<64;++i) if (word_response(out[i]).tag!=0xffff) {std::puts("M3_MATH_OVERRUN");return 1;}
        std::printf("M3_MATH_CALL run=%u count=%u retired=%u request_stalls=%u receive_holds=%u\n",run,ns[run],meta[0],meta[1],meta[2]);
    }
    std::printf("M3_MATH_PASS num=%d\n",S2_NUM);return 0;
}
