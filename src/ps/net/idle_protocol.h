#ifndef HSI_IDLE_PROTOCOL_H
#define HSI_IDLE_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>

// S2a: pure single-owner idle subset. No engine, DMA, heap or network calls.
namespace hsi_idle {
enum { HEADER_BYTES = 12, PING_BYTES = 16, PONG_BYTES = 24, STATUS_BYTES = 92 };
struct Peer {
    uint32_t ipv4;  // opaque lwIP network-order value, NOT a wire-format field
    uint16_t port;
};
struct Packet { Peer to; size_t size; uint8_t bytes[STATUS_BYTES]; };
struct Counters {
    uint32_t tx_pkts, tx_bytes, tx_fail, rx_pkts, rx_bad, rx_gap;
    uint16_t down_cnt;
};
class Idle {
public:
    // Future App supplies a fresh boot identity; no fixed/random fake ID here.
    explicit Idle(uint32_t boot_id);
    // now_us is a monotonic 64-bit clock, not the wrapping wire timestamp.
    // Only exact v1 PING is accepted; all other datagrams are silently rejected.
    bool receive(const uint8_t *data, size_t size, Peer from,
                 uint64_t now_us, Packet &reply);
    bool status(uint64_t now_us, Packet &reply);
    void sent(size_t size, bool ok);
    void bad_input();
    const Counters &counters() const { return counts_; }
private:
    void tick(uint64_t now_us);
    void header(Packet &p, uint8_t type, size_t size, uint64_t now_us);
    uint32_t boot_id_, session_;
    Peer peer_;
    Counters counts_;
    uint16_t tx_seq_, rx_seq_;
    bool have_peer_, online_, have_rx_seq_, have_status_;
    uint64_t last_rx_us_, last_status_us_, down_since_us_, down_total_us_;
};
// Set t3 just before pbuf_take/send, without touching PONG t1/t2.
void stamp(Packet &packet, uint64_t now_us);
}
#endif
