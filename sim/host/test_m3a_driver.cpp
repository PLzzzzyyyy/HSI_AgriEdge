// Real M3a driver -> instrumented registers/cache -> HLS C model.
// Reproduce with tools/test_m3a_driver.py. Static DMA buffers must be below 4GiB.
#include "tt_m3a.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include "../../src/hls/tt_engine.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
static unsigned starts, setters, flushes, invalidates;
static bool timeout, fake;
static uint32_t forced;
static uint32_t synthetic_cycles=12345;
static uint64_t synthetic_now=0;
static uint64_t clock_us(){return ++synthetic_now;}
static struct {
    u32 x_in,cube,x_out,q_out,k_out,v_out,stats_out,w_ddr;
    u32 cube_w,seg_row,seg_col,n_patch,layer_lo,layer_hi,proj_mask,mode,ret,polls;
    bool busy;
} r;
static void need(bool b,const char *s) { if(!b) { std::printf("FAIL %s\n",s); std::exit(1); } }
static void idle() { need(!r.busy,"register/cache access during DMA"); }
int XTt_engine_Initialize(XTt_engine *,int) { idle(); return XST_SUCCESS; }
void XTt_engine_Start(XTt_engine *) { idle(); ++starts; r.polls=0; r.busy=true; }
u32 XTt_engine_IsDone(XTt_engine *) {
    ++r.polls;
    if(timeout || r.polls==1) return 0;
    unsigned cycles=0;
    if(forced) r.ret=forced;
    else if(fake) r.ret=(18u<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
    else r.ret=tt_engine((const u64 *)(uintptr_t)r.x_in,(const u64 *)(uintptr_t)r.cube,
        (u64 *)(uintptr_t)r.x_out,(u64 *)(uintptr_t)r.q_out,(u64 *)(uintptr_t)r.k_out,
        (u64 *)(uintptr_t)r.v_out,(u64 *)(uintptr_t)r.stats_out,(const u64 *)(uintptr_t)r.w_ddr,
        r.cube_w,r.seg_row,r.seg_col,r.n_patch,r.layer_lo,r.layer_hi,r.proj_mask,r.mode,&cycles);
    r.busy=false; return 1;
}
u32 XTt_engine_Get_return(XTt_engine *) { idle(); return r.ret; }
u32 XTt_engine_Get_cycles(XTt_engine *) { idle();return synthetic_cycles; } // OFFLINE SYNTHETIC CLOCK
#define SET(n) void XTt_engine_Set_##n(XTt_engine *,u32 v) { idle(); ++setters; r.n=v; }
SET(x_in) SET(cube) SET(x_out) SET(q_out) SET(k_out) SET(v_out) SET(stats_out) SET(w_ddr)
SET(cube_w) SET(seg_row) SET(seg_col) SET(n_patch) SET(layer_lo) SET(layer_hi) SET(proj_mask) SET(mode)
void Xil_DCacheFlush() { need(false,"whole-cache flush forbidden"); }
void Xil_DCacheFlushRange(INTPTR a,u32 n) { idle(); need(!(a&63)&&n&&!(n&63),"flush span"); ++flushes; }
void Xil_DCacheInvalidateRange(INTPTR a,u32 n) { idle(); need(!(a&63)&&n&&!(n&63),"invalidate span"); ++invalidates; }
alignas(64) static unsigned char weights[TT_ENGINE_WPKG16_BYTES];
alignas(64) static int16_t inputs[3*TT_ENGINE_IN_STRIDE/2];
alignas(64) static unsigned char output[12*TT_ENGINE_OUT32_STRIDE+64];
static std::string root() {
    std::string s=__FILE__; for(char &c:s) if(c=='\\') c='/';
    auto p=s.rfind("/sim/host/"); need(p!=std::string::npos,"absolute test source path");
    return s.substr(0,p)+"/sim/golden/n6_engine/";
}
template<class T> static std::vector<T> load(const std::string &n,size_t count) {
    std::vector<T> v(count); FILE *f=std::fopen((root()+n).c_str(),"rb"); need(f!=nullptr,"golden open");
    need(std::fread(v.data(),sizeof(T),count,f)==count&&std::fgetc(f)==EOF,"golden size"); std::fclose(f); return v;
}
static void put(unsigned i,const std::vector<int32_t> &v) {
    for(size_t e=0;e<v.size();++e) { need(v[e]>=-32768&&v[e]<=32767,"input int16 range"); inputs[i*TT_ENGINE_IN_STRIDE/2+e]=(int16_t)v[e]; }
}
static bool equal(size_t off,const std::vector<int32_t> &v) { return !std::memcmp(output+off,v.data(),v.size()*4); }
static void guard(size_t from) { for(size_t i=from;i<sizeof(output);++i) need(output[i]==0xa5,"output guard"); }
static void reject(const TTM3aJob &j,int code,uint32_t polls=20) {
    unsigned s=setters,st=starts,f=flushes,i=invalidates;
    need(tt_m3a_run(j,polls)==code,"reject code");
    need(s==setters&&st==starts&&f==flushes&&i==invalidates,"rejected request side effects");
}
int main(int argc,char **argv) {
    need(tt_m3a_decode_clock(33333000,0x13000,0,0x01010402,2)==199998000,"PS configured divider frequency");
    need(!tt_m3a_decode_clock(33333000,0x13008,0,0x01010402,2),"PLL bypass is not nominal frequency");
    need(!tt_m3a_decode_clock(33333000,0x13000,0x80000000,0x01010402,2),"fractional PLL rejected");
    need(!tt_m3a_decode_clock(33333000,0x13000,0,0x01010802,2),"wrong PL divider rejected");
    const std::string mode=argc==2?argv[1]:"full";
    need((uintptr_t)weights<UINT64_C(0x100000000)&&(uintptr_t)output<UINT64_C(0x100000000),"low DDR link");
    auto pkg=load<unsigned char>("weights_engine.bin",sizeof(weights)); std::memcpy(weights,pkg.data(),sizeof(weights));
    TTM3aJob j={inputs,sizeof(inputs),output,sizeof(output),3,0,11,TT_ENGINE_OUT_LOGITS,false};
    reject(j,TT_M3A_NOT_READY);
    need(tt_m3a_output_bytes(3,0,11,TT_ENGINE_OUT_CLASS,false)==64,"odd CLASS cache span");
    need(tt_m3a_output_bytes(3,0,11,TT_ENGINE_OUT_LOGITS,false)==384,"LOGITS span");
    need(tt_m3a_output_bytes(2,5,11,TT_ENGINE_OUT_FEAT,true)==14*TT_ENGINE_OUT32_STRIDE,"DUMP span");
    need(tt_m3a_output_bytes(65535,0,11,TT_ENGINE_OUT_FEAT,true)==0,"DUMP overflow");
    need(tt_m3a_init()==0&&tt_m3a_init()==0,"init idempotent"); need(tt_m3a_init(1)==TT_M3A_ARGUMENT,"device switch");
    reject(j,TT_M3A_NOT_READY);
    need(tt_m3a_load_weights(weights,sizeof(weights)-1,20)==TT_M3A_ARGUMENT,"short package");
    need(tt_m3a_load_weights(weights,sizeof(weights),0)==TT_M3A_ARGUMENT,"zero polls");
    need(tt_m3a_load_weights(weights+1,sizeof(weights),20)==TT_M3A_BUFFER,"unaligned package");
    weights[0]^=1; need(tt_m3a_load_weights(weights,sizeof(weights),20)==TT_M3A_ARGUMENT,"magic"); weights[0]^=1;
    weights[4]=3; need(tt_m3a_load_weights(weights,sizeof(weights),20)==TT_M3A_ARGUMENT,"package version"); weights[4]=2;
    weights[12]=8; need(tt_m3a_load_weights(weights,sizeof(weights),20)==TT_M3A_ARGUMENT,"int8 package"); weights[12]=16;
    need(!starts&&!setters&&!flushes,"bad load side effects");
    const unsigned char ncls=weights[8];
    weights[8]=0; need(tt_m3a_load_weights(weights,sizeof(weights),20)==TT_M3A_ARGUMENT,"zero classes"); weights[8]=ncls;
    fake=mode!="full";
    if(mode=="load-contract") {
        forced=(16u<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
        need(tt_m3a_load_weights(weights,sizeof(weights),20)==TT_M3A_CONTRACT,"reject M2 at LOAD_W");
        reject(j,TT_M3A_RESET_REQUIRED);
        std::puts("M3A_DRIVER PASS (load-contract)"); return 0;
    }
    if(mode=="load-timeout") {
        timeout=true;
        need(tt_m3a_load_weights(weights,sizeof(weights),3)==TT_M3A_TIMEOUT&&r.polls==3,"LOAD_W timeout");
        reject(j,TT_M3A_RESET_REQUIRED);
        need(tt_m3a_init()==TT_M3A_RESET_REQUIRED,"LOAD_W timeout cannot re-init");
        std::puts("M3A_DRIVER PASS (load-timeout)"); return 0;
    }
    need(tt_m3a_load_weights(weights,sizeof(weights),20)==0,"load M3 weights");
    TTM3aJob b=j; b.output_capacity=383; reject(b,TT_M3A_BUFFER);
    b=j; b.input_capacity=3*TT_ENGINE_IN_STRIDE-1; reject(b,TT_M3A_BUFFER);
    b=j; b.output=output+1; reject(b,TT_M3A_BUFFER);
    b=j; b.input=nullptr; reject(b,TT_M3A_BUFFER);
    b=j; b.output=inputs; reject(b,TT_M3A_BUFFER);
    b=j; b.input=(const int16_t *)(uintptr_t)UINT64_C(0x100000000); reject(b,TT_M3A_BUFFER);
    b=j; b.output=(void *)(uintptr_t)UINT64_C(0xffffffc0); reject(b,TT_M3A_BUFFER);
    b=j; b.n_patch=0; reject(b,TT_M3A_ARGUMENT);
    b=j; b.n_patch=TT_ENGINE_NPATCH_MAX+1; reject(b,TT_M3A_ARGUMENT);
    b=j; b.layer_lo=12; reject(b,TT_M3A_ARGUMENT);
    b=j; b.layer_hi=10; reject(b,TT_M3A_ARGUMENT);
    b=j; b.output_kind=4; reject(b,TT_M3A_ARGUMENT);
    b=j; b.output_kind=TT_ENGINE_OUT_ATTENTION;b.output_capacity=1919;reject(b,TT_M3A_BUFFER);
    b=j; b.output_kind=TT_ENGINE_OUT_ATTENTION;b.layer_lo=1;reject(b,TT_M3A_ARGUMENT);
    b=j; b.dump=true; reject(b,TT_M3A_ARGUMENT); reject(j,TT_M3A_ARGUMENT,0);
    std::puts("PASS shape/address/capacity/overlap guards before DMA/cache");
    if(mode=="timeout") {
        timeout=true; unsigned inv=invalidates;
        need(tt_m3a_run(j,3)==TT_M3A_TIMEOUT&&r.polls==3,"bounded timeout");
        need(invalidates==inv,"do not invalidate in-flight DMA"); reject(j,TT_M3A_RESET_REQUIRED);
        need(tt_m3a_init()==TT_M3A_RESET_REQUIRED,"timeout re-init rejected");
        need(tt_m3a_load_weights(weights,sizeof(weights),20)==TT_M3A_RESET_REQUIRED,"timeout reload rejected");
    } else if(mode=="cycles-zero"||mode=="cycles-overflow") {
        fake=true;synthetic_cycles=mode=="cycles-zero"?0:UINT32_MAX;const unsigned inv=invalidates;
        need(tt_m3a_run(j,20)==TT_M3A_CONTRACT,"missing/overflow real counter rejected");
        need(!tt_m3a_last_cycles()&&inv==invalidates,"no stale measurement or failed DMA read");
        reject(j,TT_M3A_RESET_REQUIRED);
    } else if(mode=="contract"||mode=="engine-error") {
        forced=((mode=="contract"?16u:18u)<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
        if(mode=="engine-error") forced|=TT_ENGINE_ERR_MODE;
        need(tt_m3a_run(j,20)==(mode=="contract"?TT_M3A_CONTRACT:TT_M3A_ENGINE),"return checked");
        reject(j,mode=="contract"?TT_M3A_RESET_REQUIRED:TT_M3A_NOT_READY);
    } else {
        need(mode=="full","known mode");
        auto a=load<int16_t>("a/x_in_i16.bin",TT_ENGINE_BLK_ELEMS);
        put(0,std::vector<int32_t>(a.begin(),a.end())); put(2,std::vector<int32_t>(a.begin(),a.end()));
        put(1,load<int32_t>("b/x_embed_i32.bin",TT_ENGINE_BLK_ELEMS));
        std::memset(output,0xa5,sizeof(output)); need(tt_m3a_run(j,20)==0,"LOGITS");
        auto la=load<int32_t>("a/logits_q16_i32.bin",32),lb=load<int32_t>("b/logits_q16_i32.bin",32);
        need(equal(0,la)&&equal(128,lb)&&equal(256,la),"LOGITS bit-exact"); guard(384); std::puts("PASS LOGITS batch A/B/A");
        j.output_kind=TT_ENGINE_OUT_CLASS; std::memset(output,0xa5,sizeof(output)); need(tt_m3a_run(j,20)==0,"CLASS");
        uint32_t cls[4]; std::memcpy(cls,output,sizeof(cls));
        auto ca=load<uint32_t>("a/class_u32.bin",1)[0],cb=load<uint32_t>("b/class_u32.bin",1)[0];
        need(cls[0]==ca&&cls[1]==cb&&cls[2]==ca&&cls[3]==0,"CLASS confidence/odd tail"); guard(16); std::puts("PASS CLASS confidence + odd tail");
        j.n_patch=1; j.output_kind=TT_ENGINE_OUT_FEAT; j.dump=true;
        std::memset(output,0xa5,sizeof(output)); need(tt_m3a_run(j,20)==0,"DUMP");
        for(unsigned l=0;l<12;++l) {
            need(equal(l*TT_ENGINE_OUT32_STRIDE,load<int32_t>("a/L"+std::to_string(l)+"_x_out_i4.bin",TT_ENGINE_BLK_ELEMS)),"DUMP layer");
            std::printf("PASS DUMP layer %u\n",l);
        }
        guard(12*TT_ENGINE_OUT32_STRIDE);
        put(0,load<int32_t>("a/L4_x_out_i4.bin",TT_ENGINE_BLK_ELEMS)); j.layer_lo=5; j.dump=false;
        std::memset(output,0xa5,sizeof(output)); need(tt_m3a_run(j,20)==0,"resume");
        need(equal(0,load<int32_t>("a/L11_x_out_i4.bin",TT_ENGINE_BLK_ELEMS)),"resume FEAT"); guard(TT_ENGINE_OUT32_BYTES);
        need(starts==5&&flushes==9&&invalidates==4,"cache lifecycle"); std::puts("PASS FEAT layer5..11 and cache lifecycle");
        put(0,std::vector<int32_t>(a.begin(),a.end()));j.layer_lo=0;j.output_kind=TT_ENGINE_OUT_ATTENTION;
        std::memset(output,0xa5,sizeof(output));TTMeasureRecord measured;
        {TTMeasureUse use(measured,clock_us);need(tt_m3a_run(j,20)==0,"ATTENTION real driver and HLS C");}
        need(measured.valid&&measured.pl_cycles==12345&&measured.pl_calls==1&&measured.pixels==1,"synthetic PL counter propagation");
        need(measured.calls[TT_MEASURE_WAIT]==1&&measured.calls[TT_MEASURE_SUBMIT]==2&&
             measured.calls[TT_MEASURE_CACHE_PREPARE]==1&&measured.calls[TT_MEASURE_CACHE_COMPLETE]==1,"disjoint driver phases");
        uint32_t h[16];std::memcpy(h,output,64);
        need(h[0]==TT_ENGINE_ATTN_MAGIC&&h[1]==4&&h[2]==ca&&h[4]==12&&h[5]==6&&h[6]==24&&h[7]==432,"attention header");
        need(equal(64,la),"attention LOGITS exact");
        for(unsigned l=0;l<12;++l)need(equal(TT_ENGINE_ATTN_OFFSET+l*144,load<int32_t>("a/L"+std::to_string(l)+"_attn_i4.bin",36)),"attention 12x6x6 exact");
        guard(TT_ENGINE_ATTN_STRIDE);std::puts("PASS ATTENTION full DMA/cache/guard + exact 432 Q0.24, synthetic timing NOT hardware");
    }
    std::printf("M3A_DRIVER PASS (%s)\n",mode.c_str()); return 0;
}
