// C3c：PS DisplayPort 出一帧 1920x1080@60 测试图。流程照 Xilinx 2020.2 的 dpdma_v1_3 例程（厂商 course_s2/07_ps_dp 同源），
// 三处改动：① 不用 HPD / VSync 中断，前台轮询 HPD、训练链路；② DPDMA 描述符在驱动实例里（可缓存 DDR），
//   例程靠关 D-cache 规避，这里开着 cache，写完描述符 flush 实例再触发（描述符 NEXT 指向自己，触发一次后 DMA 循环读同一帧）；
//   ③ 训练后不再重复 init（原因见 dp_test）。
// 帧缓冲 RGBA8888，一个像素 u32 = A<<24 | B<<16 | G<<8 | R（例程 0xFF0000FF 为红）。重插显示器后要再按一次 d。
#include "periph.h"
#include <stdio.h>
#include "xparameters.h"
#include "xil_cache.h"
#include "sleep.h"
#include "xdpdma.h"
#include "xdppsu.h"
#include "xavbuf.h"
#include "xavbuf_clk.h"

namespace {

constexpr u32 W = 1920, H = 1080, STRIDE = W * 4;   // 步长须是 256 的倍数：7680 = 30 × 256
constexpr u32 FRAME_BYTES = STRIDE * H;
u32 g_frame[W * H] __attribute__((aligned(256)));
XDpPsu g_dp;
XAVBuf g_avbuf;
XDpDma g_dma;
XDpDma_FrameBuffer g_fb;
bool g_started;

constexpr u32 rgb(u32 r, u32 g, u32 b) { return 0xFF000000u | (b << 16) | (g << 8) | r; }

// 上 2/3：8 条竖彩条 白 黄 青 绿 品红 红 蓝 黑；下 1/3：左半 0..255 灰阶横向渐变，右半 32 px 黑白棋盘；四周 4 px 橙框
void draw_frame() {
    static const u32 bars[8] = {rgb(255, 255, 255), rgb(255, 255, 0), rgb(0, 255, 255), rgb(0, 255, 0),
                                rgb(255, 0, 255), rgb(255, 0, 0), rgb(0, 0, 255), rgb(0, 0, 0)};
    for (u32 y = 0; y < H; y++) {
        u32 *row = g_frame + y * W;
        for (u32 x = 0; x < W; x++) {
            u32 c;
            if (x < 4 || y < 4 || x >= W - 4 || y >= H - 4) c = rgb(255, 128, 0);
            else if (y < H * 2 / 3) c = bars[x / (W / 8)];
            else if (x < W / 2) { const u32 v = x * 256 / (W / 2); c = rgb(v, v, v); }
            else c = (((x / 32) ^ (y / 32)) & 1) ? rgb(255, 255, 255) : rgb(0, 0, 0);
            row[x] = c;
        }
    }
    Xil_DCacheFlushRange((INTPTR)g_frame, FRAME_BYTES);
}

bool init_subsystem() {
    XDpPsu_Config *cfg = XDpPsu_LookupConfig(XPAR_PSU_DP_DEVICE_ID);
    XDpDma_Config *dcfg = XDpDma_LookupConfig(XPAR_XDPDMA_0_DEVICE_ID);
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

}  // namespace

bool dp_test() {
    printf("\n--- C3c DP: PS DisplayPort 1920x1080@60 RGBA8888 test pattern, polled (no HPD/VSync interrupts) ---\n");
    if (g_started) {
        XDpPsu_EnableMainLink(&g_dp, 0);
        XDpDma_SetChannelState(&g_dma, GraphicsChan, XDPDMA_DISABLE);
        g_started = false;
    }
    const u64 t0 = now_ticks();
    draw_frame();
    printf("  frame drawn + flushed in %.1f ms (%lu B at 0x%08lX)\n", ticks_us(now_ticks() - t0) / 1000.0,
           (unsigned long)FRAME_BYTES, (unsigned long)(UINTPTR)g_frame);
    if (!init_subsystem()) {
        printf("C3c DP FAIL: DP/AVBUF/DPDMA init (XDpPsu_InitializeTx or format setup)\n");
        return false;
    }
    printf("  waiting for HPD (monitor on DP connector, powered on), up to 30 s...\n");
    const u64 tw = now_ticks();
    while (!XDpPsu_IsConnected(&g_dp)) {
        if (now_ticks() - tw > 30 * (u64)COUNTS_PER_SECOND) {
            printf("C3c DP FAIL: no sink (HPD low for 30 s). Check cable / monitor input / DP-to-HDMI adapter must be active\n");
            return false;
        }
        usleep(100000);
    }
    printf("  HPD high after %.1f s\n", ticks_us(now_ticks() - tw) / 1e6);
    u8 power = 0x1;   // DPCD 0x600 = D0，例程写两次唤醒显示器
    XDpPsu_AuxWrite(&g_dp, XDPPSU_DPCD_SET_POWER_DP_PWR_VOLTAGE, 1, &power);
    XDpPsu_AuxWrite(&g_dp, XDPPSU_DPCD_SET_POWER_DP_PWR_VOLTAGE, 1, &power);
    // 例程在训练后又做一遍 init（含 XDpPsu_InitializeTx：软复位、PHY 时钟写回 5.4 Gbps），
    // 对只支持 2.7 Gbps 的显示器会打乱已训练的链路；这里只在训练前 init 一次，视频流路径在 setup_video_stream 里复位
    u32 s = XST_FAILURE;
    for (int attempt = 1; attempt <= 3 && s != XST_SUCCESS; attempt++) {
        usleep(100000);
        XDpPsu_EnableMainLink(&g_dp, 0);
        s = train();
        printf("  attempt %d: link training %s, lanes %u, link rate code 0x%02X (0x06 1.62 / 0x0A 2.7 / 0x14 5.4 Gbps)\n",
               attempt, s == XST_SUCCESS ? "OK" : "failed", g_dp.LinkConfig.LaneCount, g_dp.LinkConfig.LinkRate);
        if (s == XST_DEVICE_NOT_FOUND) break;
        if (s != XST_SUCCESS) continue;
        setup_video_stream();
        start_gfx_dma();
        s = XDpPsu_CheckLinkStatus(&g_dp, g_dp.LinkConfig.LaneCount);
        printf("  video stream on, pixel clock %lu Hz, link status %s\n", (unsigned long)g_dp.MsaConfig.PixelClockHz,
               s == XST_SUCCESS ? "OK" : "lost");
    }
    if (s != XST_SUCCESS) {
        printf("C3c DP FAIL: could not train/keep the link (status %lu)\n", (unsigned long)s);
        return false;
    }
    g_started = true;
    printf("C3c DP STREAMING: check the monitor: 1920x1080, orange 4 px border on all four edges,\n"
           "  bars left->right white yellow cyan green magenta red blue black (red/blue swapped = wrong byte order),\n"
           "  bottom-left gray ramp, bottom-right 32 px checkerboard. PASS = picture exactly like this (record by eye/photo)\n");
    return true;
}
