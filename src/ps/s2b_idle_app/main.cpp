// S2b connected SOURCE, Vitis 2020.2 / A53 standalone / existing application BSP.
// This connected target revision is NOT built, linked or run yet.
// Separate cold-start App only, never hot takeover.
#ifndef S2B_LOG_HOST_TEST
#define S2B_LOG_HOST_TEST 0
#endif
#if S2B_LOG_HOST_TEST != 0 && S2B_LOG_HOST_TEST != 1
#error S2B_LOG_HOST_TEST must be 0 or 1
#endif
#if S2B_LOG_HOST_TEST && (defined(__aarch64__) || defined(__arm__))
#error The private log test adapter must not be used in a target App
#endif
#if S2B_LOG_HOST_TEST
#include <cstdint>
#else
#include "boot_id.h"
#include "idle_lwip.h"
#include "xparameters.h"
#include "xscugic.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xuartps_hw.h"
#include "xtime_l.h"
#include "lwip/init.h"
#include "lwip/etharp.h"
#include "lwip/ip4_frag.h"
#include "lwip/priv/tcp_priv.h"
#include "netif/xadapter.h"

#if !defined(__aarch64__)
#error S2b requires the existing AArch64 standalone application domain
#endif
#if !NO_SYS || !NO_SYS_NO_TIMERS || LWIP_TIMERS || !LWIP_IPV4 || !LWIP_UDP
#error S2b timer ownership requires the audited raw IPv4 BSP with automatic timers off
#endif
#if LWIP_DHCP || LWIP_AUTOIP || LWIP_IGMP || LWIP_DNS || LWIP_IPV6
#error Re-audit timers and addressing before changing the existing BSP features
#endif
#if !CONFIG_LINKSPEED1000
#error S2b preparation targets the existing forced-1000 BSP, not another PHY setup
#endif
static_assert(XPAR_XEMACPS_0_BASEADDR == 0xFF0E0000U, "Expected GEM3 alias");
static_assert(COUNTS_PER_SECOND > 0, "Expected existing physical-counter frequency");
static_assert(STDOUT_BASEADDRESS == XPAR_XUARTPS_0_BASEADDR, "Expected UART0 console");
#endif

namespace {
// Retain accepted C3 IP/MAC. SOURCE release authorized 2026-10-10, only after
// successful r1 identity acquisition. This does not authorize device execution.
constexpr bool kLabNetworkConfirmed = true;
#if !S2B_LOG_HOST_TEST
unsigned char mac[6] = {0x00, 0x0a, 0x35, 0x00, 0x01, 0x02};
XScuGic gic;
struct netif network;
#else
// Same-translation-unit test hooks, not a public API or a simulated board.
// Register identifiers match the existing 2020.2 UART header.
constexpr uint32_t XUARTPS_SR_OFFSET = 0x2cU;
constexpr uint32_t XUARTPS_FIFO_OFFSET = 0x30U;
constexpr uint32_t XUARTPS_SR_TXFULL = 0x10U;
struct LogHostIo {
    uint32_t (*read)(uint32_t offset);
    void (*write)(uint32_t offset, uint32_t value);
    void (*disable_interrupts)();
    void (*park)();
};
LogHostIo log_host_io = {};
#endif

inline uint32_t log_uart_status() {
#if S2B_LOG_HOST_TEST
    return log_host_io.read(XUARTPS_SR_OFFSET);
#else
    return XUartPs_ReadReg(XPAR_XUARTPS_0_BASEADDR, XUARTPS_SR_OFFSET);
#endif
}

inline void log_uart_byte(uint8_t value) {
#if S2B_LOG_HOST_TEST
    log_host_io.write(XUARTPS_FIFO_OFFSET, value);
#else
    XUartPs_WriteReg(XPAR_XUARTPS_0_BASEADDR, XUARTPS_FIFO_OFFSET, value);
#endif
}

// Best-effort diagnostics, NOT the r1 identity prompt. No clock access, retry,
// TX-empty wait or hidden SendByte/printf loop. Messages may be truncated/lost.
// Finite software work assumes MMIO returns and this App owns UART0; it is not
// a wall-clock guarantee against a wedged bus or proof of terminal delivery.
bool try_log(const char *text) {
    for (unsigned int i = 0; i != 96U; ++i) {
        if (text[i] == '\0') return true;
        const uint32_t status = log_uart_status();
        if ((status & XUARTPS_SR_TXFULL) != 0) return false;
        log_uart_byte(static_cast<uint8_t>(text[i]));
    }
    return false;  // diagnostic byte budget exhausted; do not wait/retry
}

[[noreturn]] void stop(const char *reason) {
#if S2B_LOG_HOST_TEST
    log_host_io.disable_interrupts();
#else
    Xil_ExceptionDisable();
#endif
    if (try_log("S2B STOP: ") && try_log(reason)) (void)try_log("\r\n");
    // No retry, no cleanup of potentially active GEM buffers, no other App.
#if S2B_LOG_HOST_TEST
    log_host_io.park();  // tests throw here; returning still enters permanent stop
#endif
    for (;;) {}
}

void log_bound(uint32_t boot_id) {
    // Shared verbatim formatting: host tests never execute the App entry point.
    char bound[] = "S2B UDP PCB bound; boot_id=00000000; NOT a link/PING PASS\r\n";
    const unsigned int prefix = sizeof("S2B UDP PCB bound; boot_id=") - 1U;
    for (unsigned int i = 0; i != 8U; ++i)
        bound[prefix + i] = "0123456789abcdef"[(boot_id >> (28U - 4U * i)) & 15U];
    (void)try_log(bound);
}

#if !S2B_LOG_HOST_TEST
uint64_t ticks_now() {
    XTime ticks;
    // Existing EL3 BSP may enable a disabled counter, including inside the
    // identity provider. Device authorization must include this side effect.
    XTime_GetTime(&ticks);
    return ticks;
}

// Each timer runs at most once per main-loop iteration. Carry a due backlog
// forward, without a blocking catch-up loop or an ISR calling the lwIP core.
bool due(uint64_t now, uint64_t &last, uint32_t interval_ms) {
    const uint64_t interval =
        (uint64_t(COUNTS_PER_SECOND) * interval_ms + 999U) / 1000U;
    if (now - last < interval) return false;
    last += interval;
    return true;
}

class StackTimers {
public:
    explicit StackTimers(uint64_t now) : arp_(now), reass_(now), tcp_(now) {}
    void poll(uint64_t now) {
#if LWIP_ARP
        if (due(now, arp_, ARP_TMR_INTERVAL)) etharp_tmr();
#endif
#if IP_REASSEMBLY
        if (due(now, reass_, IP_TMR_INTERVAL)) ip_reass_tmr();
#endif
#if LWIP_TCP
        // Existing BSP enables TCP even though this App creates no TCP PCB.
        if (due(now, tcp_, TCP_TMR_INTERVAL)) tcp_tmr();
#endif
    }
private:
    uint64_t arp_, reass_, tcp_;
};
#endif
}

