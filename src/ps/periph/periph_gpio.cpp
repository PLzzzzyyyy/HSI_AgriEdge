// C3e：PS GPIO。LED 在 MIO40（高亮），KEY 在 MIO26（按下为低），与厂商 course_s2/03_ps_mio 相同。
// PL 侧 LED（AE12）/ KEY（AF12）在 tt_zu5ev.xsa 里没有引出，本项不测。
#include "periph.h"
#include <stdio.h>
#include "xparameters.h"
#include "xgpiops.h"
#include "sleep.h"

namespace {

constexpr u32 LED_MIO = 40, KEY_MIO = 26;
constexpr int PRESSES = 3, TIMEOUT_S = 15;
XGpioPs g_gpio;

bool key_down() { return XGpioPs_ReadPin(&g_gpio, KEY_MIO) == 0; }

}  // namespace

bool gpio_test() {
    printf("\n--- C3e KEY/LED: PS LED MIO%lu blinks 3 times, then press PS KEY MIO%lu %d times within %d s ---\n",
           (unsigned long)LED_MIO, (unsigned long)KEY_MIO, PRESSES, TIMEOUT_S);
    XGpioPs_Config *cfg = XGpioPs_LookupConfig(XPAR_XGPIOPS_0_DEVICE_ID);
    if (cfg == nullptr || XGpioPs_CfgInitialize(&g_gpio, cfg, cfg->BaseAddr) != XST_SUCCESS) {
        printf("C3e KEY/LED FAIL: GPIO init\n");
        return false;
    }
    XGpioPs_SetDirectionPin(&g_gpio, LED_MIO, 1);
    XGpioPs_SetOutputEnablePin(&g_gpio, LED_MIO, 1);
    XGpioPs_SetDirectionPin(&g_gpio, KEY_MIO, 0);
    for (int i = 0; i < 3; i++) {
        XGpioPs_WritePin(&g_gpio, LED_MIO, 1);
        usleep(300000);
        XGpioPs_WritePin(&g_gpio, LED_MIO, 0);
        usleep(300000);
    }
    printf("  LED blinked 3 times (look at the PS LED). Now press PS KEY; the LED follows the key\n");
    if (key_down()) printf("  note: KEY reads pressed before any press (stuck low?)\n");
    // 5 ms 采样，连续 4 次（20 ms）同一电平才算状态变化，按下沿计数
    int presses = 0, stable = 0;
    bool state = key_down();
    const u64 t0 = now_ticks();
    while (presses < PRESSES && now_ticks() - t0 < TIMEOUT_S * (u64)COUNTS_PER_SECOND) {
        usleep(5000);
        const bool now = key_down();
        stable = (now != state) ? stable + 1 : 0;
        if (stable >= 4) {
            state = now;
            stable = 0;
            XGpioPs_WritePin(&g_gpio, LED_MIO, state ? 1 : 0);
            if (state) printf("  key press %d at %.1f s\n", ++presses, ticks_us(now_ticks() - t0) / 1e6);
        }
    }
    XGpioPs_WritePin(&g_gpio, LED_MIO, 0);
    const bool pass = presses >= PRESSES;
    printf("C3e KEY/LED %s: %d/%d presses detected%s\n", pass ? "PASS" : "FAIL", presses, PRESSES,
           pass ? " (also confirm the LED blinked and followed the key)" : "");
    return pass;
}
