#include "s2_internal.h"
#include "s2_worker.h"
#include "../m3_math/s2_math.h"
namespace s2 {
typedef hls::stream<m3math::Request> MathRequests;
typedef hls::stream<m3math::Response> MathResponses;
struct MathOffer {m3math::Request item;bool valid;};
static const unsigned deps[14]={0,bit(N1),bit(Q),bit(CQ),bit(K),bit(CK),bit(CK),bit(V)|bit(S),bit(S),bit(CV)|bit(SM),bit(C),bit(N2),bit(M),0};
static const int unit_for[14]={NORMAL,PROJECT,COPY,PROJECT,COPY,SCORE,PROJECT,COPY,AUX,CONTEXT,NORMAL,PROJECT,RESIDUAL,AUX};
// x,xn,q,kv,xb,ob: per-bank peak. Contexts occupy depth, not more ports.
static const unsigned ports[STAGES][6]={
    {1,1,0,0,1,0},{0,0,0,0,1,1},{0,0,1,0,0,2},
    {0,0,0,0,1,1},{0,0,0,1,0,2},{0,0,1,1,0,0},
    {0,0,0,0,1,1},{0,0,0,1,0,2},{0,0,0,0,0,0},
    {1,1,0,1,0,0},{1,1,0,0,1,0},{0,0,0,0,1,1},
    {1,1,0,0,0,1},{1,0,0,0,0,0},{1,0,0,0,0,0},
    {1,0,0,0,0,0},{0,0,0,0,0,0}};
struct Dispatch {int slot,stage;};
static Dispatch select_dispatch(const Job jobs[8],const Slot slots[S2_P],
        int xb_owner,int ob_owner,unsigned round,unsigned accepted,
        unsigned retired,unsigned count,uint32_t meta[S2_META_WORDS]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=ports complete dim=0
    // One grant from the entry state. Never complete and reinitialize the
    // same Job in one iteration, or cascade 14 stage starts through its i.
    unsigned used[6]={};
#pragma HLS ARRAY_PARTITION variable=used complete
    for(int b=0;b<6;b++) for(int u=0;u<8;u++) {
#pragma HLS UNROLL
        if(jobs[u].active) used[b]+=ports[jobs[u].stage][b];
    }
    Dispatch grant={-1,-1};
    unsigned ob_wait=0,xb_wait=0,kv_wait=0,port_wait=0;
    for(int turn=0;turn<S2_P;turn++) {
#pragma HLS UNROLL
        const int sl=(turn+round)%S2_P;const Slot &s=slots[sl];
        for(int st=0;st<=HEAD;st++) {
#pragma HLS UNROLL
            if(!s.live || !s.loaded || s.dump || s.output ||
               (s.final?st!=HEAD:st==HEAD) || (s.done&bit(st))) continue;
            unsigned need=deps[st];
#if S2_FAULT==2
            if(st==CV) need=bit(V);
#endif
            if(st==CV && (s.done&bit(V)) && !(s.done&bit(S))) kv_wait++;
            const int u=unit_for[st];
            if((s.done&need)!=need || jobs[u].active) continue;
            bool available=true;
            for(int b=0;b<6;b++) {
#pragma HLS UNROLL
                if(used[b]+ports[st][b]>2) available=false;
            }
            if(!available) {port_wait++;continue;}
            if(u==NORMAL && xb_owner>=0) {xb_wait++;continue;}
            if(u==PROJECT && ob_owner>=0) {ob_wait++;continue;}
            if(grant.slot<0) {grant.slot=sl;grant.stage=st;}
        }
    }
    if(grant.slot<0 && !jobs[TRANSFER].active) {
        for(int c=0;c<S2_P;c++) if(slots[c].live && slots[c].output && slots[c].id==retired) {grant.slot=c;grant.stage=IO_OUT;}
        for(int c=0;c<S2_P;c++) if(grant.slot<0 && slots[c].live && slots[c].dump) {grant.slot=c;grant.stage=IO_DUMP;}
        for(int c=0;c<S2_P;c++) if(grant.slot<0 && !slots[c].live && accepted<count) {grant.slot=c;grant.stage=IO_LOAD;}
        if(grant.slot>=0) for(int b=0;b<6;b++) if(used[b]+ports[grant.stage][b]>2) {grant.slot=-1;break;}
    }
    meta[6]+=ob_wait;meta[7]+=xb_wait;meta[10]+=kv_wait;meta[11]+=port_wait;
    return grant;
}
static bool pause(unsigned &rng) {
#ifdef __SYNTHESIS__
    (void)rng;return false;
#else
    if (!rng) return false;
    rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;
    return (rng&7)==0;
#endif
}
static bool reserve_math(Job &j,unsigned kind,unsigned index,int64_t sum,uint64_t square,
                         uint64_t denominator,MathOffer &offer) {
#pragma HLS INLINE
    if (offer.valid) return false;
    S2_ASSERT(kind==m3math::NORM || (denominator>=(UINT64_C(1)<<24) && denominator<=(UINT64_C(24)<<24)));
    m3math::Request r={};r.kind=kind;r.tag=unsigned(j.slot)|(unsigned(j.stage)<<1)|(index<<6);
    r.sum=sum;r.square=square;r.denominator=uint32_t(denominator);
    offer.item=r;offer.valid=true;return true;
}
static bool reserve_core(const Job &j,int kind,CoreOffer &offer) {
#pragma HLS INLINE
    if(offer.valid || !offer.ready) return false;
    CoreRequest r={};r.kind=kind;r.slot=j.slot;r.stage=j.stage;
    r.a=j.a;r.b=j.b;r.c=int(j.i)+int(j.c);
    offer.item=r;offer.valid=true;return true;
}
static bool consumer_data(Job &j,CoreOffer &offer,CoreResponse &y,bool &valid,bool &released) {
#pragma HLS INLINE
    released=false;
    if(j.phase==1) {released=reserve_core(j,CORE_RELEASE,offer);return false;}
    if(!j.have) {if(reserve_core(j,CORE_READ,offer)) j.have=true;return false;}
    if(!valid) return false;
    S2_ASSERT(y.kind==CORE_READ && y.slot==j.slot && y.stage==j.stage);
    valid=false;j.have=false;return true;
}
static bool norm_step(MainMemory &m,Slot &s,Job &j,MathOffer &offer,CoreOffer &core,
                      unsigned norm_received,const int32_t mean[6],const int32_t inv[6],
                      const int64_t slot_sum[6],const uint64_t slot_square[6]) {
#pragma HLS INLINE
    if (j.phase==0) {
        const int t=j.t;
        if (reserve_math(j,m3math::NORM,t,slot_sum[t],slot_square[t],0,offer) && ++j.t==6) j.phase=1;
        return false;
    }
    if (j.phase==1) {
        if (norm_received==6) j.phase=2; // previous-tick committed responses
        return false;
    }
    if(!reserve_core(j,CORE_XB,core)) return false;
    core.item.c=j.b;
    for (int t=0;t<6;t++) {
#pragma HLS UNROLL
        int64_t d=int64_t(get(m.x,j.slot,j.p,t))*(INT64_C(1)<<(24-S2_DF))-mean[t];
        Act v=quant(d*inv[t],48-S2_DF);
        put(m.xn,j.slot,j.p,t,int32_t(v));core.item.value[t]=v;
    }
    if (++j.b==378) {j.b=0;j.a++;}
    return ++j.p==2646;
}
static bool copy_step(MainMemory &m,Job &j,CoreOffer &offer,CoreResponse &y,bool &valid) {
#pragma HLS INLINE
    bool released=false;if(!consumer_data(j,offer,y,valid,released)) return released;
    for (int t=0;t<6;t++) {
#pragma HLS UNROLL
        Act v0=y.value[t][0],v1=y.value[t][1];
        for (int h=0;h<4;h++) {
#pragma HLS UNROLL
            if (h==j.h || h==j.h+1) {
                const Act v=h==j.h?v0:v1;
                if (j.stage==CQ) m.q[t][h][j.slot*662+j.t]=v;
                else m.kv[t][h][j.slot*662+j.t]=v;
            }
        }
    }
    if (j.h==2) {j.h=0;j.t++;} else j.h=2;
    j.c+=2;
    if (j.c==54) {j.c=0;if (++j.b==7) {j.b=0;if (j.a&1) j.i+=54;j.a++;}}
    j.p+=2;if(j.p==2646) j.phase=1;return false;
}
static bool score_step(MainMemory &m,Slot &s,Job &j,int64_t scores[6][6]) {
#pragma HLS INLINE
    S2_ASSERT(s.kv_kind==K);
    for (int n=0;n<6;n++) {
#pragma HLS UNROLL
        int64_t a=0;
        for (int h=0;h<4;h++) {
#pragma HLS UNROLL
            // Request a pipeline boundary before the old single-cycle fused MAC.
            // Verify the generated operator and mapped timing; not a PASS claim.
            int64_t product=int64_t(m.q[n][h][j.slot*662+j.i])*int64_t(m.kv[j.c][h][j.slot*662+j.i]);
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=2
            if (j.i<661 || h<2) a+=product;
        }
        j.acc[n][0]=(j.i==0?0:j.acc[n][0])+a;
    }
    if (++j.i==662) {
        for (int n=0;n<6;n++) {
#pragma HLS UNROLL
            scores[n][j.c]=j.acc[n][0];
        }
        j.i=0;return ++j.c==6;
    }
    return false;
}
static bool softmax_step(Slot &s,Job &j,MathOffer &offer,const int64_t scores[6][6]) {
#pragma HLS INLINE
    if (j.phase==0) {
        int64_t v=scores[j.t][j.c];if (v>j.maximum) j.maximum=v;
        if (++j.c==6) {j.c=0;j.phase=1;}
    } else if (j.phase==1) {
        uint64_t d=uint64_t(j.maximum-scores[j.t][j.c])<<(24-2*S2_DF);
        j.ex[j.c]=exponential(d);j.exp_sum+=j.ex[j.c];
        if (++j.c==6) {j.c=0;j.phase=2;}
    } else if (j.phase==2) {
        if (reserve_math(j,m3math::RECIP,j.t,0,0,j.exp_sum,offer)) {j.have=false;j.phase=4;}
    } else if (j.phase==4) {
        if (j.have) {j.have=false;j.phase=3;}
    } else {
        s.attn[j.t][j.c]=uint32_t((uint64_t(j.ex[j.c])*j.recip+(UINT64_C(1)<<22))>>23);
        if (++j.c==6) {
            if (++j.t==6) return true;
            j.c=0;j.phase=0;j.maximum=INT64_MIN;j.exp_sum=0;
        }
    }
    return false;
}
static bool ctx_step(MainMemory &m,Slot &s,Job &j,int64_t sum[24],
                     int64_t slot_sum[6],uint64_t slot_square[6]) {
#pragma HLS INLINE
    S2_ASSERT(s.kv_kind==V);
    if (j.t<6) {
        int32_t vb[4];
#pragma HLS ARRAY_PARTITION variable=vb complete
        const int rh=j.p&3,base=j.p>>2;
        for (int b=0;b<4;b++) {
#pragma HLS UNROLL
            int at=base+(b<rh);if (at>661) at=661;
            vb[b]=int32_t(m.kv[j.t][b][j.slot*662+at]);
        }
        for (int n=0;n<6;n++) for (int h=0;h<4;h++) {
#pragma HLS UNROLL
            j.acc[n][h]=(j.c==0?(INT64_C(1)<<23):j.acc[n][h])+int64_t(s.attn[n][j.c])*vb[(h+rh)&3];
        }
    }
    if (j.have) {
        const int rh=j.dp&3,base=j.dp>>2;
        int32_t value[4];
#pragma HLS ARRAY_PARTITION variable=value complete
        int64_t d1=0;uint64_t d2=0;
        for (int b=0;b<4;b++) {
#pragma HLS UNROLL
            int h=(b-rh)&3,at=base+(b<rh);if (at>661) at=661;
            int32_t cq=sat(sum[j.c*4+h],S2_DB);
            value[b]=sat(int64_t(m.xn[j.h][b][j.slot*662+at])+cq,S2_DB);
            if (j.b<110 || h==0) {
                m.x[j.h][b][j.slot*662+at]=Act(value[b]);
                d1+=value[b];d2+=uint64_t(int64_t(value[b])*value[b]);
            }
        }
        slot_sum[j.h]+=d1;slot_square[j.h]+=d2;
    }
    if (j.c==5) {
        for (int n=0;n<6;n++) for (int h=0;h<4;h++) sum[n*4+h]=j.acc[n][h]>>24;
        j.have=j.t<6;j.b=j.i;j.h=j.t;j.dp=j.a;
        if (j.i==110) {j.i=0;j.a=0;j.t++;} else {j.i++;j.a+=4;}
        j.p=j.a;j.c=0;
    } else {j.c++;j.p+=441;j.dp+=441;}
    return ++j.phase==4002;
}
static bool res_step(MainMemory &m,Slot &s,Job &j,CoreOffer &offer,CoreResponse &response,bool &valid,
                     int64_t slot_sum[6],uint64_t slot_square[6]) {
#pragma HLS INLINE
    bool released=false;if(!consumer_data(j,offer,response,valid,released)) return released;
    for (int t=0;t<6;t++) {
#pragma HLS UNROLL
        int64_t v=int64_t(response.value[t][0])+get(m.xn,j.slot,j.p,t);
        int32_t y=sat(v,S2_DB);put(m.x,j.slot,j.p,t,y);
        slot_sum[t]+=y;slot_square[t]+=uint64_t(int64_t(y)*y);
    }
    if (++j.c==54) {j.c=0;if (++j.b==7) {j.b=0;if (j.a&1) j.i+=54;j.a++;}}
    if(++j.p==2646) j.phase=1;return false;
}
static bool head_step(MainMemory &m,Slot &s,Job &j,MathOffer &offer,int64_t sum[24]) {
#pragma HLS INLINE
    if (j.phase==0) {
        const int32_t x=get(m.x,j.slot,j.p,1);
        for (int g=0;g<6;g++) for (int lane=0;lane<4;lane++) {
#pragma HLS UNROLL
            const int c=g*4+lane;
            int16_t w=int16_t(m.head[g][j.p]>>(lane*16));
            sum[c]=(j.p==0?0:sum[c])+int64_t(w)*x;
        }
        if (++j.p==2646) {j.phase=1;j.c=0;}
    } else if (j.phase==1) {
        int64_t v=rnd(sum[j.c],S2_DF+m.he[j.c]-16)+m.hb[j.c];
        sum[j.c]=v;s.logits[j.c]=int32_t(v);
        if (v>j.maximum) {j.maximum=v;s.cls=unsigned(j.c);}
        if (++j.c==int(m.ncls)) {j.phase=2;j.c=0;}
    } else if (j.phase==2) {
        j.exp_sum+=exponential(uint64_t(j.maximum-sum[j.c])<<8);
        if (++j.c==int(m.ncls)) j.phase=3;
    } else if (j.phase==3) {
        if (reserve_math(j,m3math::CONF,0,0,0,j.exp_sum,offer)) {j.have=false;j.phase=4;}
    } else if (j.have) {
        s.cls|=uint32_t(j.recip)<<16;j.have=false;return true;
    }
    return false;
}
static void next_layer(Slot &s,unsigned hi,unsigned flags) {
    s.dump=false;
    if (s.layer==hi) {s.final=true;if (flags&S2_FEAT) s.output=true;}
    else {s.layer++;s.done=0;s.kv_kind=-1;}
}
static bool io_step(MainMemory &m,Slot &s,Job &j,const uint64_t *input,
                    uint64_t *logits,uint32_t *classes,uint64_t *features,
                    unsigned count,unsigned flags,unsigned lo,
                    int64_t slot_sum[6],uint64_t slot_square[6]) {
#pragma HLS INLINE
    if (j.stage==IO_LOAD) {
        const int lanes=flags&S2_RAW?2:4;
        const uint64_t w=input[s.id*(15876/lanes)+j.p];
        for (int k=0;k<4;k++) {
#pragma HLS UNROLL
            if (k<lanes) {
                int32_t v=flags&S2_RAW ? sat(int32_t(w>>(32*k)),S2_DB) : int32_t(quant(int16_t(w>>(16*k)),12-S2_DF));
                put(m.x,j.slot,j.a,j.t,v);slot_sum[j.t]+=v;slot_square[j.t]+=uint64_t(int64_t(v)*v);
                if (++j.t==6) {j.t=0;j.a++;}
            }
        }
        return ++j.p==15876/lanes;
    }
    if (j.stage==IO_DUMP) {
        uint64_t w=0;
        for (int k=0;k<2;k++) {
            w|=uint64_t(uint32_t(get(m.x,j.slot,j.a,j.t)))<<(32*k);
            if (++j.t==6) {j.t=0;j.a++;}
        }
        const unsigned layer=flags&S2_DUMP?unsigned(s.layer)-lo:0;
        features[(layer*count+s.id)*7938+j.p]=w;
        return ++j.p==7938;
    }
    if (!(flags&S2_FEAT)) {
        if (!(flags&S2_CLASS_ONLY)) {
            logits[s.id*16+j.p]=uint64_t(uint32_t(s.logits[2*j.p]))|(uint64_t(uint32_t(s.logits[2*j.p+1]))<<32);
            if (++j.p<16) return false;
        }
        classes[s.id]=s.cls;
    }
    return true;
}
} // namespace s2

