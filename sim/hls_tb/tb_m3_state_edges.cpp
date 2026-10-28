// Exercise real worker transitions with extreme legal numeric values.
// Including the engine translation unit exposes its internal static workers.
#include "../../src/hls/m3_s2/s2_engine.cpp"
#include <cstdio>
#include <vector>
static s2::Memory memory;
static s2::Projection projection;
static void check(bool x) { S2_ASSERT(x); }
int main() {
    using namespace s2;
    const int A=1<<(S2_DB-1);
    unsigned checks=0;
    // Dispatch reads entry state and grants only one idle unit. A running
    // normalizer's Job::i must not act as the math response counter.
    {
        Slot slots[S2_P]={};Job jobs[8]={};uint32_t meta[S2_META_WORDS]={};
        for(int u=0;u<8;u++) jobs[u].active=false;
        for(int sl=0;sl<S2_P;sl++) slots[sl].live=false;
        slots[0].live=slots[0].loaded=true;slots[0].final=slots[0].output=slots[0].dump=false;
        slots[0].done=0;slots[0].id=0;
        Dispatch d=select_dispatch(jobs,slots,-1,-1,0,1,0,1,meta);
        check(d.slot==0 && d.stage==N1 && !jobs[NORMAL].active);
        jobs[NORMAL].begin(0,N1);jobs[NORMAL].phase=1;jobs[NORMAL].i=6;
        d=select_dispatch(jobs,slots,0,-1,0,1,0,1,meta);
        check(d.slot==-1);
        MathOffer math={};CoreOffer core={};int32_t mean[6]={},inv[6]={};
        int64_t slot_sum[6]={};uint64_t slot_square[6]={};
        check(!norm_step(memory,slots[0],jobs[NORMAL],math,core,5,mean,inv,slot_sum,slot_square));
        check(jobs[NORMAL].phase==1);
        jobs[NORMAL].i=0;
        check(!norm_step(memory,slots[0],jobs[NORMAL],math,core,6,mean,inv,slot_sum,slot_square));
        check(jobs[NORMAL].phase==2 && jobs[NORMAL].i==0);
        jobs[NORMAL].active=false;slots[0].done=bit(N1);
        d=select_dispatch(jobs,slots,0,-1,0,1,0,1,meta);
        check(d.slot==0 && d.stage==Q && !jobs[PROJECT].active);
        d=select_dispatch(jobs,slots,0,0,0,1,0,1,meta);check(d.slot==-1);
        checks+=8;
    }
    for (int sign=0;sign<2;sign++) {
        const int x=sign?A-1:-A;
        Slot s={}; Job j={}; MathOffer offer={}; int64_t head_sum[24],ctx_sum[24];
        int64_t slot_sum[6]={},scores[6][6];uint64_t slot_square[6]={};
        for (int t=0;t<6;t++) for (int p=0;p<2646;p++) {
            put(memory.x,0,p,t,x);put(memory.xn,0,p,t,x);
            put(memory.q,0,p,t,x);put(memory.kv,0,p,t,-A);
        }
        // HEAD uses int16 weights even in W8. Test r=1 and extreme bias.
        const uint64_t weights=UINT64_C(0x8000800080008000);
        memory.ncls=24;
        for (int c=0;c<24;c++) {memory.he[c]=17-S2_DF;memory.hb[c]=sign?INT32_MAX:INT32_MIN;}
        for (int g=0;g<6;g++) for (int p=0;p<2646;p++) memory.head[g][p]=weights;
        j.begin(0,HEAD);check(j.maximum==INT64_MIN);
        for (int c=0;c<24;c++) head_sum[c]=INT64_MIN+c; // p=0 must overwrite
        for (int p=0;p<2646;p++) {check(!head_step(memory,s,j,offer,head_sum));j.check_bounds();}
        const int64_t dot=int64_t(2646)*(-32768)*x;
        for (int c=0;c<24;c++) check(head_sum[c]==dot);
        for (int c=0;c<24;c++) {check(!head_step(memory,s,j,offer,head_sum));j.check_bounds();}
        const int64_t logit=((dot+1)>>1)+memory.hb[0];
        check(j.maximum==logit);
        for (int c=0;c<24;c++) check(head_sum[c]==logit && s.logits[c]==int32_t(logit));
        // Full SCORE including the two-lane tail.
        s.kv_kind=K;j.begin(0,S);
        for (int tick=0;tick<6*662;tick++) {check(score_step(memory,s,j,scores)==(tick==6*662-1));j.check_bounds();}
        for (int n=0;n<6;n++) for (int c=0;c<6;c++) check(scores[n][c]==int64_t(2646)*x*(-A));
        // Conservative context upper bound: each individual attention at 2^24.
        // It deliberately does not rely on the approximate row sum being 1.
        s.kv_kind=V;
        for (int t=0;t<6;t++) {slot_sum[t]=0;slot_square[t]=0;for(int c=0;c<6;c++) s.attn[t][c]=1u<<24;}
        j.begin(0,C);
        for (int tick=0;tick<4002;tick++) {check(ctx_step(memory,s,j,ctx_sum,slot_sum,slot_square)==(tick==4001));j.check_bounds();}
        check(j.phase==4002 && j.t==6 && !j.have);
        for (int t=0;t<6;t++) {const int y=sign?-1:-A;check(slot_sum[t]==int64_t(2646)*y);check(slot_square[t]==uint64_t(2646)*int64_t(y)*y);}
        // RAW and DUMP terminal p7938/a2646, last context ID63 address.
        std::vector<uint64_t> raw(64*7938),dump(64*7938);
        uint32_t lane=uint32_t(sign?INT32_MAX:INT32_MIN);
        for (int i=0;i<7938;i++) raw[63*7938+i]=uint64_t(lane)|(uint64_t(lane)<<32);
        s={};s.id=63;j.begin(0,IO_LOAD);
        for(int t=0;t<6;t++) {slot_sum[t]=0;slot_square[t]=0;}
        for (int tick=0;tick<7938;tick++) {check(io_step(memory,s,j,raw.data(),0,0,0,64,S2_RAW,0,slot_sum,slot_square)==(tick==7937));j.check_bounds();}
        check(j.p==7938 && j.a==2646);
        j.begin(0,IO_DUMP);
        for (int tick=0;tick<7938;tick++) {check(io_step(memory,s,j,0,0,0,dump.data(),64,S2_FEAT,0,slot_sum,slot_square)==(tick==7937));j.check_bounds();}
        check(j.p==7938 && j.a==2646);
        const uint32_t saturated=uint32_t(sign?A-1:-A);
        for (int i=0;i<7938;i++) check(dump[63*7938+i]==(uint64_t(saturated)|(uint64_t(saturated)<<32)));
        checks+=2646+24+6*662+4002+2*7938;
    }
    // Nonuniform SCORE rows/columns and CONTEXT rotating addresses. Uniform
    // extrema alone cannot detect token-bank aliasing or a 441/tail permutation.
    for(int sl=0;sl<S2_P;sl++) {
        Slot s={};Job j={};int64_t ctx_sum[24];
        int64_t slot_sum[6]={},scores[6][6];uint64_t slot_square[6]={};
        int64_t reference[6][6]={};
        for(int t=0;t<6;t++) for(int p=0;p<2646;p++) {
            put(memory.q,sl,p,t,((p+3*t+sl)%17)-8);
            put(memory.kv,sl,p,t,((2*p+5*t+sl)%19)-9);
        }
        for(int n=0;n<6;n++) for(int c=0;c<6;c++) {
            scores[n][c]=INT64_MIN+n*6+c;
            for(int p=0;p<2646;p++) reference[n][c]+=int64_t(get(memory.q,sl,p,n))*get(memory.kv,sl,p,c);
        }
        s.kv_kind=K;j.begin(sl,S);
        for(int tick=0;tick<6*662;tick++) check(score_step(memory,s,j,scores)==(tick==6*662-1));
        for(int n=0;n<6;n++) for(int c=0;c<6;c++) check(scores[n][c]==reference[n][c]);
        // Zero attention makes CONTEXT output exactly xn, including all tails.
        // Poison x (and other slots) so omissions and cross-slot stores fail.
        for(int qsl=0;qsl<S2_P;qsl++) for(int t=0;t<6;t++) for(int p=0;p<2646;p++) {
            put(memory.x,qsl,p,t,99);
            put(memory.xn,qsl,p,t,((p+7*t+3*qsl)%101)-50);
        }
        s.kv_kind=V;j.begin(sl,C);
        for(int tick=0;tick<4002;tick++) {check(ctx_step(memory,s,j,ctx_sum,slot_sum,slot_square)==(tick==4001));j.check_bounds();}
        for(int t=0;t<6;t++) {
            int64_t total=0;uint64_t square=0;
            for(int p=0;p<2646;p++) {
                const int v=get(memory.xn,sl,p,t);total+=v;square+=uint64_t(int64_t(v)*v);
                check(get(memory.x,sl,p,t)==v);
                for(int other=0;other<S2_P;other++) if(other!=sl) check(get(memory.x,other,p,t)==99);
            }
            check(slot_sum[t]==total && slot_square[t]==square);
        }
        checks+=6*662+4002+6*2646;
    }
    // Completion publishes a tag this tick; the consumer claims it next tick.
    // Exercise both intermediate-slot control-register boundaries.
    memory=Memory{};
    for(int p=0;p<48;p++) for(int k=0;k<3;k++) memory.exponent[p][k]=S2_NUM==16?14:0;
    projection.reset();projection.next=6;projection.tok1=0;projection.tag1[0]=-2;
    for(int i=0;i<377;i++) projection.index1.advance();
    check(!projection.step(memory,0));
    check(projection.tok1==-1 && projection.tok2==-1 && projection.tag1[0]==0);
    check(!projection.step(memory,0));check(projection.tok2==0 && projection.index2.flat==0);
    for(int i=0;i<377;i++) projection.index2.advance();
    check(!projection.step(memory,0));
    check(projection.tok2==-1 && projection.tok3==-1 && projection.tag2[0]==0);
    check(!projection.step(memory,0));check(projection.tok3==0 && projection.j3==0);
    checks+=8;
    // Actual projection lifecycle with zero RAM, including all negative tags.
    memory=Memory{}; for(int p=0;p<48;p++) for(int k=0;k<3;k++) memory.exponent[p][k]=S2_NUM==16?14:0; projection.reset();unsigned seen=0;bool done=false;
    for (int tick=0;tick<10000 && !done;tick++) {
        done=projection.step(memory,0);
        for(int b=0;b<2;b++) {int t1=int(projection.tag1[b]),t2=int(projection.tag2[b]);if(t1<0) seen|=1u<<(-t1);if(t2<0) seen|=1u<<(-t2);}
        checks++;
    }
    check(done && (seen&14)==14 && projection.next==6 && projection.g3==7 && projection.j3==54);
    std::printf("M3_STATE_EDGES_PASS num=%d native=%d checks=%u\n",S2_NUM,S2_NATIVE,checks);
}
