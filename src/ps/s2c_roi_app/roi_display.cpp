// Hardware procedures below are copied verbatim from frozen periph_dp.cpp.
// Private App only; no edits to C3, BSP, old M3a driver, interrupt controller or UDP.
#include "roi_display.h"
#include "roi_models.h"
#include <cstring>
#include "xparameters.h"
#include "xil_cache.h"
#include "sleep.h"
#include "xdpdma.h"
#include "xdppsu.h"
#include "xavbuf.h"
#include "xavbuf_clk.h"
#include "xtime_l.h"
namespace {
constexpr u32 W=s2c::DISPLAY_W,H=s2c::DISPLAY_H,STRIDE=W*4,FRAME_BYTES=STRIDE*H;
u32 g_frame[W*H] __attribute__((aligned(256)));
XDpPsu g_dp; XAVBuf g_avbuf; XDpDma g_dma; XDpDma_FrameBuffer g_fb;
bool g_started=false;
void (*g_key_service)()=nullptr;
s2c::SceneCanvas g_scene;
static_assert(STRIDE%256==0,"DP stride");
bool init_subsystem() {
#ifdef SDT
    // SDT LookupConfig matches physical base addresses, not legacy device IDs.
    XDpPsu_Config *cfg = XDpPsu_LookupConfig(XPAR_XDPPSU_0_BASEADDR);
    XDpDma_Config *dcfg = XDpDma_LookupConfig(XPAR_XDPDMA_0_BASEADDR);
#else
    XDpPsu_Config *cfg = XDpPsu_LookupConfig(XPAR_PSU_DP_DEVICE_ID);
    XDpDma_Config *dcfg = XDpDma_LookupConfig(XPAR_XDPDMA_0_DEVICE_ID);
#endif
    if (cfg == nullptr || dcfg == nullptr) return false;
    XDpPsu_CfgInitialize(&g_dp, cfg, cfg->BaseAddr);
#ifdef SDT
    /* 2026.1 SDT BSP：XAVBuf_CfgInitialize 去掉了第三参 DeviceId（xavbuf.h 的 #ifndef SDT 分支）。 */
    XAVBuf_CfgInitialize(&g_avbuf, g_dp.Config.BaseAddr);
#else
    XAVBuf_CfgInitialize(&g_avbuf, g_dp.Config.BaseAddr, XPAR_PSU_DP_DEVICE_ID);
#endif
    XDpDma_CfgInitialize(&g_dma, dcfg);
    if (XDpPsu_InitializeTx(&g_dp) != XST_SUCCESS) return false;
    if (XDpDma_SetGraphicsFormat(&g_dma, RGBA8888) != XST_SUCCESS) return false;
    if (XAVBuf_SetInputNonLiveGraphicsFormat(&g_avbuf, RGBA8888) != XST_SUCCESS) return false;
    XDpDma_SetQOS(&g_dma, 11);
    XAVBuf_EnableGraphicsBuffers(&g_avbuf, 1);
    XAVBuf_SetOutputVideoFormat(&g_avbuf, RGB_8BPC);
    XAVBuf_InputVideoSelect(&g_avbuf, XAVBUF_VIDSTREAM1_NONE, XAVBUF_VIDSTREAM2_NONLIVE_GFX);
    XAVBuf_ConfigureGraphicsPipeline(&g_avbuf);
    XAVBuf_ConfigureOutputVideo(&g_avbuf);
    XAVBuf_SetBlenderAlpha(&g_avbuf, 0, 0);   // 用像素 alpha（全 0xFF）
    XDpPsu_CfgMsaEnSynchClkMode(&g_dp, 0);
    XAVBuf_SetAudioVideoClkSrc(&g_avbuf, XAVBUF_PS_CLK, XAVBUF_PS_CLK);
    XAVBuf_SoftReset(&g_avbuf);
    return true;
}

u32 train() {
    XDpPsu_LinkConfig *lc = &g_dp.LinkConfig;
    u32 s = XDpPsu_GetRxCapabilities(&g_dp);
    if (s != XST_SUCCESS) return s;
    s = XDpPsu_SetEnhancedFrameMode(&g_dp, lc->SupportEnhancedFramingMode ? 1 : 0);
    if (s == XST_SUCCESS) s = XDpPsu_SetLaneCount(&g_dp, lc->MaxLaneCount);
    if (s == XST_SUCCESS) s = XDpPsu_SetLinkRate(&g_dp, lc->MaxLinkRate);
    if (s == XST_SUCCESS) s = XDpPsu_SetDownspread(&g_dp, lc->SupportDownspreadControl);
    if (s == XST_SUCCESS) s = XDpPsu_EstablishLink(&g_dp);
    return s;
}

void setup_video_stream() {
    XDpPsu_SetColorEncode(&g_dp, XDPPSU_CENC_RGB);
    XDpPsu_CfgMsaSetBpc(&g_dp, XVIDC_BPC_8);
    XDpPsu_CfgMsaUseStandardVideoMode(&g_dp, XVIDC_VM_1920x1080_60_P);
    XAVBuf_SetPixelClock(g_dp.MsaConfig.PixelClockHz);
    XDpPsu_WriteReg(g_dp.Config.BaseAddr, XDPPSU_SOFT_RESET, 0x1);
    usleep(10);
    XDpPsu_WriteReg(g_dp.Config.BaseAddr, XDPPSU_SOFT_RESET, 0x0);
    XDpPsu_SetMsaValues(&g_dp);
    XDpPsu_WriteReg(g_dp.Config.BaseAddr, 0xB124, 0x3);   // AV_BUF_SRST_REG，与例程相同
    usleep(10);
    XDpPsu_WriteReg(g_dp.Config.BaseAddr, 0xB124, 0x0);
    XDpPsu_EnableMainLink(&g_dp, 1);
}

// 例程在 VSync 中断里做 SetupChannel + 使能 + 触发；这里视频流起来后前台做一次，中间 flush 描述符。
// 重试时先关通道（驱动内部先暂停、等未完成传输，有超时）。
void start_gfx_dma() {
    XDpDma_SetChannelState(&g_dma, GraphicsChan, XDPDMA_DISABLE);
    g_fb.Address = (INTPTR)g_frame;
    g_fb.Stride = STRIDE;
    g_fb.LineSize = STRIDE;
    g_fb.Size = FRAME_BYTES;
    XDpDma_DisplayGfxFrameBuffer(&g_dma, &g_fb);
    XDpDma_SetupChannel(&g_dma, GraphicsChan);
    Xil_DCacheFlushRange((INTPTR)&g_dma, sizeof g_dma);
    XDpDma_SetChannelState(&g_dma, GraphicsChan, XDPDMA_ENABLE);
    XDpDma_Trigger(&g_dma, GraphicsChan);
}

}
namespace s2c {
void display_key_service(void (*service)()){g_key_service=service;}
bool display_scene_keys(uint32_t id,unsigned state,unsigned code) {
    if(!g_started||!g_scene.keys(id,state,code))return false;
    for(unsigned y=1046;y<1076;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),1800*4);
    return true;
}
bool display_scene_dispatch(const DispatchView &v) {
    if(!g_started||!g_scene.dispatch(v))return false;
    for(unsigned y=8;y<56;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+1490),410*4);
    for(unsigned y=650;y<866;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    return true;
}
unsigned display_mirror(uint32_t request,uint32_t offset,uint8_t *out,unsigned capacity,uint32_t &total,uint32_t &crc) {
    static uint8_t encoded[W*H*4];static uint32_t frame_id=0,size=0,checksum=0;
    if(!g_started||!request||!out)return 0;
    if(request!=frame_id) {
        if(offset)return 0;
        size=0;uint16_t previous=0,run=0;
        auto write=[&](){encoded[size++]=uint8_t(run);encoded[size++]=uint8_t(run>>8);encoded[size++]=uint8_t(previous);encoded[size++]=uint8_t(previous>>8);};
        for(unsigned i=0;i<W*H;++i){if((i&8191)==0&&g_key_service)g_key_service();
            const uint32_t p=g_frame[i];const uint16_t rgb=uint16_t(((p&255)>>3)<<11|(((p>>8)&255)>>2)<<5|(((p>>16)&255)>>3));
            if(run&&rgb==previous&&run<65535)++run;else{if(run)write();previous=rgb;run=1;}}
        if(run)write();
        uint32_t running=0xffffffffu;
        for(uint32_t offset=0;offset<size;offset+=16384){
            if(g_key_service)g_key_service();
            const size_t count=size-offset>16384?16384:size-offset;
            running=model_crc_update(running,encoded+offset,count);
        }
        checksum=running^0xffffffffu;frame_id=request;
    }
    if(offset>=size)return 0;
    total=size;crc=checksum;const unsigned count=size-offset<capacity?size-offset:capacity;std::memcpy(out,encoded+offset,count);return count;
}
bool display_scene_begin(const DisplayView &view) {
    if(!g_started || !g_scene.begin(g_frame,W*H,view))return false;
    Xil_DCacheFlushRange((INTPTR)g_frame,FRAME_BYTES);return true;
}
bool display_scene_append(unsigned row,unsigned col,unsigned n,const uint32_t *words) {
    if(!g_started || !g_scene.append(row,col,n,words))return false;
    const unsigned y=g_scene.row_y(row),h=g_scene.row_height(row);
    if(h)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W),h*STRIDE);
    return true;
}
bool display_scene_update(const DisplayView &view) {
    if(!g_started || !g_scene.update(view))return false;
    // The same framebuffer stays on scanout. Never restart DP/DPDMA per row.
    for(unsigned y=80;y<1040;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+1240),650*4);
    for(unsigned y=488;y<608;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+104),280*4);
    for(unsigned y=650;y<866;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    for(unsigned y=878;y<925;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    return true;
}
bool display_scene_probe(const ProbeView &view) {
    if(!g_started || !g_scene.probe(view))return false;
    // The probe card is left of the map, outside the task-panel flush above.
    for(unsigned y=s2c::PROBE_PANEL_Y;y<s2c::PROBE_PANEL_Y+s2c::PROBE_PANEL_H;++y)
        Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+s2c::PROBE_PANEL_X),s2c::PROBE_PANEL_W*4);
    for(unsigned y=g_scene.map_y();y<g_scene.map_y()+g_scene.map_height();++y)
        Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+g_scene.map_x()),g_scene.map_width()*4);
    return true;
}
bool display_scene_connection(PeerState state,unsigned age_seconds) {
    if(!g_started||!g_scene.connection(state,age_seconds))return false;
    for(unsigned y=8;y<56;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+1490),410*4);
    for(unsigned y=650;y<866;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    return true;
}
bool display_scene_parcel(const ParcelView &v,uint64_t now) {
    if(!g_started||!g_scene.parcel(v,now))return false;
    for(unsigned y=350;y<1040;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+1240),650*4);
    for(unsigned y=g_scene.map_y();y<g_scene.map_y()+g_scene.map_height();++y)
        Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+g_scene.map_x()),g_scene.map_width()*4);
    for(unsigned y=1018;y<1038;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+470),640*4);
    return true;
}
bool display_scene_parcel_age(uint64_t now) {
    if(!g_started||!g_scene.parcel_age(now))return false;
    for(unsigned y=1018;y<1038;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+470),640*4);
    return true;
}
bool display_scene_temperature(float current,float peak,bool valid) {
    if(!g_started||!g_scene.temperature(current,peak,valid))return false;
    for(unsigned y=910;y<1042;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    return true;
}
bool display_scene_power(const PowerView &value) {
    if(!g_started||!g_scene.power(value))return false;
    for(unsigned y=410;y<478;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    for(unsigned y=980;y<1042;++y)Xil_DCacheFlushRange((INTPTR)(g_frame+y*W+88),312*4);
    return true;
}
bool display_update(const DisplayView &view) {
    if(!g_started || !render(g_frame,W*H,view))return false;
    Xil_DCacheFlushRange((INTPTR)g_frame,FRAME_BYTES);
    return true;
}
int display_init(const DisplayView &view) {
    if(g_started)return 5; // no retrain/reinitialize in this boot
    const UINTPTR base=(UINTPTR)g_frame;
    if(base>0xffffffffULL || FRAME_BYTES-1>0xffffffffULL-base)return 4;
    if(!g_scene.begin(g_frame,W*H,view))return 6;
    Xil_DCacheFlushRange((INTPTR)g_frame,FRAME_BYTES);
    if(!init_subsystem())return 1;
    XTime begin,current; XTime_GetTime(&begin);
    while(!XDpPsu_IsConnected(&g_dp)) {
        XTime_GetTime(&current);
        if(current-begin>3*(u64)COUNTS_PER_SECOND)return 2;
        usleep(100000);
    }
    u8 power=1;
    XDpPsu_AuxWrite(&g_dp,XDPPSU_DPCD_SET_POWER_DP_PWR_VOLTAGE,1,&power);
    XDpPsu_AuxWrite(&g_dp,XDPPSU_DPCD_SET_POWER_DP_PWR_VOLTAGE,1,&power);
    // One bounded attempt; no automatic cable/retrain loop. BSP timing remains its own contract.
    usleep(100000); XDpPsu_EnableMainLink(&g_dp,0);
    if(train()!=XST_SUCCESS)return 3;
    setup_video_stream(); start_gfx_dma();
    if(XDpPsu_CheckLinkStatus(&g_dp,g_dp.LinkConfig.LaneCount)!=XST_SUCCESS)return 3;
    g_started=true;
    return 0;
}
}