static unsigned engine_body(const uint64_t *weights,const uint64_t *input,
                   uint64_t *logits,uint32_t *classes,uint64_t *features,
                   unsigned count,unsigned flags,unsigned lo,unsigned hi,
                   unsigned stall_seed,unsigned max_iterations,uint32_t meta[S2_META_WORDS],
                   s2::MathRequests &rq,s2::MathResponses &rs,unsigned &issued,unsigned &received,
                   s2::CoreRequests &cq,s2::CoreResponses &cr,unsigned &core_issued,unsigned &core_received) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=s2::deps complete dim=0
#pragma HLS ARRAY_PARTITION variable=s2::unit_for complete dim=0
    using namespace s2;
    static MainMemory mem;
    static Slot slots[S2_P];
    static Job jobs[8];
    // Same mean/inv scalars, moved out of Slot (not copied). HLS 2020.2
    // rejects ARRAY_PARTITION variable=slots.mean on an array of structs.
    static int32_t norm_mean[S2_P][6],norm_inv[S2_P][6];
    // Original Slot storage, moved (old members deleted), not shadow copies.
    // Six RESIDUAL statistics updates and six SCORE row writes are parallel.
    static int64_t slot_sum[S2_P][6];
    static uint64_t slot_square[S2_P][6];
    static int64_t slot_scores[S2_P][6][6];
