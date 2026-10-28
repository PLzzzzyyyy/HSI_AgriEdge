#ifndef HSI_IDLE_LWIP_H
#define HSI_IDLE_LWIP_H
#include "idle_protocol.h"
#include "lwip/udp.h"
namespace hsi_idle {
// One standalone main-loop owner. Caller owns lwip_init, GEM/netif/GIC,
// IP/MAC, timers and xemacif_input. Construction has no hardware/network effects.
class LwipIdle {
public:
    explicit LwipIdle(uint32_t fresh_boot_id) : idle_(fresh_boot_id), pcb_(0), opened_(false) {}
    err_t open(uint16_t local_port = 5010);  // future authorized App integration only
    void poll();  // call after xemacif_input; does not service/initialize GEM itself
    void close();  // terminal shutdown; successful open is once per object/boot
private:
    LwipIdle(const LwipIdle &) = delete;
    LwipIdle &operator=(const LwipIdle &) = delete;
    static void receive_cb(void *, udp_pcb *, pbuf *, const ip_addr_t *, u16_t);
    void send(Packet &packet);
    Idle idle_;
    udp_pcb *pcb_;
    bool opened_;
};
}
#endif
