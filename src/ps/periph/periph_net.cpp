// C3b：lwIP RAW API，静态 IP 192.168.1.10/24，UDP 5010（docs/protocol.md 的 BOARD_PORT）上跑测试服务；PC 端 tools/periph_pc.py。
// 回包一律发往请求的源地址（protocol.md §3.3：不写死 PC 地址）。报文格式与 periph_pc.py 一致，全部小端：
//   头 16 B：u32 magic "C3UT"、u16 cmd、u16 0、u32 seq、u32 arg
//   PING 1 → PONG 2：整包原样回，PC 测往返时延
//   TXREQ 3：载荷 u32 count、u32 size（整个 UDP 载荷字节数，64..1472）、u32 rate_kbps（UDP 载荷速率上限，0 = 按发送环空位尽快发）
//            → 板发 count 个 TXDATA 4（seq = 0..count-1、arg = count、头后数据第 j 字节 = (seq + j) & 0xFF），发完回 REPORT
//   RXRESET 8 → 清收包计数、回 REPORT；RXDATA 5：格式同 TXDATA，板上计数并逐字节核对；RXSTAT 6 → 回 REPORT
//   REPORT 7：arg = 触发它的命令号，载荷是 NetReport（8 个 u32）
// 这不是地面站协议 v1（那是 C3b 之后的 src/ps/net/），只借用同一对端口，防火墙放行一次两边都能用。
#include "periph.h"
#include <stdio.h>
#include <string.h>
#include "xparameters.h"
#include "xscugic.h"
#include "xil_exception.h"
#include "lwip/init.h"
#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/udp.h"
#include "netif/xadapter.h"
#include "netif/xemacpsif.h"

#if LWIP_VERSION_MAJOR == 2 && LWIP_VERSION_MINOR >= 2
/* 2026.1：lwip220（lwIP 2.2）把移植层 is_tx_space_available 更名为 xemacps_is_tx_space_available
   （netif/xemacpsif.h，签名不变）；旧 lwip211（lwIP 2.1）仍用原名，按版本宏切换。 */
#define is_tx_space_available xemacps_is_tx_space_available
#endif

