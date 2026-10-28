// C3 外设测试（PLAN §17 C3）：SD 读立方体测读速、lwIP UDP 与 PC 互通测吞吐、DP 出一帧、SYSMON 温度电压、PS 按键与 LED。
// 平台：build/vivado/tt_zu5ev.xsa + tools/build_periph_platform.tcl 的 BSP（xilffs、lwip211、dppsu）。上板步骤见 board/CHECKLIST.md。
// 每项测试串口打印 "C3x ... PASS/FAIL"，返回 true 表示 PASS；需要人眼确认的（DP 画面、LED）在串口提示里写明看什么。
#pragma once
#include "xil_types.h"
#if defined(__has_include)
#if __has_include("xtime_l.h")
#include "xtime_l.h"
#else
/* 2026.1 BSP 不再把 xtime_l.h 复制到导出 include；XTime_GetTime 与 COUNTS_PER_SECOND 由 xiltimer 提供 */
#include "xiltimer.h"
#endif
#else
#include "xtime_l.h"
#endif

bool sd_test(bool full);   // C3a：full=false 只读 LongKou cube_i16 与一个长文件名小文件，true 读全表
bool net_start();          // C3b：起 lwIP 与 UDP 测试服务（192.168.1.10:5010），之后由 net_poll 驱动
void net_poll();           //       主循环里反复调用；未起网口时直接返回
bool dp_test();            // C3c：1920x1080@60 出一帧测试图，DPDMA 轮询方式，不用中断
bool sysmon_test();        // C3d：PS / PL 温度与供电
bool gpio_test();          // C3e：PS LED（MIO40）闪 3 次，PS KEY（MIO26）按 3 次

static inline u64 now_ticks() {
    XTime t;
    XTime_GetTime(&t);
    return (u64)t;
}

static inline u64 ticks_us(u64 ticks) {
    return ticks * 1000000ull / COUNTS_PER_SECOND;
}
