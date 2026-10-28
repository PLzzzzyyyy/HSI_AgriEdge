#include "idle_lwip.h"
#include "xtime_l.h"
#if !NO_SYS || !LWIP_UDP || !LWIP_IPV4
#error S2a requires standalone raw lwIP with IPv4 and UDP
#endif
namespace hsi_idle {
namespace {
uint64_t now_us() {
    XTime ticks; XTime_GetTime(&ticks);
    // Divide first: avoid overflow of ticks*1e6 after long uptime.
    return (ticks / COUNTS_PER_SECOND) * 1000000ULL +
           ((ticks % COUNTS_PER_SECOND) * 1000000ULL) / COUNTS_PER_SECOND;
}
}
err_t LwipIdle::open(uint16_t local_port) {
    if (opened_ || local_port == 0) return ERR_ARG;
    udp_pcb *p = udp_new();
    if (!p) return ERR_MEM;
    const err_t rc = udp_bind(p, IP_ADDR_ANY, local_port);
    if (rc != ERR_OK) { udp_remove(p); return rc; }
    pcb_ = p; opened_ = true; udp_recv(pcb_, receive_cb, this);
    return ERR_OK;
}
void LwipIdle::close() {
    if (pcb_) { udp_recv(pcb_, 0, 0); udp_remove(pcb_); pcb_ = 0; }
}
void LwipIdle::send(Packet &packet) {
    pbuf *p = pbuf_alloc(PBUF_TRANSPORT, u16_t(packet.size), PBUF_RAM);
    if (!p) { idle_.sent(packet.size, false); return; }
    stamp(packet, now_us());
    err_t rc = pbuf_take(p, packet.bytes, u16_t(packet.size));
    if (rc == ERR_OK) {
        ip_addr_t dst; ip_addr_set_ip4_u32(&dst, packet.to.ipv4);
        rc = udp_sendto(pcb_, p, &dst, packet.to.port);
    }
    pbuf_free(p);  // CPU pbuf only, not a PL/engine DMA buffer
    idle_.sent(packet.size, rc == ERR_OK);
}
void LwipIdle::receive_cb(void *arg, udp_pcb *, pbuf *p,
                          const ip_addr_t *addr, u16_t port) {
    if (!p) return;
    LwipIdle *self = static_cast<LwipIdle *>(arg);
    const uint64_t received = now_us();
    uint8_t bytes[PING_BYTES];
    // Do not assume p->payload is contiguous; safely copy a chained pbuf.
    if (!addr || !IP_IS_V4(addr) || p->tot_len != PING_BYTES ||
        pbuf_copy_partial(p, bytes, PING_BYTES, 0) != PING_BYTES) {
        self->idle_.bad_input(); pbuf_free(p); return;
    }
    const Peer peer = {ip_addr_get_ip4_u32(addr), port};
    pbuf_free(p);
    Packet reply;
    if (self->idle_.receive(bytes, sizeof(bytes), peer, received, reply)) self->send(reply);
}
void LwipIdle::poll() {
    if (!pcb_) return;
    Packet reply;
    if (idle_.status(now_us(), reply)) send(reply);
}
}
