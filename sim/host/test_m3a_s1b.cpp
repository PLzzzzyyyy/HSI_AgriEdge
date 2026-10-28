// Tests only S1b integration with real S1a/driver. Synthetic FatFs and MMIO.
#include "m3a_app.h"
#include "tt_net.h"
#include "ff.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
static void need(bool v,const char *m) { if (!v) { std::printf("FAIL %s\n",m); std::exit(1); } }
enum { W=40,H=30,CUBE_BYTES=(H+6)*(W+6)*270*4, IN_BYTES=4*TT_ENGINE_IN_STRIDE,
       IN_ALLOC=((IN_BYTES+4095)/4096)*4096, PATCH_ALLOC=((13230*4+4095)/4096)*4096,
       WEIGHT_ALLOC=((TT_ENGINE_WPKG16_BYTES+4095)/4096)*4096 };
alignas(4096) static unsigned char cube[CUBE_BYTES], cls[10584], pos[63504], weights[WEIGHT_ALLOC];
alignas(4096) static unsigned char input[IN_ALLOC], output[4096], patch[PATCH_ALLOC];
static TTM3aRoiResult results[15];
static std::vector<unsigned char> files[4];
static TTM3aSdProfile profile;
static TTM3aSdStorage storage;
static TTM3aRoiRequest request;
static TTM3aAppSession session;
static std::string mode;
static int target, mounts, opens, closes, reads, inits, loads, fulls, emitted;
static bool pending, pages;
static struct { u32 x_in,x_out,w_ddr,n_patch,layer_lo,layer_hi,mode,ret; } reg;
static uint32_t crc(const std::vector<unsigned char> &v) {
    uint32_t c=~0u;
    for (auto x:v) { c^=x; for (int j=0;j<8;++j) c=(c>>1)^((c&1)?0xedb88320u:0u); }
    return ~c;
}
static void protect(DWORD a,DWORD b,DWORD c,DWORD d) {
    DWORD old;
    need(VirtualProtect(input,sizeof(input),a,&old)!=0,"protect input");
    need(VirtualProtect(output,sizeof(output),b,&old)!=0,"protect output");
    need(VirtualProtect(patch,sizeof(patch),c,&old)!=0,"protect patch");
    need(VirtualProtect(weights,sizeof(weights),d,&old)!=0,"protect weights");
}
static void idle() { need(!pending,"no file/MMIO/cache access during pending DMA"); }
FRESULT f_mount(FATFS *fs,const char *path,BYTE now) {
    idle(); need(!std::strcmp(path,"1:/"),"SD1 path"); ++mounts;
    if (!fs) { need(now==0,"unregister"); return mode=="unmount"?FR_DISK_ERR:FR_OK; }
    need(now==1,"immediate mount"); return mode=="mount"||mode=="app-mount"?FR_DISK_ERR:FR_OK;
}
FRESULT f_open(FIL *f,const char *path,BYTE flags) {
    idle(); need(flags==FA_READ,"read only"); int i=opens++;
    need(i<4 && !std::strcmp(path,profile.files[i].path),"file order/profile");
    if (mode=="open" && i==target) return FR_NO_FILE;
    f->index=i; f->position=0; f->size=files[i].size();
    if (i==target && mode=="size-short") --f->size;
    if (i==target && mode=="size-long") ++f->size;
    if (i==target && mode=="size-wide") f->size+=UINT64_C(0x100000000);
    return FR_OK;
}
FRESULT f_read(FIL *f,void *dst,UINT want,UINT *got) {
    idle(); ++reads;
    need(want && want<=(1u<<20) && f->position+want<=files[f->index].size(),"bounded file read");
    *got=want;
    const bool fail=f->index==target && (target!=0 || f->position>0);
    if (fail && (mode=="short" || mode=="read-error")) *got=want/2;
    std::memcpy(dst,files[f->index].data()+f->position,*got); f->position+=*got;
    return fail && mode=="read-error"?FR_DISK_ERR:FR_OK;
}
FRESULT f_close(FIL *f) { idle(); ++closes; return mode=="close"&&f->index==target?FR_DISK_ERR:FR_OK; }
int XTt_engine_Initialize(XTt_engine *,int id) { idle(); ++inits; need(id==0,"device"); return mode=="init"?1:0; }
static uint32_t word(unsigned n) { return (0x8123u+n)<<16 | n%9; }
void XTt_engine_Start(XTt_engine *) {
    idle(); need(mounts==2 && closes==4 && session.sd.loaded,"verified and unmounted BEFORE DMA");
    reg.ret=(18u<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
    if (reg.mode==TT_ENGINE_MODE_LOAD_W) {
        ++loads;
        need(reg.w_ddr==(uintptr_t)weights,"weights address");
        need(!std::memcmp(weights,files[3].data(),files[3].size()),"loaded exact weight bytes");
    } else {
        ++fulls;
        need(reg.mode==(TT_ENGINE_MODE_FULL|TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_CLASS)) &&
             reg.layer_lo==0 && reg.layer_hi==11,"only serial FULL CLASS");
        need(reg.n_patch==static_cast<unsigned>(15-emitted<4?15-emitted:4),"batch tail");
        const TTNet net={6,5,nullptr,reinterpret_cast<float *>(cls),reinterpret_cast<float *>(pos),nullptr,nullptr};
        std::vector<float> p(13230); std::vector<int16_t> ref(15876);
        for (unsigned i=0;i<reg.n_patch;++i) {
            const unsigned n=static_cast<unsigned>(emitted)+i;
            tt_patch_extract(reinterpret_cast<float *>(cube),W+6,n/5,n%5,p.data());
            tt_embed(net,p.data(),ref.data());
            need(!std::memcmp(reinterpret_cast<void *>(uintptr_t(reg.x_in)+i*TT_ENGINE_IN_STRIDE),ref.data(),31752),
                 "ROI consumes loaded HWC/cls/pos");
            reinterpret_cast<uint32_t *>(uintptr_t(reg.x_out))[i]=word(n);
        }
        emitted+=reg.n_patch;
    }
    const bool load_fault=loads==1 && !fulls;
    const bool full_fault=fulls==2;
    if ((mode=="load-error" && load_fault) || (mode=="full-error" && full_fault)) reg.ret|=TT_ENGINE_ERR_NOWEIGHT;
    if ((mode=="load-timeout" && load_fault) || (mode=="full-timeout" && full_fault)) {
        pending=true; pages=true; protect(PAGE_READONLY,PAGE_NOACCESS,PAGE_READONLY,PAGE_READONLY);
    }
}
u32 XTt_engine_IsDone(XTt_engine *) { return pending?0:1; }
u32 XTt_engine_Get_return(XTt_engine *) { idle(); return reg.ret; }
u32 XTt_engine_Get_cycles(XTt_engine *) { return 12345; } // OFFLINE SYNTHETIC CLOCK
#define SET(n) void XTt_engine_Set_##n(XTt_engine *,u32 v) { idle(); reg.n=v; }
SET(x_in) SET(x_out) SET(w_ddr) SET(n_patch) SET(layer_lo) SET(layer_hi) SET(mode)
#define UNUSED(n) void XTt_engine_Set_##n(XTt_engine *,u32) { idle(); }
UNUSED(cube) UNUSED(q_out) UNUSED(k_out) UNUSED(v_out) UNUSED(stats_out)
UNUSED(cube_w) UNUSED(seg_row) UNUSED(seg_col) UNUSED(proj_mask)
void Xil_DCacheFlush() { need(false,"global flush"); }
void Xil_DCacheFlushRange(INTPTR a,u32 n) { idle(); need(!(a&63) && n && !(n&63),"flush span"); }
void Xil_DCacheInvalidateRange(INTPTR a,u32 n) { idle(); need(!(a&63) && n && !(n&63),"invalidate span"); }
static void fixture() {
    auto *c=reinterpret_cast<float *>(cube);
    for (unsigned y=0;y<H;++y) for (unsigned x=0;x<W;++x) for (unsigned k=0;k<270;++k)
        c[((y+3)*(W+6)+x+3)*270+k]=(static_cast<int>((y*17+x*13+k*7)%103)-51)/41.f;
    for (unsigned i=0;i<2646;++i) reinterpret_cast<float *>(cls)[i]=(int(i%13)-6)/128.f;
    for (unsigned i=0;i<15876;++i) reinterpret_cast<float *>(pos)[i]=(int(i%17)-8)/256.f;
    uint32_t h[]={TT_ENGINE_WPKG_MAGIC,2,9,16}; std::memcpy(weights,h,sizeof(h));
    profile={W,H,270,3,9,{{"1:/cube.bin",CUBE_BYTES,0},{"1:/cls.bin",10584,0},
             {"1:/pos.bin",63504,0},{"1:/weights.bin",TT_ENGINE_WPKG16_BYTES,0}}};
    storage={{{cube,sizeof(cube)},{cls,sizeof(cls)},{pos,sizeof(pos)},{weights,sizeof(weights)}}};
    for (unsigned i=0;i<4;++i) {
        const auto *p=static_cast<unsigned char *>(storage.files[i].data);
        files[i].assign(p,p+profile.files[i].bytes); profile.files[i].crc32=crc(files[i]);
        std::memset(storage.files[i].data,0xa5,storage.files[i].capacity);
    }
    std::memset(results,0xa5,sizeof(results));
    request={reinterpret_cast<float *>(cube),sizeof(cube),W,H,W+6,0,0,5,3,
        reinterpret_cast<float *>(cls),2646,reinterpret_cast<float *>(pos),15876,4,3,
        reinterpret_cast<float *>(patch),sizeof(patch),reinterpret_cast<int16_t *>(input),sizeof(input),
        output,sizeof(output),results,15};
}
int s1b_prepared_main();
int main(int argc,char **argv) {
    need(argc>=2,"mode"); mode=argv[1]; target=argc>2?std::atoi(argv[2]):0; fixture();
    if (mode=="app-mount") {
        need(s1b_prepared_main()==1,"actual prepared main returns nonzero on safe SD failure");
        need(inits==0 && mounts==2,"actual main no hardware start after failure");
        std::puts("S1B PASS app-mount (HOST MOCK ONLY)"); return 0;
    }
    if (mode=="capacity") storage.files[target].capacity=profile.files[target].bytes-1;
    if (mode=="align") storage.files[target].data=static_cast<unsigned char *>(storage.files[target].data)+1;
    if (mode=="alias") storage.files[1].data=cube;
    if (mode=="high") storage.files[3].data=reinterpret_cast<void *>(UINT64_C(0x100000000));
    if (mode=="overflow") profile.height=0xffffffffu;
    if (mode=="shape") profile.bands=272;
    if (mode=="pad") profile.pad=0;
    if (mode=="profile-size") --profile.files[target].bytes;
    if (mode=="mismatch") request.cube=reinterpret_cast<float *>(cls);
    if (mode=="crc") files[target][files[target].size()/2]^=1;
    if (mode=="header") { files[3][target*4]^=1; profile.files[3].crc32=crc(files[3]); }
    if (mode!="mismatch") {
        request.cube=static_cast<float *>(storage.files[0].data);
        request.cls_token=static_cast<float *>(storage.files[1].data);
        request.pos_embed=static_cast<float *>(storage.files[2].data);
        request.cube_bytes=profile.files[0].bytes;
    }
    const int rc=tt_m3a_app_once(session,profile,storage,request);
    const bool full_fault=mode=="full-error"||mode=="full-timeout";
    const bool hw_fault=full_fault||mode=="load-error"||mode=="load-timeout"||mode=="init";
    size_t completed=0;
    if (mode=="success") {
        need(rc==0 && session.sd.loaded && fulls==4 && loads==1,"success"); completed=15;
    } else if (hw_fault) {
        need(rc==TT_M3A_ROI_DRIVER && session.roi.halted,"driver error latch");
        completed=full_fault?4:0;
        need(fulls==(full_fault?2:0),"no third batch");
        need(session.driver_status==(mode.find("timeout")!=std::string::npos?TT_M3A_TIMEOUT:
             mode=="init"?TT_M3A_INIT:TT_M3A_ENGINE),"original driver error");
    } else {
        need(rc!=0 && !session.sd.loaded && !inits && !loads && !fulls,"failed SD never reaches driver");
        if (mode=="short") need(rc==TT_M3A_SD_SHORT,"FR_OK short read rejected");
        if (mode=="crc") need(rc==TT_M3A_SD_CRC,"same-size corrupt data rejected");
        if (mode=="header") need(rc==TT_M3A_SD_FORMAT,"header rejected despite matching CRC");
        if (mode=="mount") need(mounts==2 && !opens,"unregister failed mount");
        if (mode=="open") need(closes==target,"close opened files only");
        if (mode=="short"||mode=="read-error"||mode=="close"||mode.find("size-")==0||mode=="crc")
            need(closes==target+1 && mounts==2,"cleanup and stop on current file");
        if (mode=="capacity"||mode=="align"||mode=="alias"||mode=="high"||mode=="overflow"||
            mode=="shape"||mode=="pad"||mode=="profile-size"||mode=="mismatch")
            need(!mounts && !reads,"reject metadata before SD/destination writes");
    }
    need(session.roi.completed==completed,"committed prefix count");
    for (size_t i=0;i<15;++i) {
        if (i<completed) need(results[i].x==i%5 && results[i].y==i/5 && results[i].packed_class==word(i),"prefix words/coords");
        else need(results[i].x==0xa5a5a5a5 && results[i].packed_class==0xa5a5a5a5,"failed suffix untouched");
    }
    const int io=reads+mounts+opens+closes, hw=loads+fulls+inits;
    need(tt_m3a_app_once(session,profile,storage,request)==TT_M3A_ROI_HALTED,"no second app attempt");
    need(io==reads+mounts+opens+closes && hw==loads+fulls+inits,"no reload or DMA reuse");
    if (pages) protect(PAGE_READWRITE,PAGE_READWRITE,PAGE_READWRITE,PAGE_READWRITE); // test teardown ONLY
    std::printf("S1B PASS %s target=%d rc=%d completed=%lu (HOST MOCK ONLY)\n",mode.c_str(),target,rc,(unsigned long)completed);
}
