/* Standalone A53 app. Requires prior PS/DDR initialization, not lwIP or PL IP. */
#include "phy_id.h"
#include "xparameters.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xtime_l.h"
#include "xemacps_hw.h"

_Static_assert(XPAR_XEMACPS_0_BASEADDR == 0xFF0E0000U, "Use GEM3 / tt_zu5ev XSA");
_Static_assert(PHY_GEM_CTRL == XEMACPS_NWCTRL_OFFSET, "CTRL offset");
_Static_assert(PHY_GEM_CFG == XEMACPS_NWCFG_OFFSET, "CFG offset");
_Static_assert(PHY_GEM_STATUS == XEMACPS_NWSR_OFFSET, "STATUS offset");
_Static_assert(PHY_GEM_MAINT == XEMACPS_PHYMNTNC_OFFSET, "MDIO offset");
_Static_assert(PHY_READ_COMMAND == (XEMACPS_PHYMNTNC_OP_MASK | XEMACPS_PHYMNTNC_OP_R_MASK), "Read-only command");
_Static_assert(PHY_MDC_DIV224 == ((uint32_t)MDC_DIV_224 << XEMACPS_NWCFG_MDC_SHIFT_MASK), "MDC divisor");
_Static_assert(PHY_MDC_MASK == XEMACPS_NWCFG_MDCCLKDIV_MASK, "MDC mask");
_Static_assert(PHY_MDIO_IDLE == XEMACPS_NWSR_MDIOIDLE_MASK, "MDIO status");
_Static_assert(PHY_MDIO_ENABLE == XEMACPS_NWCTRL_MDEN_MASK, "MDIO enable");
_Static_assert(PHY_RX_TX_ENABLE == (XEMACPS_NWCTRL_RXEN_MASK | XEMACPS_NWCTRL_TXEN_MASK), "No RX/TX");

static uint32_t read_reg(void *ctx, uint32_t offset) {
    (void)ctx; return Xil_In32((UINTPTR)XPAR_XEMACPS_0_BASEADDR + offset);
}
static void write_reg(void *ctx, uint32_t offset, uint32_t v) {
    (void)ctx; Xil_Out32((UINTPTR)XPAR_XEMACPS_0_BASEADDR + offset, v);
}
static uint64_t time_us(void *ctx) {
    XTime t; (void)ctx; XTime_GetTime(&t);
    return (t / COUNTS_PER_SECOND) * 1000000U +
           ((t % COUNTS_PER_SECOND) * 1000000U) / COUNTS_PER_SECOND;
}
static void report(void *ctx, const PhySample *s) {
    static const char *const names[] = {
        "EMPTY", "SUSPICIOUS", "UNSTABLE", "UNKNOWN_PHY",
        "KSZ9031 / E-candidate", "JLSEMI-family / B-candidate (JL2121 unconfirmed)"
    };
    (void)ctx;
    xil_printf("ADDR %02d ID %04x:%04x REPEAT %04x:%04x %s\r\n",
               s->addr, s->id1, s->id2, s->repeat1, s->repeat2, names[s->kind]);
}
int main(void) {
    const PhyIo io = {0, read_reg, write_reg, time_us, report};
    xil_printf("\r\n=== PHY_ID_DIAG v1 / A53 standalone / GEM3 ===\r\n");
    xil_printf("Prerequisite: cold PS/DDR init, GEM3 clock/reset and MDIO MIO76/77.\r\n");
    xil_printf("No lwIP, no PHY writes/reset/page select/autoneg, no MAC TX/RX.\r\n");
    xil_printf("Registers 2/3 only, twice; addresses 0..31; MDC divisor 224.\r\n");
    xil_printf("GEM base %08x, waits <=10ms or 100000 polls (MMIO must respond).\r\n", XPAR_XEMACPS_0_BASEADDR);
    int n = phy_scan(&io);
    if (n == PHY_ERR_ACTIVE)
        xil_printf("STOP ACTIVE_MAC: reset + PS init; do not run over a network app.\r\n");
    else if (n == PHY_ERR_TIMEOUT)
        xil_printf("STOP MDIO_TIMEOUT: check PS init/GEM clock/reset. Not a board-model verdict.\r\n");
    else {
        xil_printf("SCAN_DONE stable_nonempty=%d\r\n", n);
        if (n == 0) xil_printf("NO_VALID_ID: check power, PHY reset, MIO, clock and raw rows.\r\n");
        if (n > 1) xil_printf("MULTIPLE_RESPONDERS: possible address aliases; do not auto-select a board.\r\n");
    }
    xil_printf("BOARD_MODEL=UNCONFIRMED. Match raw ID + PS PHY marking + PCB revision.\r\n");
    xil_printf("PHY_ID_DIAG_END. Save this whole log. No network cable/IP/SD required.\r\n");
    return n > 0 ? 0 : 1;
}