#pragma HLS ARRAY_PARTITION variable=slot_sum complete dim=0
#pragma HLS ARRAY_PARTITION variable=slot_square complete dim=0
#pragma HLS ARRAY_PARTITION variable=slot_scores complete dim=1
#pragma HLS ARRAY_PARTITION variable=slot_scores complete dim=2
    // Keep each score row as six addressed columns, not 36 registers/slot.
#pragma HLS BIND_STORAGE variable=slot_scores type=ram_2p impl=lutram
    // The two original live Job::sum arrays, moved, not duplicated.
    // HEAD needs 24 concurrent read/modify/writes; CONTEXT keeps its storage.
    static int64_t head_sum[24],ctx_sum[24];
#pragma HLS ARRAY_PARTITION variable=head_sum complete dim=1
#pragma HLS ARRAY_PARTITION variable=mem.x complete dim=1
#pragma HLS ARRAY_PARTITION variable=mem.x complete dim=2
#pragma HLS ARRAY_PARTITION variable=mem.xn complete dim=1
#pragma HLS ARRAY_PARTITION variable=mem.xn complete dim=2
#pragma HLS ARRAY_PARTITION variable=mem.q complete dim=1
#pragma HLS ARRAY_PARTITION variable=mem.q complete dim=2
#pragma HLS ARRAY_PARTITION variable=mem.kv complete dim=1
#pragma HLS ARRAY_PARTITION variable=mem.kv complete dim=2
#pragma HLS BIND_STORAGE variable=mem.x type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=mem.xn type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=mem.q type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=mem.kv type=ram_t2p impl=bram
#pragma HLS ARRAY_PARTITION variable=mem.head complete dim=1
#pragma HLS BIND_STORAGE variable=mem.head type=ram_1p impl=uram
#pragma HLS ARRAY_PARTITION variable=slots complete dim=1
#pragma HLS ARRAY_PARTITION variable=norm_mean complete dim=0
#pragma HLS ARRAY_PARTITION variable=norm_inv complete dim=0
#pragma HLS ARRAY_PARTITION variable=jobs complete dim=1
    for (int i=0;i<S2_META_WORDS;i++) meta[i]=0;
    meta[0]=S2_FORMAT;
    if ((flags&~31u) || ((flags&S2_FEAT) && (flags&S2_CLASS_ONLY)) || count>64 || (!count && !(flags&S2_LOAD)) || (count && (lo>hi || hi>=12 || (!(flags&S2_FEAT) && hi!=11)))) return S2_BAD_CONFIG;
    if ((flags&S2_LOAD) && !load(mem,weights)) return S2_BAD_PACKAGE;
    if(flags&S2_LOAD) {
        // Explicit loop-carried phases: a blocking cr.read() here was
        // scheduled before core_send_weights in the r9 RTL and deadlocked.
        // Only a successful LOAD request handshake enables the ACK phase.
        State<3> load_phase=0;
load_handshake:
        while(load_phase!=3) {
#pragma HLS PIPELINE off
#ifndef __SYNTHESIS__
            core_sim_tick(cq,cr);
#endif
            if(load_phase==0) {
                core_send_weights(weights,cq,cr);
                load_phase=1;
            } else if(load_phase==1) {
                CoreRequest r={};r.kind=CORE_LOAD;
#ifndef __SYNTHESIS__
                // hls::stream is unbounded in C; mirror the RTL depth=2.
                if(cq.size()>=2) continue;
#endif
                if(cq.write_nb(r)) {++core_issued;load_phase=2;}
            } else {
                CoreResponse y;
                if(cr.read_nb(y)) {
                    S2_ASSERT(y.kind==CORE_LOAD);
                    ++core_received;load_phase=3;
                }
            }
        }
    }
    if (count && !mem.loaded) return S2_NO_WEIGHT;
    for (int s=0;s<S2_P;s++) slots[s].live=false;
    for (int u=0;u<8;u++) jobs[u].active=false;
    int xb_owner=-1,ob_owner=-1,ob_kind=-1;
    unsigned accepted=0,retired=0,rng=stall_seed;
    State<4> norm_received=0; // 0..6, separate from every worker's Job::i
    CoreResponse returned={};bool returned_valid=false;
    // One held 6x2 response, not another ob. read_nb unpacks all twelve
    // values together and COPY consumes both lanes for all six tokens.
    // Without this, HLS 2020.2 infers a port-limited local response RAM.