#if !S2B_LOG_HOST_TEST
int main() {
    (void)try_log("S2B CONNECTED SOURCE r1: idle v1 subset; no board acceptance\r\n");
    uint32_t boot_id;  // not consumed unless the provider really assigned it
    if (!s2b::acquire_boot_id(boot_id))
        stop("boot_id acquisition FAILED; GEM/lwIP/UDP not initialized");
    if (!kLabNetworkConfirmed)
        stop("network release NOT AUTHORIZED; GEM/lwIP/UDP not initialized");

    // Reachable only after identity success. An authorized independent App must
    // start after matching PS initialization, never over a live ROI/C3 App.
    Xil_ICacheEnable();
    Xil_DCacheEnable();
    Xil_ExceptionDisable();
    XScuGic_Config *config = XScuGic_LookupConfig(XPAR_SCUGIC_0_DEVICE_ID);
    if (!config || XScuGic_CfgInitialize(&gic, config, config->CpuBaseAddress) != XST_SUCCESS)
        stop("GIC init failed");
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,
        reinterpret_cast<Xil_ExceptionHandler>(XScuGic_InterruptHandler), &gic);
    Xil_ExceptionEnable();

    lwip_init();
    ip_addr_t ip, mask, gateway;
    IP4_ADDR(&ip, 192, 168, 1, 10);
    IP4_ADDR(&mask, 255, 255, 255, 0);
    IP4_ADDR(&gateway, 192, 168, 1, 1);
    // Existing BSP installs/enables GEM3 IRQ 95 through its shared GIC table.
    // Do not reinitialize the GIC or install a second GEM handler afterwards.
    // PHY init uses BSP MDIO routines; this App adds no PHY polling/timeouts.
    if (!xemac_add(&network, &ip, &mask, &gateway, mac, XPAR_XEMACPS_0_BASEADDR))
        stop("xemac_add failed; no UDP open");
    netif_set_default(&network);
    netif_set_up(&network);  // administrative UP only, not a PHY measurement

    hsi_idle::LwipIdle idle(boot_id);
    if (idle.open() != ERR_OK) stop("idle UDP bind failed; no retry");
    StackTimers timers(ticks_now());
    log_bound(boot_id);
    for (;;) {
        // One input pump per iteration, never drain-until-empty under traffic.
        (void)xemacif_input(&network);
        timers.poll(ticks_now());
        idle.poll();
    }
}
#endif