namespace {

constexpr u16 BOARD_PORT = 5010;
constexpr u32 MAGIC = 0x54553343u;   // 字节序列 "C3UT"
enum : u16 { CMD_PING = 1, CMD_PONG = 2, CMD_TXREQ = 3, CMD_TXDATA = 4, CMD_RXDATA = 5, CMD_RXSTAT = 6, CMD_REPORT = 7, CMD_RXRESET = 8 };
constexpr u32 HDR = 16, MIN_UDP = 64, MAX_UDP = 1472, MAX_COUNT = 2000000;

struct Hdr { u32 magic; u16 cmd; u16 flags; u32 seq; u32 arg; };
struct NetReport { u32 packets, bytes, elapsed_us, errors, extra, seq_max, link_mbps, reserved; };
static_assert(sizeof(Hdr) == HDR && sizeof(NetReport) == 32, "wire layout shared with tools/periph_pc.py");
// NetReport.extra：TX = 等发送环空位的包数，RX = 乱序包数（seq 小于此前最大 seq）

XScuGic g_gic;
struct netif g_netif;
struct udp_pcb *g_pcb;
xemacpsif_s *g_emacif;
XEmacPs *g_emac;
bool g_up;
u32 g_link_mbps;
unsigned char g_mac[6] = {0x00, 0x0a, 0x35, 0x00, 0x01, 0x02};

ip_addr_t g_peer;
u16 g_peer_port;
bool g_have_peer, g_peer_new;
u32 g_pings;

// 收包回调里只登记请求；大量发包和回 REPORT 放到回调外的 net_poll 里做，避免在协议栈输入路径里再进 xemacif_input
bool g_tx_pending;
u32 g_tx_count, g_tx_size, g_tx_rate_kbps;
u16 g_report_cmd;

struct RxStat { u32 packets, bytes, errors, reorder, seq_max; u64 t_first, t_last; } g_rx;

u8 g_rx_seen[(MAX_COUNT + 7) / 8];
u32 g_rx_expected;

u8 g_pattern[256 + MAX_UDP];   // g_pattern[k] = k & 0xFF；序号 seq 的数据 = g_pattern + (seq & 0xFF)
u8 g_scratch[MAX_UDP];

void rx_account(struct pbuf *p, const Hdr &h) {
    if (!h.arg || h.arg > MAX_COUNT || h.seq >= h.arg ||
        (g_rx_expected && h.arg != g_rx_expected)) {
        g_rx.errors++;
        return;
    }
    g_rx_expected = h.arg;
    const u8 bit = (u8)(1u << (h.seq & 7));
    if (g_rx_seen[h.seq >> 3] & bit) {
        g_rx.errors++; // Duplicates must not hide lost packets.
        return;
    }
    g_rx_seen[h.seq >> 3] |= bit;
    const u64 t = now_ticks();
    if (g_rx.packets == 0) g_rx.t_first = t;
    else if (h.seq < g_rx.seq_max) g_rx.reorder++;
    g_rx.t_last = t;
    g_rx.packets++;
    g_rx.bytes += p->tot_len;
    if (h.seq > g_rx.seq_max) g_rx.seq_max = h.seq;
    if (p->tot_len < MIN_UDP || p->tot_len > MAX_UDP) {
        g_rx.errors++;
        return;
    }
    const u16 n = (u16)(p->tot_len - HDR);
    if (pbuf_copy_partial(p, g_scratch, n, HDR) != n || memcmp(g_scratch, g_pattern + (h.seq & 0xFF), n) != 0)
        g_rx.errors++;
}

void on_recv(void *, struct udp_pcb *pcb, struct pbuf *p, const ip_addr_t *addr, u16_t port) {
    Hdr h;
    if (p->tot_len < HDR || pbuf_copy_partial(p, &h, HDR, 0) != HDR || h.magic != MAGIC) {
        pbuf_free(p);
        return;
    }
    if (!g_have_peer || !ip_addr_cmp(&g_peer, addr) || g_peer_port != port) {
        ip_addr_copy(g_peer, *addr);
        g_peer_port = port;
        g_have_peer = g_peer_new = true;
    }
    switch (h.cmd) {
    case CMD_PING:
        h.cmd = CMD_PONG;
        pbuf_take(p, &h, HDR);
        udp_sendto(pcb, p, addr, port);
        g_pings++;
        break;
    case CMD_TXREQ: {
        u32 a[3];
        if (pbuf_copy_partial(p, a, sizeof a, HDR) == sizeof a) {
            g_tx_count = a[0] > MAX_COUNT ? MAX_COUNT : a[0];
            g_tx_size = a[1] < MIN_UDP ? MIN_UDP : a[1] > MAX_UDP ? MAX_UDP : a[1];
            g_tx_rate_kbps = a[2];
            g_tx_pending = true;
        }
        break;
    }
    case CMD_RXRESET:
        memset(&g_rx, 0, sizeof g_rx);
        memset(g_rx_seen, 0, sizeof g_rx_seen);
        g_rx_expected = 0;
        g_report_cmd = CMD_RXRESET;
        break;
    case CMD_RXDATA:
        rx_account(p, h);
        break;
    case CMD_RXSTAT:
        g_report_cmd = CMD_RXSTAT;
        break;
    default:
        break;
    }
    pbuf_free(p);
}

// 发送环（256 个描述符）剩余不足时先等 TX 完成中断回收。lwIP 移植层在环满时每包 printf 一行再丢包，
// 满速发送会被 115200 串口拖住，所以这里不让它走到那个分支。
bool send_packet(const u8 *data, u32 len, u32 *waits) {
    if (is_tx_space_available(g_emacif) < 8) {
        if (waits) (*waits)++;
        const u64 t0 = now_ticks();
        while (is_tx_space_available(g_emacif) < 8)
            if (now_ticks() - t0 > COUNTS_PER_SECOND) return false;
    }
    struct pbuf *p = pbuf_alloc(PBUF_TRANSPORT, (u16)len, PBUF_POOL);
    if (!p) return false;
    pbuf_take(p, data, (u16)len);
    const err_t e = udp_sendto(g_pcb, p, &g_peer, g_peer_port);
    pbuf_free(p);
    return e == ERR_OK;
}

void send_report(u16 cmd, const NetReport &r) {
    u8 buf[HDR + sizeof(NetReport)];
    const Hdr h = {MAGIC, CMD_REPORT, 0, 0, cmd};
    memcpy(buf, &h, HDR);
    memcpy(buf + HDR, &r, sizeof r);
    send_packet(buf, sizeof buf, nullptr);
}

void run_tx() {
    static u8 pkt[MAX_UDP];
    const u32 count = g_tx_count, size = g_tx_size, rate = g_tx_rate_kbps;
    const u64 gap = rate ? (u64)size * 8 * COUNTS_PER_SECOND / ((u64)rate * 1000) : 0;
    Hdr h = {MAGIC, CMD_TXDATA, 0, 0, count};
    NetReport r = {};
    const u64 t0 = now_ticks();
    u64 next = t0;
    for (u32 i = 0; i < count; i++) {
        if (gap) {
            while (now_ticks() < next) {}
            next += gap;
        }
        h.seq = i;
        memcpy(pkt, &h, HDR);
        memcpy(pkt + HDR, g_pattern + (i & 0xFF), size - HDR);
        if (send_packet(pkt, size, &r.extra)) {
            r.packets++;
            r.bytes += size;
        } else {
            r.errors++;
        }
    }
    const u64 us = ticks_us(now_ticks() - t0);
    r.elapsed_us = (u32)us;
    r.seq_max = count;
    r.link_mbps = g_link_mbps;
    send_report(CMD_TXREQ, r);
    printf("C3b UDP TX: %lu/%lu pkts x %lu B in %.1f ms = %.1f Mbps UDP payload (cap %lu kbps), ring waits %lu, errors %lu\n",
           (unsigned long)r.packets, (unsigned long)count, (unsigned long)size, us / 1000.0,
           us ? r.bytes * 8.0 / us : 0.0, (unsigned long)rate, (unsigned long)r.extra, (unsigned long)r.errors);
}

void report_rx(u16 cmd) {
    const u64 us = g_rx.packets > 1 ? ticks_us(g_rx.t_last - g_rx.t_first) : 0;
    const NetReport r = {g_rx.packets, g_rx.bytes, (u32)us, g_rx.errors, g_rx.reorder, g_rx.seq_max, g_link_mbps, 0};
    send_report(cmd, r);
    if (cmd == CMD_RXSTAT)
        printf("C3b UDP RX: %lu pkts, %lu B, first..last %.1f ms = %.1f Mbps, payload errors %lu, out-of-order %lu, "
               "max seq %lu; pings answered %lu\n",
               (unsigned long)r.packets, (unsigned long)r.bytes, us / 1000.0, us ? r.bytes * 8.0 / us : 0.0,
               (unsigned long)r.errors, (unsigned long)r.extra, (unsigned long)r.seq_max, (unsigned long)g_pings);
}

// 板上 PHY 是 KSZ9031（ID1 0x0022）：BMSR bit2 链路（锁存低，读两次），0x1F 寄存器 bit6/5/4 = 1000/100/10、bit3 = 全双工
void print_phy() {
    u32 addr = 0;
    for (u32 a = 1; a < 32 && addr == 0; a++) {
        u16 v = 0xFFFF;
        if (XEmacPs_PhyRead(g_emac, a, 1, &v) == XST_SUCCESS && v != 0xFFFF && (v & 0x1808) == 0x1808) addr = a;
    }
    if (addr == 0) {
        printf("  PHY: none answered on MDIO\n");
        return;
    }
    u16 id1 = 0, id2 = 0, bmsr = 0, ctl = 0;
    XEmacPs_PhyRead(g_emac, addr, 2, &id1);
    XEmacPs_PhyRead(g_emac, addr, 3, &id2);
    const u64 t0 = now_ticks();
    do {
        XEmacPs_PhyRead(g_emac, addr, 1, &bmsr);
        XEmacPs_PhyRead(g_emac, addr, 1, &bmsr);
    } while ((bmsr & 0x4) == 0 && now_ticks() - t0 < 6 * (u64)COUNTS_PER_SECOND);
    XEmacPs_PhyRead(g_emac, addr, 0x1F, &ctl);
    const bool ksz = id1 == 0x0022, link = (bmsr & 0x4) != 0;
    g_link_mbps = link && ksz ? ((ctl & 0x40) ? 1000 : (ctl & 0x20) ? 100 : (ctl & 0x10) ? 10 : 0) : 0;
    printf("  PHY addr %lu id %04X:%04X%s, link %s after %.1f s, %lu Mbps %s duplex (reg 0x1F = %04X)\n", (unsigned long)addr,
           id1, id2, ksz ? " (KSZ9031)" : " (not KSZ9031: speed bits unknown)", link ? "UP" : "DOWN",
           ticks_us(now_ticks() - t0) / 1e6, (unsigned long)g_link_mbps, (ctl & 0x8) ? "full" : "half", ctl);
}

}  // namespace

