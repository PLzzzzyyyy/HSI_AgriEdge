// C3 外设测试主程序：串口菜单（PS_UART 115200 8N1，发 ASCII 字母），各项实现在 periph_*.cpp，上板步骤见 board/CHECKLIST.md。
// 菜单等待按键时一直调 net_poll：UDP 服务起来以后，PC 脚本随时可测，不必停在某一项里。
#include "periph.h"
#include <stdio.h>
#include "xparameters.h"
#include "xil_cache.h"
#include "xuartps_hw.h"

static void menu() {
    printf("\n[s] SD quick  [S] SD full  [u] UDP server  [d] DP frame  [t] SYSMON  [k] KEY/LED  [a] all (s t k d u)\n");
    printf("Send one ASCII letter (HEX mode off). Once started, UDP keeps answering while the menu waits.\n");
    fflush(stdout);
}

static char wait_key() {
    while (!XUartPs_IsReceiveData(STDIN_BASEADDRESS)) net_poll();
    return (char)XUartPs_RecvByte(STDIN_BASEADDRESS);
}

static const char *verdict(bool ok) { return ok ? "PASS" : "FAIL"; }

int main() {
    Xil_ICacheEnable();
    Xil_DCacheEnable();
    printf("\n=== C3 peripheral test (ZU5EV, platform build/vivado/tt_zu5ev.xsa) ===\n");
    printf("Cortex-A53 %lu Hz, timer %lu Hz; board 192.168.1.10 UDP 5010; SD1 FAT32; DP 1920x1080@60\n",
           (unsigned long)XPAR_CPU_CORTEXA53_0_CPU_CLK_FREQ_HZ, (unsigned long)COUNTS_PER_SECOND);
    menu();
    while (true) {
        const char key = wait_key();
        if (key == '\r' || key == '\n' || key == ' ') continue;
        switch (key) {
        case 's': sd_test(false); break;
        case 'S': sd_test(true); break;
        case 'u': net_start(); break;
        case 'd': dp_test(); break;
        case 't': sysmon_test(); break;
        case 'k': gpio_test(); break;
        case 'a': {
            const bool sd = sd_test(false), sm = sysmon_test(), key_led = gpio_test(), dp = dp_test(), net = net_start();
            printf("\nC3 summary: SD %s | SYSMON %s | KEY/LED %s | DP %s | UDP %s\n", verdict(sd), verdict(sm), verdict(key_led),
                   dp ? "STREAMING (confirm picture)" : "FAIL", net ? "READY (PC script gives PASS/FAIL)" : "FAIL");
            break;
        }
        default: printf("Unknown key '%c'\n", key); break;
        }
        menu();
    }
}
