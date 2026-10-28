#include "s2_worker.h"
namespace s2 {
bool Projection::step(CoreMemory &mem,int pid) {
#pragma HLS INLINE
    // Decide from the registered entry state, never from a tag just produced
    // below. Completion -> tag -> grant -> token is split across iterations.
#pragma HLS ARRAY_PARTITION variable=tag1 complete
#pragma HLS ARRAY_PARTITION variable=tag2 complete
    const bool finished=next==6 && tok1<0 && tok2<0 && tok3<0 &&
        tag1[0]==-1 && tag1[1]==-1 && tag2[0]==-1 && tag2[1]==-1;
    if(finished) return true;
    const int take3=tok3>=0?-1:tag2[0]>=0?0:tag2[1]>=0?1:-1;
    const int take2=tok2>=0?-1:(tag1[0]>=0 && tag2[0]==-1)?0:
        (tag1[1]>=0 && tag2[1]==-1)?1:-1;
    const int token3=take3<0?-1:int(tag2[take3]);
    const int token2=take2<0?-1:int(tag1[take2]);
    const bool take1=tok1<0 && next<6 && tag1[next&1]==-1;
    const int e1=mem.exponent[pid][0],e2=mem.exponent[pid][1],e3=mem.exponent[pid][2];
    if (tok3>=0) {
        // Common producer write, at most one result per b bank each tick.
        if (pending_valid) {
            for (int b=0;b<7;b++) {
#pragma HLS UNROLL
#if S2_NUM==8
                mem.ob[tok3][pending_a&1][b][(pending_a>>1)*54+j3]=projection_quant<21>(pending[b][j3],e3);
#else
                mem.ob[tok3][pending_a&1][b][(pending_a>>1)*54+j3]=pending[b][j3];
#endif
            }
        }
        if (flush3) {
            if (++j3==54) { tag2[tok3&1]=-1;tok3=-1;pending_valid=false; }
        } else {
            Weight w[54];
#pragma HLS ARRAY_PARTITION variable=w complete
            for (int c=0;c<54;c++) {
#pragma HLS UNROLL
                const uint64_t word=mem.wm3[c/VLANES][pid*54+j3];
                w[c]=Weight(S2_WB==8 ? int8_t(word>>(8*(c%VLANES))) : int16_t(word>>(16*(c%VLANES))));
            }
            for (int b=0;b<7;b++) {
#pragma HLS UNROLL
                const Mid x=t2[b][(tok3&1)*378+g3*54+j3];
                for (int c=0;c<54;c+=2) {
#pragma HLS UNROLL
                    Acc lo,hi;pair_mul(x,w[c],w[c+1],lo,hi);
                    acc[b][c]=(j3==0?Acc(0):acc[b][c])+lo;
                    acc[b][c+1]=(j3==0?Acc(0):acc[b][c+1])+hi;
                }
            }
            if (++j3==54) {
                for (int b=0;b<7;b++) for (int c=0;c<54;c++) {
#pragma HLS UNROLL
#if S2_NUM==8
                    pending[b][c]=acc[b][c];
#else
                    pending[b][c]=quant(int64_t(acc[b][c]),S2_MF+e3-S2_DF);
#endif
                }
                pending_valid=true;pending_a=g3;j3=0;
                if (++g3==7) flush3=1;
            }
        }
    }
    if (tok2>=0) {
        const int a=int(index2.row),j=int(index2.col),buf=tok2&1;
        for (int b=0;b<7;b+=2) {
#pragma HLS UNROLL
            Acc s0=0,s1=0;
            for (int i=0;i<7;i++) {
#pragma HLS UNROLL
                Acc lo,hi;
                Weight w1=b+1<7 ? mem.wm12[49+(b+1)*7+i][pid] : Weight(0);
                pair_mul(t1[a][i][buf*54+j],mem.wm12[49+b*7+i][pid],w1,lo,hi);
                s0+=lo;s1+=hi;
            }
            t2[b][buf*378+int(index2.flat)]=Mid(projection_quant<18>(s0,e2));
            if (b+1<7) t2[b+1][buf*378+int(index2.flat)]=Mid(projection_quant<18>(s1,e2));
        }
        if (index2.advance()) { tag1[buf]=-1;tag2[buf]=tok2;tok2=-1; }
    }
    if (tok1>=0) {
        const int b=int(index1.row),j=int(index1.col),buf=tok1&1;
        for (int a=0;a<7;a+=2) {
#pragma HLS UNROLL
            Acc s0=0,s1=0;
            for (int i=0;i<7;i++) {
#pragma HLS UNROLL
                Acc lo,hi;
                Weight w1=a+1<7 ? mem.wm12[(a+1)*7+i][pid] : Weight(0);
                pair_mul(Mid(mem.xb[tok1][i][int(index1.flat)]),mem.wm12[a*7+i][pid],w1,lo,hi);
                s0+=lo;s1+=hi;
            }
            t1[a][b][buf*54+j]=Mid(projection_quant<18>(s0,S2_DF+e1-S2_MF));
            if (a+1<7) t1[a+1][b][buf*54+j]=Mid(projection_quant<18>(s1,S2_DF+e1-S2_MF));
        }
        if (index1.advance()) { tag1[buf]=tok1;tok1=-1; }
    }
    if (take3>=0) {
        tok3=token3;tag2[take3]=-3;g3=j3=flush3=0;pending_valid=false;
    }
    if (take2>=0) {
        tok2=token2;tag1[take2]=-3;tag2[take2]=-2;index2.reset();
    }
    if (take1) {
        tok1=next++;tag1[tok1&1]=-2;index1.reset();
    }
    S2_ASSERT(next>=0 && next<=6 && g3>=0 && g3<=7 && j3>=0 && j3<=54);
    S2_ASSERT(tok1>=-1 && tok1<=5 && tok2>=-1 && tok2<=5 && tok3>=-1 && tok3<=5);
    S2_ASSERT(flush3>=0 && flush3<=1);
    S2_ASSERT(!pending_valid || (pending_a>=0 && pending_a<=6));
    for (int b=0;b<2;b++) {
        S2_ASSERT(tag1[b]>=-3 && tag1[b]<=5 && tag2[b]>=-3 && tag2[b]<=5);
    }
    return false;
}
static int32_t raw(const uint64_t *d,unsigned byte,unsigned bits) {
    uint64_t x=d[byte>>3]>>(8*(byte&7));
    return bits==8 ? int8_t(x) : bits==16 ? int16_t(x) : int32_t(x);
}
static void send_weight(CoreRequest r,CoreRequests &request,CoreResponses &response) {
#pragma HLS INLINE
#ifndef __SYNTHESIS__
    while(request.size()>=2) core_sim_tick(request,response);
#else
    (void)response;
#endif
    request.write(r);
}
void core_send_weights(const uint64_t *d,CoreRequests &request,CoreResponses &response) {
#pragma HLS INLINE off
    for (int pid=0;pid<48;pid++) {
        for (int k=0;k<3;k++) {
            CoreRequest r;r.kind=CORE_EXP;r.pid=pid;r.c=k;
            r.word=S2_NUM==8 ? raw(d,335904+pid*3+k,8) : 14;send_weight(r,request,response);
        }
        for (int e=0;e<98;e++) {
            CoreRequest r;r.kind=CORE_W12;r.pid=pid;r.c=e;
            r.word=uint64_t(int64_t(raw(d,191232+(pid*3014+e)*(S2_WB/8),S2_WB)));
            send_weight(r,request,response);
        }
        for (int j=0;j<54;j++) for (int g=0;g<WGROUP;g++) {
            uint64_t word=0;
            for (int lane=0;lane<VLANES;lane++) {
                int c=g*VLANES+lane;
                if (c<54) {
                    const int32_t v=raw(d,191232+(pid*3014+98+c*54+j)*(S2_WB/8),S2_WB);
                    word|=(uint64_t(uint32_t(v))&((uint64_t(1)<<S2_WB)-1))<<(lane*S2_WB);
                }
            }
            CoreRequest r;r.kind=CORE_W3;r.pid=pid;r.a=g;r.c=j;r.word=word;
            send_weight(r,request,response);
        }
    }
}
bool load(MainMemory &m,const uint64_t *d) {
    const unsigned magic=uint32_t(d[0]),version=uint32_t(d[0]>>32);
    const unsigned ncls=uint32_t(d[1]),num=uint32_t(d[1]>>32);
    if (magic!=0x32455454 || version!=2 || num!=S2_NUM || ncls==0 || ncls>24) return false;
    // Validate metadata before any persistent writes: failed reload is atomic.
    for (unsigned c=0;c<ncls;c++) {
        const int r=S2_DF+raw(d,32+c,8)-16;
        if (r<1 || r>48) return false;
    }
    if (S2_NUM==8) for (int i=0;i<144;i++) {
        int e=raw(d,335904+i,8);if (e<0 || e>24) return false;
    }
    for (int c=0;c<24;c++) {
        m.he[c]=c<int(ncls)?raw(d,32+c,8):0;
        m.hb[c]=c<int(ncls)?raw(d,63616+c*4,32):0;
    }
    for (int p=0;p<2646;p++) for (int g=0;g<6;g++) {
        uint64_t word=0;
        for (int lane=0;lane<4;lane++) {
            int c=g*4+lane;
            uint16_t v=c<int(ncls)?uint16_t(raw(d,63744+c*5312+p*2,16)):0;
            word|=uint64_t(v)<<(lane*16);
        }
        m.head[g][p]=word;
    }
    m.ncls=ncls;m.loaded=true;return true;
}
// The only ob read entry. Keep the two RAM operations behind a function
// boundary: q/kv lane predicates live in the *other* dataflow task and cannot
// replicate these load sites. Residual reuses port0, never a third read site.
static void read_ob(CoreMemory &m,const CoreRequest &r,CoreResponse &y) {
#pragma HLS INLINE off
    const int at=r.c,other=at+(r.stage==R?0:1);
    for(int t=0;t<6;t++) {
#pragma HLS UNROLL
        y.value[t][0]=m.ob[t][int(r.a)&1][r.b][at];
        y.value[t][1]=m.ob[t][int(r.a)&1][r.b][other];
    }
}
bool CoreWorker::accept(const CoreRequest &r,CoreResponse &y) {
#pragma HLS INLINE
    S2_ASSERT(!active);
    y.kind=r.kind;y.slot=r.slot;y.stage=r.stage;
    if(r.kind==CORE_LOAD) {
        S2_ASSERT(!owned);return true; // ordered load-complete ACK
    }
    if(r.kind==CORE_W12 || r.kind==CORE_W3 || r.kind==CORE_EXP) {
        S2_ASSERT(!owned && r.pid>=0 && r.pid<48);
        if(r.kind==CORE_W12) {
            S2_ASSERT(r.c>=0 && r.c<98);mem.wm12[r.c][r.pid]=Weight(int64_t(r.word));
        } else if(r.kind==CORE_W3) {
            S2_ASSERT(r.a>=0 && r.a<WGROUP && r.c>=0 && r.c<54);
            mem.wm3[r.a][int(r.pid)*54+int(r.c)]=r.word;
        } else {
            S2_ASSERT(r.c>=0 && r.c<3);mem.exponent[r.pid][r.c]=int8_t(r.word);
        }
        return false;
    }
    if(r.kind==CORE_XB) {
        S2_ASSERT(r.a>=0 && r.a<7 && r.c>=0 && r.c<378);
        for(int t=0;t<6;t++) {
#pragma HLS UNROLL
            mem.xb[t][r.a][r.c]=r.value[t];
        }
    } else if(r.kind==CORE_START) {
        S2_ASSERT(!owned && r.pid>=0 && r.pid<48 && r.slot>=0 && r.slot<S2_P);
        S2_ASSERT(r.stage==Q || r.stage==K || r.stage==V || r.stage==M);
        owner=r.slot;stage=r.stage;pid=r.pid;owned=active=true;projection.reset();
#ifndef __SYNTHESIS__
        reads=0;
#endif
    } else if(r.kind==CORE_READ || r.kind==CORE_RELEASE) {
        S2_ASSERT(owned && r.slot==owner);
        S2_ASSERT((stage==Q && r.stage==CQ) || (stage==K && r.stage==CK) ||
                  (stage==V && r.stage==CV) || (stage==M && r.stage==R));
        if(r.kind==CORE_READ) {
            S2_ASSERT(r.a>=0 && r.a<7 && r.b>=0 && r.b<7 && r.c>=0 && r.c<216);
            S2_ASSERT(r.stage==R || (r.c<215 && !(int(r.c)&1)));
#ifndef __SYNTHESIS__
            const unsigned p=reads*(r.stage==R?1:2);
            S2_ASSERT(p<2646 && r.a==int(p/378) && r.b==int((p/54)%7) && r.c==int((p/378/2)*54+p%54));
            ++reads;
#endif
            read_ob(mem,r,y);return true;
        }
        S2_ASSERT(reads==(r.stage==R?2646u:1323u));
        owned=false;
    } else {S2_ASSERT(r.kind==CORE_STOP);reset_session();}
    return false;
}
bool CoreWorker::advance(CoreResponse &y) {
#pragma HLS INLINE
    S2_ASSERT(active && owned);
    if(!projection.step(mem,pid)) return false;
    active=false;y.kind=CORE_START;y.slot=owner;y.stage=stage;return true;
}
void CoreWorker::run(CoreResponse &y) {
#pragma HLS INLINE off
    bool done=false;
project_loop:
    while(!done) {
#pragma HLS PIPELINE II=1
        done=projection.step(mem,pid);
    }
    // Session ownership survives DONE until the consumer's RELEASE.
    active=false;y.kind=CORE_START;y.slot=owner;y.stage=stage;
}
bool core_reply_kind(int kind) {
#pragma HLS INLINE
    return kind==CORE_LOAD || kind==CORE_START || kind==CORE_READ;
}
void core_service(CoreRequests &request,CoreResponses &response) {
#pragma HLS INLINE off
    static CoreWorker w;
#pragma HLS ARRAY_PARTITION variable=w.mem.xb complete dim=1
#pragma HLS ARRAY_PARTITION variable=w.mem.xb complete dim=2
#pragma HLS BIND_STORAGE variable=w.mem.xb type=ram_t2p impl=bram
#pragma HLS ARRAY_PARTITION variable=w.mem.ob complete dim=1
#pragma HLS ARRAY_PARTITION variable=w.mem.ob complete dim=3
#pragma HLS BIND_STORAGE variable=w.mem.ob type=ram_t2p impl=bram
#pragma HLS ARRAY_PARTITION variable=w.mem.wm12 complete dim=1
#pragma HLS BIND_STORAGE variable=w.mem.wm12 type=ram_1p impl=lutram
#pragma HLS ARRAY_PARTITION variable=w.mem.exponent complete dim=2
#pragma HLS ARRAY_PARTITION variable=w.mem.wm3 complete dim=1
#pragma HLS BIND_STORAGE variable=w.mem.wm3 type=ram_1p impl=uram
#pragma HLS ARRAY_PARTITION variable=w.projection.t1 complete dim=1
#pragma HLS ARRAY_PARTITION variable=w.projection.t1 complete dim=2
#pragma HLS BIND_STORAGE variable=w.projection.t1 type=ram_2p impl=lutram
#pragma HLS ARRAY_PARTITION variable=w.projection.t2 complete dim=1
#pragma HLS BIND_STORAGE variable=w.projection.t2 type=ram_t2p impl=bram
#pragma HLS ARRAY_PARTITION variable=w.projection.acc complete dim=0
#pragma HLS ARRAY_PARTITION variable=w.projection.pending complete dim=0
#pragma HLS ARRAY_PARTITION variable=w.projection.tag1 complete dim=0
#pragma HLS ARRAY_PARTITION variable=w.projection.tag2 complete dim=0
    w.reset_session();
    while(true) {
#pragma HLS PIPELINE off
        CoreRequest r=request.read();
        if(r.kind==CORE_STOP) return;
        CoreResponse y={};bool reply=w.accept(r,y);
        if(r.kind==CORE_START) {w.run(y);reply=true;}
        if(reply) response.write(y);
    }
}
#ifndef __SYNTHESIS__
static CoreWorker sim_worker;
void core_sim_begin() {sim_worker.reset_session();}
void core_sim_tick(CoreRequests &request,CoreResponses &response) {
    // Holding a full response FIFO holds the worker and its ob ownership.
    if(response.size()>=2) return;
    CoreResponse y={};bool reply=false;
    if(sim_worker.active) reply=sim_worker.advance(y);
    else {CoreRequest r;if(request.read_nb(r)) reply=sim_worker.accept(r,y);}
    if(reply) response.write(y);
}
#endif
} // namespace