bool net_start() {
    if (g_up) {
        printf("C3b UDP already running on 192.168.1.10:%u, link %lu Mbps, pings answered %lu\n", BOARD_PORT,
               (unsigned long)g_link_mbps, (unsigned long)g_pings);
        return g_link_mbps == 1000;
    }
    printf("\n--- C3b UDP: lwIP RAW, 192.168.1.10/24, UDP %u, PHY forced 1000 Mbps; PC: python tools/periph_pc.py all ---\n",
           BOARD_PORT);
    printf("  (lwIP prints \"WARNING: Not a Marvell or TI or Realtek Ethernet PHY\" for KSZ9031: expected)\n");
    for (u32 i = 0; i < sizeof g_pattern; i++) g_pattern[i] = (u8)i;
    XScuGic_Config *gc = XScuGic_LookupConfig(XPAR_SCUGIC_0_DEVICE_ID);
    if (gc == nullptr || XScuGic_CfgInitialize(&g_gic, gc, gc->CpuBaseAddress) != XST_SUCCESS) {
        printf("C3b UDP FAIL: GIC init\n");
        return false;
    }
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT, (Xil_ExceptionHandler)XScuGic_InterruptHandler, &g_gic);
    Xil_ExceptionEnable();
    lwip_init();
    ip_addr_t ip, mask, gw;
    IP4_ADDR(&ip, 192, 168, 1, 10);
    IP4_ADDR(&mask, 255, 255, 255, 0);
    IP4_ADDR(&gw, 192, 168, 1, 1);
    const u64 t0 = now_ticks();
    if (xemac_add(&g_netif, &ip, &mask, &gw, g_mac, XPAR_XEMACPS_0_BASEADDR) == nullptr) {
        printf("C3b UDP FAIL: xemac_add (GEM3 / PHY init)\n");
        return false;
    }
    netif_set_default(&g_netif);
    netif_set_up(&g_netif);
    g_emacif = (xemacpsif_s *)((struct xemac_s *)g_netif.state)->state;
    g_emac = &g_emacif->emacps;
    printf("  xemac_add done in %.1f ms (GEM base 0x%08lX)\n", ticks_us(now_ticks() - t0) / 1000.0,
           (unsigned long)XPAR_XEMACPS_0_BASEADDR);
    print_phy();
    g_pcb = udp_new();
    if (g_pcb == nullptr || udp_bind(g_pcb, IP_ADDR_ANY, BOARD_PORT) != ERR_OK) {
        printf("C3b UDP FAIL: udp bind %u\n", BOARD_PORT);
        return false;
    }
    udp_recv(g_pcb, on_recv, nullptr);
    g_up = true;
    printf("C3b UDP READY%s: board answers on 192.168.1.10:%u while the menu is idle; PASS/FAIL is printed by the PC script\n",
           g_link_mbps == 1000 ? "" : " (WARNING: link is not 1000 Mbps)", BOARD_PORT);
    return g_link_mbps == 1000;
}

void net_poll() {
    if (!g_up) return;
    for (int i = 0; i < 256 && xemacif_input(&g_netif) > 0; i++) {}
    if (g_peer_new) {
        g_peer_new = false;
        printf("C3b UDP: peer %s:%u\n", ipaddr_ntoa(&g_peer), g_peer_port);
    }
    if (g_tx_pending) {
        g_tx_pending = false;
        run_tx();
    }
    if (g_report_cmd) {
        const u16 cmd = g_report_cmd;
        g_report_cmd = 0;
        report_rx(cmd);
    }
}
