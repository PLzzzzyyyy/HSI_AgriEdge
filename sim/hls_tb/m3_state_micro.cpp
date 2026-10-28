#include "m3_state_micro.h"
void m3_state_micro(const int input[STATE_COUNT], unsigned seed, int output[STATE_COUNT], unsigned trace[STATE_COUNT]) {
#define INIT(I,N,T,L,H,W) STATE_TYPE(T) N=input[I]; unsigned hash_##N=0;
    STATE_FIELDS(INIT)
#undef INIT
state_ticks:
    for (int tick=0;tick<64;tick++) {
#pragma HLS PIPELINE II=1
        seed=seed*1664525u+1013904223u;
#define STEP(I,N,T,L,H,W) if ((seed >> (I%16))&1) { if (N==H) N=L; else ++N; } hash_##N=hash_##N*33u+unsigned(int(N));
        STATE_FIELDS(STEP)
#undef STEP
    }
#define OUT(I,N,T,L,H,W) output[I]=int(N); trace[I]=hash_##N;
    STATE_FIELDS(OUT)
#undef OUT
}
