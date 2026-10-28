#include "s2_engine.h"
#include "s2_internal.h"
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <vector>
#include <fstream>
static const uint64_t GUARD=UINT64_C(0x5a719dce4362be08);
static std::string root;
static void check(bool ok,const char *why) { if (!ok) {fprintf(stderr,"S2_FAIL %s\n",why);exit(2);} }
template<typename T> static std::vector<T> read(const std::string &name) {
    std::ifstream f((root+"/"+name).c_str(),std::ios::binary|std::ios::ate);
    check(bool(f),name.c_str());size_t bytes=size_t(f.tellg());check(bytes%sizeof(T)==0,"file size");
    std::vector<T> v(bytes/sizeof(T));f.seekg(0);f.read(reinterpret_cast<char*>(v.data()),bytes);return v;
}
static std::string golden() { return S2_NUM==8?"sim/golden/n6_engine_i8/":"sim/golden/n6_engine/"; }
static std::vector<uint64_t> raw_input(const std::vector<int32_t> &v) {
    check(v.size()%2==0,"raw input parity");std::vector<uint64_t> words(v.size()/2);
    for (size_t i=0;i<words.size();i++) words[i]=uint64_t(uint32_t(v[2*i]))|(uint64_t(uint32_t(v[2*i+1]))<<32);
    return words;
}
struct Buffers {
    std::vector<uint64_t> lg,feat;std::vector<uint32_t> cls;uint32_t meta[S2_META_WORDS];
    Buffers(unsigned n,unsigned layers):lg(n*16+4,GUARD),feat(n*7938*layers+4,GUARD),cls(n+8,0x9ac51e37u) {}
};
static unsigned call(const std::vector<uint64_t> &w,const std::vector<uint64_t> &x,Buffers &b,unsigned n,unsigned flags,unsigned lo,unsigned hi,unsigned seed=0,unsigned limit=20000000) {
    unsigned rc=s2_engine(w.data(),x.data(),b.lg.data(),b.cls.data(),b.feat.data(),n,flags,lo,hi,seed,limit,b.meta);
    check(b.meta[0]==S2_FORMAT,"format metadata");
    if (!rc && n) {
        check(b.meta[2]==n,"retirement count");
        check(b.meta[3]==n*(hi-lo+1)*4,"single projection completion count");
        check(b.meta[4]==n*(hi-lo+1)*3,"copy completion count");
        check(b.meta[9]==n*(hi-lo+1),"layer completion count");
        printf("S2_CALL n=%u layers=%u seed=%u iterations_not_cycles=%u peak_units=%u ob_wait=%u xb_wait=%u kv_wait=%u port_wait=%u\n",n,hi-lo+1,seed,b.meta[1],b.meta[5],b.meta[6],b.meta[7],b.meta[10],b.meta[11]);
    }
    return rc;
}
static void guard(const std::vector<uint64_t> &v,size_t start) {for (size_t i=start;i<v.size();i++) check(v[i]==GUARD,"output overrun");}
static void block(const std::vector<uint64_t> &got,size_t off,const std::vector<int32_t> &want,const char *tag) {
    for (size_t e=0;e<want.size();e++) {
        int32_t v=int32_t(got[off+e/2]>>(32*(e%2)));
        if (v!=want[e]) {fprintf(stderr,"S2_MISMATCH %s e=%u got=%d expected=%d\n",tag,unsigned(e),v,want[e]);exit(3);}
    }
}
static void logits(Buffers &b,unsigned id,const std::string &entry) {
    block(b.lg,id*16,read<int32_t>(golden()+entry+"/logits_q16_i32.bin"),"logits");
    check(b.cls[id]==read<uint32_t>(golden()+entry+"/class_u32.bin")[0],"class/confidence");
}
static void timeout_drain(const std::vector<uint64_t> &w,const std::vector<uint64_t> &x) {
    // 3969 input words, then norm requests. This cutoff leaves a response
    // outstanding in the C model; S2_FAULT=3 skips drain and must fail.
    Buffers aborted(1,1);
    check(call(w,x,aborted,1,S2_CLASS_ONLY,0,11,0,3972)==S2_TIMEOUT,"timeout with math outstanding");
    guard(aborted.lg,0);guard(aborted.feat,0);
    for (uint32_t c:aborted.cls) check(c==0x9ac51e37u,"aborted class untouched");
    Buffers next(1,1);
    check(call(w,x,next,1,S2_FEAT,0,0)==S2_OK,"reuse after math drain");
    block(next.feat,0,read<int32_t>(golden()+"a/L0_x_out_i4.bin"),"after math drain");
    guard(next.feat,7938);guard(next.lg,0);
    // Exercise timeout while XB is queued, projection is active, and copy /
    // residual traffic is in flight. Every new invocation must start clean.
    for(unsigned cut: {6600u,6700u,9000u,10000u,12000u,38000u,44000u}) {
        Buffers interrupted(1,1);
        check(call(w,x,interrupted,1,S2_CLASS_ONLY,0,11,0,cut)==S2_TIMEOUT,"core timeout drain");
        guard(interrupted.lg,0);guard(interrupted.feat,0);
        for(uint32_t c:interrupted.cls) check(c==0x9ac51e37u,"core aborted class untouched");
        Buffers clean(1,1);
        check(call(w,x,clean,1,S2_FEAT,0,0)==S2_OK,"reuse after core drain");
        block(clean.feat,0,read<int32_t>(golden()+"a/L0_x_out_i4.bin"),"after core drain");
        guard(clean.feat,7938);guard(clean.lg,0);
    }
}
int main(int argc,char **argv) {
    const char *env=getenv("S2_ROOT");root=env?env:".";
    std::string mode=argc>1?argv[1]:"full";
    for (int v=-32768;v<=32767;v++) {
        int want=S2_NUM==8 ? int(floor((double(v)+128)/256)) : v;
        if (want>127 && S2_NUM==8) want=127;
        check(int32_t(s2::quant(v,12-S2_DF))==want,"actual C++ entry quantizer");
    }
    auto w=read<uint64_t>(golden()+"weights_engine.bin");
    auto x=read<uint64_t>(golden()+"a/x_in_i16.bin");
    Buffers b(1,12);
    check(call(w,x,b,1,0,0,11)==S2_NO_WEIGHT,"missing weights gate");
    check(call(w,x,b,65,S2_LOAD,0,11)==S2_BAD_CONFIG,"batch gate");
    auto bad=w;bad[1]^=UINT64_C(24)<<32;
    check(call(bad,x,b,0,S2_LOAD,0,0)==S2_BAD_PACKAGE,"numeric format gate");
    check(call(w,x,b,0,S2_LOAD,0,0)==S2_OK,"weight load");
    bad=w;bad[0]^=UINT64_C(1)<<32;
    check(call(bad,x,b,0,S2_LOAD,0,0)==S2_BAD_PACKAGE,"version gate");
    bad=w;bad[4]=(bad[4]&~UINT64_C(255))|255;
    check(call(bad,x,b,0,S2_LOAD,0,0)==S2_BAD_PACKAGE,"head shift gate");
    if (S2_NUM==8) {bad=w;bad[335904/8]=(bad[335904/8]&~UINT64_C(255))|127;check(call(bad,x,b,0,S2_LOAD,0,0)==S2_BAD_PACKAGE,"projection exponent gate");}
    guard(b.feat,0);guard(b.lg,0);
    if (mode=="load") {
        // LOAD-only/reload/error/STOP sessions must leave no stale ACK or
        // output writes. This is C regression, not proof of RTL ordering.
        for(int repeat=0;repeat<3;repeat++) {
            check(call(w,x,b,0,S2_LOAD,0,0)==S2_OK,"repeated LOAD handshake");
            check(call(bad,x,b,0,S2_LOAD,0,0)==S2_BAD_PACKAGE,"bad reload drains");
            guard(b.feat,0);guard(b.lg,0);
            for(auto v:b.cls) check(v==0x9ac51e37u,"LOAD class guard");
        }
        check(call(w,x,b,1,S2_FEAT,0,0)==S2_OK,"compute after reload ACK");
        block(b.feat,0,read<int32_t>(golden()+"a/L0_x_out_i4.bin"),"after reload layer0");
        guard(b.feat,7938);guard(b.lg,0);
    } else if (mode=="drain") {
        timeout_drain(w,x);
    } else if (mode=="smoke") {
        check(call(w,x,b,1,S2_FEAT,0,0)==S2_OK,"one-layer smoke");
        block(b.feat,0,read<int32_t>(golden()+"a/L0_x_out_i4.bin"),"layer0");guard(b.feat,7938);
    } else if (mode=="budget") {
        timeout_drain(w,x);
        // CLASS-only is part of the required n16 performance scope, not the
        // prior S2 ABI's simultaneous LOGITS+CLASS output. No feature writes.
        check(call(w,x,b,1,S2_FEAT|S2_CLASS_ONLY,0,11)==S2_BAD_CONFIG,"contradictory output flags");
        for (unsigned n: {1u,3u,16u}) {
            std::vector<uint64_t> in;
            for (unsigned i=0;i<n;++i) in.insert(in.end(),x.begin(),x.end());
            Buffers batch(n,1);
            check(call(w,in,batch,n,S2_CLASS_ONLY,0,11)==S2_OK,"CLASS-only supported");
            auto expected=read<uint32_t>(golden()+"a/class_u32.bin");
            for (unsigned i=0;i<n;++i) check(batch.cls[i]==expected[0],"CLASS-only result");
            for (size_t i=n;i<batch.cls.size();++i) check(batch.cls[i]==0x9ac51e37u,"CLASS-only tail guard");
            guard(batch.lg,0);guard(batch.feat,0);
        }
        auto a=read<int32_t>(golden()+"a/x_embed_i32.bin"),bb=read<int32_t>(golden()+"b/x_embed_i32.bin");
        auto in=a;in.insert(in.end(),bb.begin(),bb.end());in.insert(in.end(),a.begin(),a.end());
        auto xx=raw_input(in);Buffers mixed(3,1);
        check(call(w,xx,mixed,3,S2_RAW|S2_CLASS_ONLY,0,11,715)==S2_OK,"CLASS-only mixed odd batch");
        for (unsigned i=0;i<3;++i) check(mixed.cls[i]==read<uint32_t>(golden()+(i==1?"b":"a")+"/class_u32.bin")[0],"CLASS-only A/B/A order");
        for (size_t i=3;i<mixed.cls.size();++i) check(mixed.cls[i]==0x9ac51e37u,"mixed class guard");
        guard(mixed.lg,0);guard(mixed.feat,0);
    } else {
        check(call(w,x,b,1,S2_DUMP,0,11)==S2_OK,"external Q312 full dump");
        check(b.meta[10]>0,"V completed before K consumer: join exercised");
        for (int l=0;l<12;l++) block(b.feat,l*7938,read<int32_t>(golden()+"a/L"+std::to_string(l)+"_x_out_i4.bin"),"dump");
        logits(b,0,"a");guard(b.feat,12*7938);guard(b.lg,16);
        auto a=read<int32_t>(golden()+"a/x_embed_i32.bin"),bb=read<int32_t>(golden()+"b/x_embed_i32.bin");
        std::vector<int32_t> in=a;in.insert(in.end(),bb.begin(),bb.end());in.insert(in.end(),a.begin(),a.end());
        auto xx=raw_input(in);Buffers batch(3,1);
        check(call(w,xx,batch,3,S2_RAW,0,11,715)==S2_OK,"A/B/A backpressure");
        logits(batch,0,"a");logits(batch,1,"b");logits(batch,2,"a");guard(batch.lg,48);guard(batch.feat,0);
        for (size_t i=3;i<batch.cls.size();i++) check(batch.cls[i]==0x9ac51e37u,"class guard");
        if (S2_P==2) check(batch.meta[5]>=2 && batch.meta[6]+batch.meta[7]>0,"P2 actual overlapping services");
        auto mid=raw_input(read<int32_t>(golden()+"a/L4_x_out_i4.bin"));Buffers resumed(1,7);
        check(call(w,mid,resumed,1,S2_RAW|S2_DUMP|S2_FEAT,5,11,19)==S2_OK,"continuation");
        for (int l=5;l<12;l++) block(resumed.feat,(l-5)*7938,read<int32_t>(golden()+"a/L"+std::to_string(l)+"_x_out_i4.bin"),"resumed layer");
        guard(resumed.lg,0);guard(resumed.feat,7*7938);
        Buffers timeout(1,1);check(call(w,x,timeout,1,0,0,11,0,1)==S2_TIMEOUT,"bounded timeout");
        guard(timeout.lg,0);guard(timeout.feat,0);
        Buffers again(1,1);check(call(w,x,again,1,S2_FEAT,0,0)==S2_OK,"reuse after timeout");
        block(again.feat,0,read<int32_t>(golden()+"a/L0_x_out_i4.bin"),"after timeout");
        if (mode=="stress") {
            auto hw=read<uint64_t>(golden()+"batch_hanchuan/weights_engine.bin");
            auto hx=read<uint64_t>("build/host/m3_s2_vectors/hanchuan_"+std::to_string(S2_NUM)+"_raw.bin");
            auto hl=read<int32_t>(golden()+"batch_hanchuan/expect_logits_i32.bin");
            auto hc=read<uint32_t>(golden()+"batch_hanchuan/expect_class_u32.bin");
            Buffers many(32,1);check(call(hw,hx,many,32,S2_LOAD|S2_RAW,0,11,32)==S2_OK,"32 distinct QAT/input regression");
            block(many.lg,0,hl,"32 logits");for (int k=0;k<32;k++) check(many.cls[k]==hc[k],"32 class");
            guard(many.lg,32*16);guard(many.feat,0);
        }
    }
    printf("S2_TEST_PASS mode=%s num=%d P=%d pack=%d native=%d\n",mode.c_str(),S2_NUM,S2_P,S2_PACK,S2_NATIVE);
    return 0;
}