#pragma HLS ARRAY_PARTITION variable=returned.value complete dim=0
schedule_loop:
    while (retired<count) {
#pragma HLS PIPELINE II=1
        // This is a requested initiation interval, NOT a proven hardware clock.
        if (meta[1]++>=max_iterations) return S2_TIMEOUT;
        const Dispatch grant=select_dispatch(jobs,slots,xb_owner,ob_owner,
            meta[1]%S2_P,accepted,retired,count,meta);
        const int grant_unit=grant.stage>=IO_LOAD?TRANSFER:
            grant.stage>=0?unit_for[grant.stage]:-1;
        MathOffer offer={};
        CoreOffer core={};
#ifdef __SYNTHESIS__
        core.ready=!cq.full();
#else
        core_sim_tick(cq,cr);core.ready=cq.size()<2;
#endif
        if(!returned_valid && cr.read_nb(returned)) {returned_valid=true;++core_received;}
        for (int u=0;u<8;u++) {
#pragma HLS UNROLL
            Job &j=jobs[u];
            // Static unit-local lifecycle: idle->start OR active->step.
            // No dynamic begin after completion, and no same-tick execution.
            if (!j.active) {
                if(grant.slot>=0 && grant_unit==u) j.begin(grant.slot,grant.stage);
                continue;
            }
            if (pause(rng)) {if (j.stage==IO_OUT) meta[8]++;continue;}
            Slot &s=slots[j.slot];bool done=false;
            if (u==NORMAL) {S2_ASSERT(xb_owner==j.slot);done=norm_step(mem,s,j,offer,core,unsigned(norm_received),norm_mean[j.slot],norm_inv[j.slot],slot_sum[j.slot],slot_square[j.slot]);}
            else if (u==PROJECT) {
                S2_ASSERT(xb_owner==j.slot && ob_owner==j.slot && ob_kind==j.stage);
                int pj=j.stage==Q?0:j.stage==K?1:j.stage==V?2:3;
                if(!j.have) {
                    if(reserve_core(j,CORE_START,core)) {core.item.pid=int(s.layer)*4+pj;j.have=true;}
                } else if(returned_valid) {
                    S2_ASSERT(returned.kind==CORE_START && returned.slot==j.slot && returned.stage==j.stage);
                    returned_valid=false;done=true;
                }
            } else if (u==COPY) {
                int kind=j.stage==CQ?Q:j.stage==CK?K:V;
                S2_ASSERT(ob_owner==j.slot && ob_kind==kind);
                S2_ASSERT(j.stage!=CV || ((s.done&bit(S)) && s.kv_kind==K));
                done=copy_step(mem,j,core,returned,returned_valid);
            } else if (u==SCORE) done=score_step(mem,s,j,slot_scores[j.slot]);
            else if (u==AUX) done=j.stage==HEAD?head_step(mem,s,j,offer,head_sum):softmax_step(s,j,offer,slot_scores[j.slot]);
            else if (u==CONTEXT) done=ctx_step(mem,s,j,ctx_sum,slot_sum[j.slot],slot_square[j.slot]);
            else if (u==RESIDUAL) {S2_ASSERT(ob_owner==j.slot && ob_kind==M);done=res_step(mem,s,j,core,returned,returned_valid,slot_sum[j.slot],slot_square[j.slot]);}
            else done=io_step(mem,s,j,input,logits,classes,features,count,flags,lo,slot_sum[j.slot],slot_square[j.slot]);
            j.check_bounds();
            S2_ASSERT(s.id>=0 && s.id<64 && s.layer>=0 && s.layer<12);
            S2_ASSERT(s.done>=0 && s.done<16384 && s.kv_kind>=-1 && s.kv_kind<=V);
            if (!done) continue;
            if (u!=TRANSFER) s.done|=State<15>(bit(j.stage));
            if (u==PROJECT) {
                meta[3]++;if (j.stage==V || j.stage==M) xb_owner=-1;
#if S2_FAULT==1
                ob_owner=-1; // negative test: projection completion != consumer completion
#endif
            }
            if (u==COPY) {meta[4]++;ob_owner=-1;ob_kind=-1;if (j.stage!=CQ) s.kv_kind=j.stage==CK?K:V;}
            // The unit is a compile-time constant in this unrolled loop.
            // Do not synthesize every completion kind for every worker merely
            // because Job::stage is stored as a runtime integer.
            if (u==RESIDUAL) {
                meta[9]++;ob_owner=-1;ob_kind=-1;
                if ((flags&S2_DUMP) || ((flags&S2_FEAT) && s.layer==hi)) s.dump=true;
                else next_layer(s,hi,flags);
            }
            if (u==AUX && j.stage==HEAD) s.output=true;
            if (u==TRANSFER) {
                if (j.stage==IO_LOAD) s.loaded=true;
                if (j.stage==IO_DUMP) next_layer(s,hi,flags);
                if (j.stage==IO_OUT) {S2_ASSERT(s.id==retired);s.live=false;retired++;meta[2]=retired;}
            }
            j.active=false;
        }
        // Commit math responses after execution. A new response cannot pass
        // through phase control and normalization in this same iteration.
        m3math::Response answer;
        if (rs.read_nb(answer)) {
            ++received;
            const unsigned sl=answer.tag&1,st=(answer.tag>>1)&31,t=answer.tag>>6;
            if (answer.error || sl>=S2_P) return S2_BAD_CONFIG;
            if (answer.kind==m3math::NORM) {
                S2_ASSERT(jobs[NORMAL].active && unsigned(jobs[NORMAL].slot)==sl && unsigned(jobs[NORMAL].stage)==st);
                S2_ASSERT(t<6 && (st==N1 || st==N2) && norm_received<6);
                norm_mean[sl][t]=answer.mean;norm_inv[sl][t]=answer.inv;++norm_received;
            } else {
                Job &mj=jobs[AUX];
                S2_ASSERT(mj.active && unsigned(mj.slot)==sl && unsigned(mj.stage)==st);
                S2_ASSERT(mj.phase==4 && !mj.have && (st==SM || st==HEAD));
                S2_ASSERT(st!=SM || t==unsigned(mj.t));
                mj.recip=answer.value;mj.have=true;
            }
        }
        // Apply only the previously chosen grant; no same-tick completion
        // can enable it. Contexts add addresses, not another compute core.
        if(grant.slot>=0) {
            const int sl=grant.slot,st=grant.stage,u=st>=IO_LOAD?TRANSFER:unit_for[st];
            Slot &s=slots[sl];S2_ASSERT(jobs[u].active && jobs[u].slot==sl && jobs[u].stage==st);
            if(u==PROJECT) {S2_ASSERT(xb_owner==sl && ob_owner<0);ob_owner=sl;ob_kind=st;}
            if(u==NORMAL) {S2_ASSERT(xb_owner<0);xb_owner=sl;norm_received=0;}
            if(st==C || st==R) for(int t=0;t<6;t++) {slot_sum[sl][t]=0;slot_square[sl][t]=0;}
            if(st==HEAD) for(int c=0;c<32;c++) s.logits[c]=0;
            if(st==IO_LOAD) {
                s.live=true;s.loaded=s.final=s.output=s.dump=false;
                s.id=accepted++;s.layer=lo;s.done=0;s.kv_kind=-1;
                for(int t=0;t<6;t++) {slot_sum[sl][t]=0;slot_square[sl][t]=0;}
            }
        }
        unsigned live=0;
        for (int u=0;u<8;u++) if (jobs[u].active) live++;
        if (live>meta[5]) meta[5]=live;
        // Single FIFO writer; state only advances after an available offer.
        // Read/START responses have at most one outstanding transaction.
        if(core.valid) {cq.write(core.item);if(core_reply_kind(core.item.kind)) ++core_issued;}
        S2_ASSERT(core_issued>=core_received && core_issued-core_received<=1);
        // One explicit request-port arbiter, not two inlined FIFO writers.
        // NORMAL can have at most6 outstanding requests, AUX at most1;
        // each FIFO has depth8. Blocking write remains safe under backpressure.
        if (offer.valid) {
#ifdef __SYNTHESIS__
            rq.write(offer.item);
#else
            rs.write(m3math::compute(offer.item));
#endif
            ++issued;S2_ASSERT(issued>=received && issued-received<=7);
        }
    }
    S2_ASSERT(xb_owner<0 && ob_owner<0);
    for (int u=0;u<8;u++) S2_ASSERT(!jobs[u].active);
    return S2_OK;
}

