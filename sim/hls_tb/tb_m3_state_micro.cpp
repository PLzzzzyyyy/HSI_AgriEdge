#include "m3_state_micro.h"
#include <cstdio>
#include <cstdlib>
static void check(bool ok) {if (!ok) {std::puts("M3_STATE_FAIL");std::exit(1);}}
int main() {
    unsigned checks=0;
#define RANGE(I,N,T,L,H,W) { T x; for (int v=L;v<=H;v++) {x=v;check(int(x)==v);checks++;} x=H-1;++x;check(int(x)==H); x=L;check(int(x)==L); }
    STATE_FIELDS(RANGE)
#undef RANGE
    int low[STATE_COUNT],high[STATE_COUNT];
#define LIMIT(I,N,T,L,H,W) low[I]=L;high[I]=H;
    STATE_FIELDS(LIMIT)
#undef LIMIT
    unsigned random=923451u;
    for (int run=0;run<128;run++) {
        int in[STATE_COUNT],out[STATE_COUNT],ref[STATE_COUNT]; unsigned trace[STATE_COUNT],hash[STATE_COUNT]={};
        for (int j=0;j<STATE_COUNT;j++) {
            random=random*1664525u+1013904223u;
            in[j]=run%3==0?high[j]-1:run%3==1?low[j]:low[j]+int(random%unsigned(high[j]-low[j]+1));
            ref[j]=in[j];
        }
        unsigned seed=random;
        m3_state_micro(in,seed,out,trace);
        for (int tick=0;tick<64;tick++) {
            seed=seed*1664525u+1013904223u;
            for (int j=0;j<STATE_COUNT;j++) {
                if ((seed>>(j%16))&1) ref[j]=ref[j]==high[j]?low[j]:ref[j]+1;
                hash[j]=hash[j]*33u+unsigned(ref[j]);
            }
        }
        for (int j=0;j<STATE_COUNT;j++) {check(out[j]==ref[j] && trace[j]==hash[j]);checks++;}
    }
    std::printf("M3_STATE_MICRO_PASS checks=%u ticks=8192 fields=%d\n",checks,STATE_COUNT);
}
