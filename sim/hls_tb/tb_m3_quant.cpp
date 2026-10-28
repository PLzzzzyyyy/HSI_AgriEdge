#include "s2_quant.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <set>
static uint32_t rng=0x841907u;
static uint32_t next() { rng^=rng<<13; rng^=rng>>17; rng^=rng<<5; return rng; }
static uint64_t checked=0;
// Independent floor((x+half)/2^e) specification, ties toward +infinity.
static int reference(int x,int e) {
    const int64_t d=INT64_C(1)<<e;
    const int64_t n=int64_t(x)+(e?d/2:0);
    int64_t q=n/d;
    if (n<0 && n%d) --q;
    return q<-128?-128:q>127?127:int(q);
}
template<int W> static void check(int x,int e) {
    const int got=int(s2::projection_quant8<W>(x,e));
    const int want=reference(x,e);
    ++checked;
    if (got!=want) {
        std::fprintf(stderr,"QUANT_FAIL w=%d x=%d e=%d got=%d want=%d\n",W,x,e,got,want);
        std::exit(1);
    }
}
template<int W> static void test() {
    const int lo=-(1<<(W-1)),hi=(1<<(W-1))-1;
    for (int e=0;e<=24;++e) {
        std::set<int> cases={lo,lo+1,hi-1,hi,-1,0,1,114688,-113792,884736,-877824};
        for (int q=-130;q<=130;++q) for (int delta=-2;delta<=2;++delta) {
            int64_t v=int64_t(q)*(INT64_C(1)<<e)-(e?(INT64_C(1)<<(e-1)):0)+delta;
            if (v>=lo && v<=hi) cases.insert(int(v));
        }
        for (int x:cases) if (x>=lo && x<=hi) check<W>(x,e);
#if S2_NATIVE
        // Full domains are stronger than the legal dot product bounds.
        for (int x=lo;x<=hi;++x) check<W>(x,e);
#else
        for (int i=0;i<20000;++i) check<W>(lo+int(next()&((1u<<W)-1)),e);
#endif
    }
    for (int i=0;i<10000;++i) {
        int sum=0;
        for (int k=0;k<(W==18?7:54);++k) sum+=int(int8_t(next()))*int(int8_t(next()));
        for (int e=0;e<=24;++e) check<W>(sum,e);
    }
}
int main() {
    test<18>();test<21>();
    std::printf("M3_QUANT_PASS checked=%llu native=%d\n",(unsigned long long)checked,S2_NATIVE);
}