static void engine_task(const uint64_t *weights,const uint64_t *input,
                   uint64_t *logits,uint32_t *classes,uint64_t *features,
                   unsigned count,unsigned flags,unsigned lo,unsigned hi,
                   unsigned stall_seed,unsigned max_iterations,uint32_t meta[S2_META_WORDS],
                   s2::MathRequests &rq,s2::MathResponses &rs,
                   s2::CoreRequests &cq,s2::CoreResponses &cr,unsigned &result) {
#pragma HLS INLINE off
    unsigned issued=0,received=0;
    unsigned core_issued=0,core_received=0;
    // Keep live diagnostics off the AXI-Lite meta write address/data path.
    // Every return path publishes the same ABI only after workers drain.
    uint32_t counters[S2_META_WORDS];
#pragma HLS ARRAY_PARTITION variable=counters complete
#ifndef __SYNTHESIS__
    s2::core_sim_begin();
#endif
    result=engine_body(weights,input,logits,classes,features,count,flags,lo,hi,
                       stall_seed,max_iterations,counters,rq,rs,issued,received,cq,cr,core_issued,core_received);
    // Every return path, including timeout/bad config, must retire accepted
    // requests before STOP. No stale response can leak into the next call.
math_drain:
#if S2_FAULT!=3
    while (received<issued) {rs.read();++received;}
#endif
    S2_ASSERT(issued==received);
    m3math::stop(rq);
core_drain:
    while(core_received<core_issued) {
#pragma HLS PIPELINE off
#ifndef __SYNTHESIS__
        while(cr.empty()) s2::core_sim_tick(cq,cr);
#endif
        cr.read();++core_received;
    }
    S2_ASSERT(core_issued==core_received);
    s2::CoreRequest end={};end.kind=s2::CORE_STOP;cq.write(end);
#ifndef __SYNTHESIS__
    while(!cq.empty()) s2::core_sim_tick(cq,cr);
    S2_ASSERT(cr.empty());
#endif
meta_publish:
    for(int i=0;i<S2_META_WORDS;i++) {
#pragma HLS PIPELINE II=1
        meta[i]=counters[i];
    }
}
unsigned s2_engine(const uint64_t *weights,const uint64_t *input,
                   uint64_t *logits,uint32_t *classes,uint64_t *features,
                   unsigned count,unsigned flags,unsigned lo,unsigned hi,
                   unsigned stall_seed,unsigned max_iterations,uint32_t meta[S2_META_WORDS]) {
#pragma HLS INTERFACE m_axi port=weights offset=slave bundle=wmem
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=inmem
#pragma HLS INTERFACE m_axi port=logits offset=slave bundle=outmem
#pragma HLS INTERFACE m_axi port=classes offset=slave bundle=outmem
#pragma HLS INTERFACE m_axi port=features offset=slave bundle=outmem
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=logits bundle=control
#pragma HLS INTERFACE s_axilite port=classes bundle=control
#pragma HLS INTERFACE s_axilite port=features bundle=control
#pragma HLS INTERFACE s_axilite port=count bundle=control
#pragma HLS INTERFACE s_axilite port=flags bundle=control
#pragma HLS INTERFACE s_axilite port=lo bundle=control
#pragma HLS INTERFACE s_axilite port=hi bundle=control
#pragma HLS INTERFACE s_axilite port=stall_seed bundle=control
#pragma HLS INTERFACE s_axilite port=max_iterations bundle=control
#pragma HLS INTERFACE s_axilite port=meta bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    s2::MathRequests rq("s2_math_request");s2::MathResponses rs("s2_math_response");
    s2::CoreRequests cq("s2_core_request");s2::CoreResponses cr("s2_core_response");
#pragma HLS STREAM variable=rq depth=8
#pragma HLS STREAM variable=rs depth=8
#pragma HLS STREAM variable=cq depth=2
#pragma HLS STREAM variable=cr depth=2
    unsigned result=0;
#ifdef __SYNTHESIS__
#pragma HLS DATAFLOW
    engine_task(weights,input,logits,classes,features,count,flags,lo,hi,stall_seed,max_iterations,meta,rq,rs,cq,cr,result);
    m3math::service(rq,rs);
    s2::core_service(cq,cr);
#else
    engine_task(weights,input,logits,classes,features,count,flags,lo,hi,stall_seed,max_iterations,meta,rq,rs,cq,cr,result);
#endif
    return result;
}
