// Real PS numerics + unchanged driver; synthetic MMIO/CLASS, NEVER HLS/PL.
#include "system/m3a_roi.h"
#include "tt_net.h"
#include "tt_hw.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include <windows.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
static void need(bool ok, const char *s) { if(!ok) { std::printf("FAIL %s\n",s); std::exit(1); } }
// Link-only traps for unused legacy routines in tt_net.cpp. No M2 owner linked.
void tt_hw_proj_start(const int16_t *, int16_t *, int16_t *, int16_t *, int32_t *,
                      const int16_t *, const int16_t *, const int16_t *, int, int) {
    need(false, "forbidden legacy projection owner");
}
void tt_hw_proj_wait() { need(false, "forbidden legacy projection wait"); }
enum { W=9, H=5, ROW=18, TOTAL=W*H,
       IN_ALLOC=((16*TT_ENGINE_IN_STRIDE+4095)/4096+1)*4096,
       PATCH_ALLOC=((TT_ENGINE_PATCH_ELEMS*4+4095)/4096+1)*4096 };
alignas(64) static float cube[(H+6)*ROW*270], cls[TT_D], pos[TT_ENGINE_BLK_ELEMS];
alignas(4096) static unsigned char input_mem[IN_ALLOC], output_mem[4096], patch_mem[PATCH_ALLOC];
alignas(64) static unsigned char weights[TT_ENGINE_WPKG16_BYTES];
static TTM3aRoiResult results[TOTAL+2];
static TTM3aRoiRequest active;
static std::vector<std::vector<int16_t>> expected;
static std::vector<std::vector<float>> expected_patch;
static unsigned submitted, full_calls, cache_calls, setters, fail_call;
static bool busy, protected_pages;
static std::string failure;
static std::vector<unsigned> batches;
static struct {
    u32 x_in,cube,x_out,q_out,k_out,v_out,stats_out,w_ddr;
    u32 cube_w,seg_row,seg_col,n_patch,layer_lo,layer_hi,proj_mask,mode,ret,polls;
} reg;
static uint32_t packed(unsigned i) { return ((0x8000u+137u*i)<<16)|(i%9); }
static void protect(DWORD in, DWORD out, DWORD patch) {
    DWORD old;
    need(VirtualProtect(input_mem,sizeof(input_mem),in,&old)!=0,"protect input");
    need(VirtualProtect(output_mem,sizeof(output_mem),out,&old)!=0,"protect output");
    need(VirtualProtect(patch_mem,sizeof(patch_mem),patch,&old)!=0,"protect patch");
}
static void idle() { need(!busy,"MMIO/cache reuse while DMA pending"); }
int XTt_engine_Initialize(XTt_engine *,int) { idle(); return XST_SUCCESS; }
void XTt_engine_Start(XTt_engine *) {
    idle(); busy=true; reg.polls=0;
    reg.ret=(18u<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
    if(reg.mode&TT_ENGINE_MODE_LOAD_W) return; // Simulated load, no PL weights proof
    ++full_calls; batches.push_back(reg.n_patch);
    need(reg.mode==(TT_ENGINE_MODE_FULL|TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_CLASS)) &&
         reg.layer_lo==0 && reg.layer_hi==11,"serial full 12-layer CLASS contract");
    need(reg.x_in==(uintptr_t)active.input && reg.x_out==(uintptr_t)active.output,"DMA addresses");
    unsigned remaining=static_cast<unsigned>(expected.size())-submitted;
    need(reg.n_patch==(remaining<active.batch_size?remaining:active.batch_size),"bounded tail");
    for(unsigned i=0;i<reg.n_patch;++i) {
        const auto *p=reinterpret_cast<const unsigned char *>(active.input)+i*TT_ENGINE_IN_STRIDE;
        need(!std::memcmp(p,expected[submitted+i].data(),TT_ENGINE_IN_BYTES),"PS embed bitwise / coordinate mapping");
        for(unsigned j=TT_ENGINE_IN_BYTES;j<TT_ENGINE_IN_STRIDE;++j) need(p[j]==0,"input stride padding");
    }
    need(!std::memcmp(active.patch,expected_patch[submitted+reg.n_patch-1].data(),TT_ENGINE_PATCH_ELEMS*4),
         "normalized patch bitwise legacy PS path");
    auto *dst=static_cast<uint32_t *>(active.output);
    // Failed DMA dirties output too; failure must NOT commit those words.
    for(unsigned i=0;i<reg.n_patch;++i) dst[i]=packed(submitted+i);
    if(reg.n_patch%2) dst[reg.n_patch]=0; // CLASS writes a complete 64-bit word
    submitted+=reg.n_patch;
    if(full_calls==fail_call) {
        if(failure=="timeout") { protect(PAGE_READONLY,PAGE_NOACCESS,PAGE_READONLY); protected_pages=true; }
        else if(failure=="contract") reg.ret=(16u<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
        else reg.ret|=TT_ENGINE_ERR_NOWEIGHT;
    }
}
u32 XTt_engine_IsDone(XTt_engine *) { ++reg.polls; if(protected_pages) return 0; busy=false; return 1; }
u32 XTt_engine_Get_return(XTt_engine *) { idle(); return reg.ret; }
u32 XTt_engine_Get_cycles(XTt_engine *) { return 12345; } // OFFLINE SYNTHETIC CLOCK
#define SET(n) void XTt_engine_Set_##n(XTt_engine *,u32 v) { idle(); ++setters; reg.n=v; }
SET(x_in) SET(cube) SET(x_out) SET(q_out) SET(k_out) SET(v_out) SET(stats_out) SET(w_ddr)
SET(cube_w) SET(seg_row) SET(seg_col) SET(n_patch) SET(layer_lo) SET(layer_hi) SET(proj_mask) SET(mode)
void Xil_DCacheFlush() { need(false,"whole cache flush forbidden"); }
void Xil_DCacheFlushRange(INTPTR a,u32 n) { idle(); need(!(a&63)&&n&&!(n&63),"cache flush span"); ++cache_calls; }
void Xil_DCacheInvalidateRange(INTPTR a,u32 n) { idle(); need(!(a&63)&&n&&!(n&63),"cache invalidate span"); ++cache_calls; }
static TTM3aRoiRequest fixture() {
    std::memset(cube,0,sizeof(cube));
    for(unsigned y=0;y<H;++y) for(unsigned x=0;x<W;++x) for(unsigned c=0;c<270;++c)
        cube[((y+3)*ROW+x+3)*270+c]=(static_cast<int>((y*43+x*19+c*7)%101)-50)/37.0f;
    // Poison unused row padding to catch accidental square/packed indexing.
    for(unsigned y=0;y<H+6;++y) for(unsigned x=W+6;x<ROW;++x) for(unsigned c=0;c<270;++c)
        cube[(y*ROW+x)*270+c]=std::numeric_limits<float>::quiet_NaN();
    for(unsigned i=0;i<TT_D;++i) cls[i]=(static_cast<int>(i%13)-6)/128.0f;
    for(unsigned i=0;i<TT_ENGINE_BLK_ELEMS;++i) pos[i]=(static_cast<int>(i%17)-8)/256.0f;
    std::memset(input_mem,0xa5,sizeof(input_mem)); std::memset(output_mem,0xa5,sizeof(output_mem));
    std::memset(patch_mem,0xa5,sizeof(patch_mem)); std::memset(results,0xa5,sizeof(results));
    submitted=full_calls=0; batches.clear();
    return {cube,sizeof(cube),W,H,ROW,0,0,W,H,cls,TT_D,pos,TT_ENGINE_BLK_ELEMS,16,7,
            reinterpret_cast<float *>(patch_mem),TT_ENGINE_PATCH_ELEMS*4,
            reinterpret_cast<int16_t *>(input_mem),16*TT_ENGINE_IN_STRIDE,output_mem,64,results+1,TOTAL};
}
static void reference(const TTM3aRoiRequest &r) {
    active=r; expected.clear(); expected_patch.clear();
    const TTNet net={6,5,nullptr,cls,pos,nullptr,nullptr};
    for(unsigned y=r.y;y<r.y+r.roi_height;++y) for(unsigned x=r.x;x<r.x+r.roi_width;++x) {
        std::vector<float> patch(TT_ENGINE_PATCH_ELEMS);
        tt_patch_extract(r.cube,r.row_pixels,y,x,patch.data());
        // Independent double CHW/window + unbiased global std, not the mock.
        std::vector<double> raw; double sum=0,ss=0;
        for(unsigned c=0;c<270;++c) for(unsigned h=0;h<7;++h) for(unsigned w=0;w<7;++w) {
            double v=r.cube[((y+h)*r.row_pixels+x+w)*270+c]; raw.push_back(v); sum+=v;
        }
        double mean=sum/raw.size();
        for(double v:raw) ss+=(v-mean)*(v-mean);
        double stddev=std::sqrt(ss/(raw.size()-1));
        for(size_t i=0;i<raw.size();++i)
            need(std::fabs(patch[i]-(raw[i]-mean)/stddev)<2e-5,"independent normalized CHW reference");
        expected_patch.push_back(patch);
        std::vector<int16_t> embed(TT_ENGINE_BLK_ELEMS);
        tt_embed(net,patch.data(),embed.data()); expected.push_back(embed);
    }
}
static bool a5(const void *p,size_t n) {
    const auto *b=static_cast<const unsigned char *>(p);
    for(size_t i=0;i<n;++i) if(b[i]!=0xa5) return false;
    return true;
}
static void check_results(const TTM3aRoiRequest &r,size_t done) {
    for(size_t i=0;i<done;++i)
        need(r.results[i].x==r.x+i%r.roi_width && r.results[i].y==r.y+i/r.roi_width &&
             r.results[i].packed_class==packed(static_cast<unsigned>(i)),"committed coordinates/packed CLASS");
    need(a5(r.results+done,(TOTAL-done+1)*sizeof(TTM3aRoiResult)),"uncommitted suffix/result guard");
    need(a5(results,sizeof(results[0])),"result prefix guard");
}
static void success(TTM3aRoiRequest r) {
    reference(r); TTM3aRoiSession s{};
    TTMeasureRecord detail;
    {TTMeasureUse use(detail,[]()->uint64_t{static uint64_t t=0;return ++t;});
        need(tt_m3a_roi_run(s,r)==0 && !s.halted && s.completed==expected.size(),"ROI complete");}
    need(detail.valid&&detail.pixels==s.completed,"real numeric measurement scopes valid (synthetic clock)");
    for(unsigned k=TT_MEASURE_EXTRACT;k<=TT_MEASURE_EMBED;++k)need(detail.calls[k]==s.completed,"one extract/normalize/embed per submitted pixel");
    need(detail.pl_calls==(s.completed+r.batch_size-1)/r.batch_size,"PL invocation count not pixel count");
    check_results(r,s.completed);
    size_t n=expected.size()<r.batch_size?expected.size():r.batch_size;
    need(a5(input_mem+n*TT_ENGINE_IN_STRIDE,sizeof(input_mem)-n*TT_ENGINE_IN_STRIDE),"input guard");
    need(a5(output_mem+64,sizeof(output_mem)-64),"output cache-line guard");
    need(a5(patch_mem+TT_ENGINE_PATCH_ELEMS*4,sizeof(patch_mem)-TT_ENGINE_PATCH_ELEMS*4),"patch guard");
    need(batches.size()==(expected.size()+r.batch_size-1)/r.batch_size,"batch count");
}
static unsigned rejected;
static void reject(TTM3aRoiRequest r,int want,bool pristine=true) {
    unsigned before=cache_calls+setters+full_calls; TTM3aRoiSession s{};
    need(tt_m3a_roi_run(s,r)==want && !s.halted && !s.completed && !s.driver_status,"PS rejection status");
    need(before==cache_calls+setters+full_calls,"PS rejection no driver side effects");
    need(a5(results,sizeof(results)) && a5(output_mem,sizeof(output_mem)),"PS rejection no output writes");
    if(pristine) need(a5(input_mem,sizeof(input_mem)) && a5(patch_mem,sizeof(patch_mem)),"bad metadata no preparation");
    ++rejected;
}
static void invalids() {
    const auto good=fixture(); TTM3aRoiRequest r;
#define BAD(edit, code) r=good; edit; reject(r,code)
    BAD(r.width=0,TT_M3A_ROI_ARGUMENT); BAD(r.height=0,TT_M3A_ROI_ARGUMENT);
    BAD(r.width=UINT32_MAX,TT_M3A_ROI_ARGUMENT); BAD(r.row_pixels=UINT32_MAX,TT_M3A_ROI_ARGUMENT);
    BAD(r.row_pixels=W+5,TT_M3A_ROI_ARGUMENT); BAD(r.roi_width=0,TT_M3A_ROI_ARGUMENT);
    BAD(r.roi_height=0,TT_M3A_ROI_ARGUMENT); BAD(r.x=W,TT_M3A_ROI_ARGUMENT);
    BAD(r.y=H,TT_M3A_ROI_ARGUMENT); BAD(r.roi_width=UINT32_MAX,TT_M3A_ROI_ARGUMENT);
    BAD(r.roi_height=H+1,TT_M3A_ROI_ARGUMENT); BAD(r.batch_size=0,TT_M3A_ROI_ARGUMENT);
    BAD(r.batch_size=17,TT_M3A_ROI_ARGUMENT); BAD(r.max_polls=0,TT_M3A_ROI_ARGUMENT);
    BAD(--r.cube_bytes,TT_M3A_ROI_BUFFER); BAD(--r.cls_count,TT_M3A_ROI_BUFFER);
    BAD(--r.pos_count,TT_M3A_ROI_BUFFER); BAD(--r.patch_bytes,TT_M3A_ROI_BUFFER);
    BAD(--r.input_bytes,TT_M3A_ROI_BUFFER); BAD(--r.output_bytes,TT_M3A_ROI_BUFFER);
    BAD(--r.result_count,TT_M3A_ROI_BUFFER); BAD(r.cube=nullptr,TT_M3A_ROI_BUFFER);
    BAD(r.cls_token=nullptr,TT_M3A_ROI_BUFFER); BAD(r.pos_embed=nullptr,TT_M3A_ROI_BUFFER);
    BAD(r.patch=nullptr,TT_M3A_ROI_BUFFER); BAD(r.results=nullptr,TT_M3A_ROI_BUFFER);
    BAD(++r.input,TT_M3A_ROI_BUFFER); BAD(r.output=output_mem+4,TT_M3A_ROI_BUFFER);
    BAD(r.input=(int16_t *)(uintptr_t)0x100000000ull,TT_M3A_ROI_BUFFER);
    BAD(r.output=(void *)(uintptr_t)0x100000000ull,TT_M3A_ROI_BUFFER);
    BAD(r.input=(int16_t *)(uintptr_t)0xffffffc0ull,TT_M3A_ROI_BUFFER);
    BAD(r.cube=(float *)(UINTPTR_MAX-3),TT_M3A_ROI_BUFFER);
    BAD(r.width=r.height=2000000000u; r.row_pixels=2000000006u; r.cube_bytes=SIZE_MAX,TT_M3A_ROI_BUFFER);
    BAD(r.output=r.input,TT_M3A_ROI_BUFFER); BAD(r.patch=(float *)r.input,TT_M3A_ROI_BUFFER);
    BAD(r.patch=const_cast<float *>(r.cube),TT_M3A_ROI_BUFFER);
    BAD(r.results=(TTM3aRoiResult *)r.output,TT_M3A_ROI_BUFFER);
    BAD(r.results=(TTM3aRoiResult *)r.input,TT_M3A_ROI_BUFFER);
    BAD(r.results=(TTM3aRoiResult *)r.pos_embed,TT_M3A_ROI_BUFFER);
#undef BAD
    for(float v:{0.0f,0.1f,std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()}) {
        r=fixture(); for(float &e:cube) e=v; reject(r,TT_M3A_ROI_NUMERIC);
    }
    r=fixture(); cls[0]=std::numeric_limits<float>::infinity(); reject(r,TT_M3A_ROI_NUMERIC);
    r=fixture(); pos[0]=std::numeric_limits<float>::quiet_NaN(); reject(r,TT_M3A_ROI_NUMERIC);
    r=fixture(); pos[0]=1024.0f; cls[0]=0; reject(r,TT_M3A_ROI_NUMERIC,false);
    r=fixture(); for(size_t i=0;i<sizeof(cube)/4;++i) cube[i]=i%2?1e20f:-1e20f;
    reject(r,TT_M3A_ROI_NUMERIC,false);
    std::printf("PS_INVALID PASS cases=%u\n",rejected);
}
int main(int argc,char **argv) {
    const std::string mode=argc==2?argv[1]:"success";
    need((uintptr_t)input_mem<0x100000000ull && (uintptr_t)output_mem<0x100000000ull,"low DDR host link");
    if(mode!="not-ready") {
        need(tt_m3a_init()==0,"driver init");
        const uint32_t head[]={TT_ENGINE_WPKG_MAGIC,2,9,16}; std::memcpy(weights,head,sizeof(head));
        need(tt_m3a_load_weights(weights,sizeof(weights),7)==0,"synthetic resident weight setup");
    }
    if(mode=="success") {
        invalids(); success(fixture());
        auto r=fixture(); r.x=3; r.y=1; r.roi_width=5; r.roi_height=3; r.batch_size=4; success(r);
        r=fixture(); r.batch_size=3; success(r);
        r=fixture(); r.batch_size=1; success(r);
        for(unsigned y:{0u,H-1u}) for(unsigned x:{0u,W-1u}) {
            r=fixture(); r.x=x; r.y=y; r.roi_width=r.roi_height=1;
            r.input_bytes=TT_ENGINE_IN_STRIDE; r.result_count=1; success(r);
        }
        std::puts("PS_NUMERIC PASS independent CHW/std + bitwise legacy patch/embed; 8 ROI cases");
    } else if(mode=="numeric-prefix") {
        auto r=fixture(); r.roi_height=1; r.batch_size=3; reference(r);
        // Column 10 outside first batch windows (last reaches 8). Second batch
        // fails after preparing x=3 but before FULL is submitted.
        cube[(3*ROW+10)*270]=std::numeric_limits<float>::quiet_NaN(); TTM3aRoiSession s{};
        need(tt_m3a_roi_run(s,r)==TT_M3A_ROI_NUMERIC && s.completed==3 && !s.halted && full_calls==1,
             "numeric failure preserves prefix and skips entire failed batch");
        check_results(r,3);
    } else {
        need(mode=="timeout" || mode=="contract" || mode=="engine-error" || mode=="not-ready","known mode");
        auto r=fixture(); reference(r); TTM3aRoiSession s{}; failure=mode; fail_call=2;
        int want=mode=="timeout"?TT_M3A_TIMEOUT:mode=="contract"?TT_M3A_CONTRACT:
                 mode=="not-ready"?TT_M3A_NOT_READY:TT_M3A_ENGINE;
        need(tt_m3a_roi_run(s,r)==TT_M3A_ROI_DRIVER && s.driver_status==want && s.halted,"driver failure captured");
        need(s.completed==(mode=="not-ready"?0u:16u) && full_calls==(mode=="not-ready"?0u:2u),"failed batch not committed/no next batch");
        check_results(r,s.completed);
        unsigned effects=cache_calls+setters+full_calls;
        need(tt_m3a_roi_run(s,r)==TT_M3A_ROI_HALTED && effects==cache_calls+setters+full_calls,"sticky halt before preparation");
        if(mode=="timeout") {
            need(reg.polls==r.max_polls && protected_pages,"bounded poll, protected pending DMA");
            // Test-only simulated cancellation, NOT a production recovery API.
            busy=false; protected_pages=false; protect(PAGE_READWRITE,PAGE_READWRITE,PAGE_READWRITE);
        }
    }
    std::printf("M3A_ROI PASS (%s); synthetic transport only, NOT PL/board/performance\n",mode.c_str());
}
