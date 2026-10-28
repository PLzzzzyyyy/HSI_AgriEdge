#ifndef M3_S2_INTERNAL_H
#define M3_S2_INTERNAL_H
#include "s2_engine.h"
#include "s2_quant.h"
#include "s2_index.h"
#include "s2_state.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef S2_FAULT
#define S2_FAULT 0
#endif
#if defined(__SYNTHESIS__) && S2_FAULT
#error "Fault injection is C/host test only"
#endif
#if !S2_NATIVE
#include <ap_int.h>
typedef ap_int<S2_DB> Act;
typedef ap_int<S2_MB> Mid;
typedef ap_int<S2_WB> Weight;
typedef ap_int<S2_AB> Acc;
#else
typedef int32_t Act;
typedef int32_t Mid;
typedef int32_t Weight;
typedef int64_t Acc;
#endif
#ifdef __SYNTHESIS__
#include <hls_math.h>
#define S2_ASSERT(x) ((void)0)
#else
#define S2_ASSERT(x) do { if (!(x)) { fprintf(stderr,"S2_INVARIANT %s:%d: %s\n",__FILE__,__LINE__,#x); exit(90); } } while (false)
#endif
namespace s2 {
enum { WGROUP=(54+64/S2_WB-1)/(64/S2_WB), VLANES=64/S2_WB };
typedef Act Bank[6][4][S2_P*662];
struct CoreMemory {
    Act xb[6][7][378];
    Act ob[6][2][7][216];
    Weight wm12[98][48];
    uint64_t wm3[WGROUP][48*54];
    int8_t exponent[48][3];
};
struct MainMemory {
    Bank x,xn,q,kv;
    uint64_t head[6][2646]; // four int16 classes / word, shared across P
    int8_t he[24]; int32_t hb[24];
    unsigned ncls; bool loaded;
};
// Test-only aggregate compatibility; hardware tasks instantiate only their
// own memory type. No shared arrays/ping-pong dataflow copies across tasks.
struct Memory : MainMemory, CoreMemory {};
inline int64_t rnd(int64_t x,int shift) {
#pragma HLS INLINE
    S2_ASSERT(shift>=-10 && shift<=48);
    return shift>0 ? (x+(INT64_C(1)<<(shift-1)))>>shift : x*(INT64_C(1)<<(-shift));
}
inline int32_t sat(int64_t x,int bits) {
#pragma HLS INLINE
    int64_t lim=INT64_C(1)<<(bits-1);
    return int32_t(x < -lim ? -lim : x >= lim ? lim-1 : x);
}
inline Act quant(int64_t x,int shift,int bits=S2_DB) {
#pragma HLS INLINE
    return Act(sat(rnd(x,shift),bits));
}
template<int W> inline Act projection_quant(Acc x,int shift) {
#pragma HLS INLINE
#if S2_NUM==8
    return Act(projection_quant8<W>(x,shift));
#else
    // Keep the existing W16 arithmetic and fixed shift constants unchanged.
    return quant(int64_t(x),shift,S2_MB);
#endif
}
inline void pair_mul(Mid x,Weight w0,Weight w1,Acc &a,Acc &b) {
#pragma HLS INLINE
#if S2_NUM==8 && S2_PACK
#if S2_NATIVE
    int64_t p=(int64_t(w1)*262144+int64_t(w0))*int64_t(x);
    int32_t low=int32_t((p+131072)&262143)-131072;
    a=low; b=(p>>18)+(low<0);
#else
    ap_int<27> packed=(ap_int<27>(w1)<<18)+ap_int<27>(w0);
    ap_int<35> p=packed*ap_int<8>(x);
#pragma HLS BIND_OP variable=p op=mul impl=dsp
    ap_int<18> low=p.range(17,0);
    a=low; b=ap_int<18>(p>>18)+(low<0?1:0);
#endif
#else
    a=Acc(x)*Acc(w0); b=Acc(x)*Acc(w1);
#endif
}
inline int32_t get(const Bank b,int slot,int p,int t) {
#pragma HLS INLINE
    return int32_t(b[t][p&3][slot*662+(p>>2)]);
}
inline void put(Bank b,int slot,int p,int t,int32_t x) {
#pragma HLS INLINE
    b[t][p&3][slot*662+(p>>2)]=Act(x);
}
inline int32_t ob_get(const CoreMemory &m,int p,int t) {
#pragma HLS INLINE
    int a=p/378,b=(p/54)%7,c=p%54;
    return int32_t(m.ob[t][a&1][b][(a>>1)*54+c]);
}
enum Stage { N1,Q,CQ,K,CK,S,V,CV,SM,C,N2,M,R,HEAD,IO_LOAD,IO_DUMP,IO_OUT,STAGES };
enum Unit { NORMAL,PROJECT,COPY,SCORE,AUX,CONTEXT,RESIDUAL,TRANSFER };
constexpr uint32_t bit(int s) { return uint32_t(1)<<s; }
struct Slot {
    bool live,loaded,final,output,dump;
    State<7> id; State<5> layer; State<15> done;
    State<4> kv_kind;
    uint32_t attn[6][6];
    int32_t logits[32]; uint32_t cls;
};
struct Job {
    bool active,have;
    State<2> slot; State<6> stage; State<13> phase; State<14> p;
    State<11> t; State<13> a; State<10> b; State<7> c;
    State<4> h; State<11> i; State<13> dp;
    int64_t acc[6][4];
    uint64_t exp_sum,recip; int64_t maximum;
    uint32_t ex[24];
    void check_bounds() const {
        // Also run on the completion tick: terminal counters must not wrap.
        S2_ASSERT(slot>=0 && slot<S2_P && stage>=0 && stage<STAGES);
        S2_ASSERT(phase>=0 && phase<=4002 && p>=0 && p<=7938);
        S2_ASSERT(t>=0 && t<=662 && a>=0 && a<=2646);
        S2_ASSERT(b>=0 && b<=378 && c>=0 && c<=54);
        S2_ASSERT(h>=0 && h<=6 && i>=0 && i<=662 && dp>=0 && dp<=2645);
    }
    void begin(int sl,int st) { active=true;have=false;slot=sl;stage=st;phase=p=t=a=b=c=h=i=dp=0;exp_sum=0;recip=0;maximum=INT64_MIN; }
};
// Projection's mode1/2/3 overlap across tokens, two finite intermediate slots.
// Slots are depth addresses, not copies per external patch context.
struct Projection {
    Mid t1[7][7][2*54];
    Mid t2[7][2*378];
    Acc acc[7][54];
#if S2_NUM==8
    // Drain seven results per tick: retain raw dots instead of instantiating
    // 378 variable quantizers on every group boundary. This is NOT a new ob.
    Acc pending[7][54];
#else
    Act pending[7][54];
#endif
    State<4> tag1[2],tag2[2],tok1,tok2,tok3;
    State<4> next,g3; State<7> j3; State<2> flush3;
    Index54 index1,index2;
    State<4> pending_a; bool pending_valid;
    void reset() {
        tag1[0]=tag1[1]=tag2[0]=tag2[1]=-1;next=0;
        tok1=tok2=tok3=-1;index1.reset();index2.reset();g3=j3=flush3=0;pending_valid=false;
    }
    bool step(CoreMemory &mem,int pid);
};
uint32_t exponential(uint64_t d);
bool load(MainMemory &mem,const uint64_t *data);
} // namespace
#endif
