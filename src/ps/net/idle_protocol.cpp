#include "idle_protocol.h"
#include <string.h>
namespace hsi_idle {
namespace {
const uint64_t ONLINE_US = 1000000;
uint16_t u16(const uint8_t *p) {
    return uint16_t(uint16_t(p[0]) | (uint16_t(p[1]) << 8));
}
uint32_t u32(const uint8_t *p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
           (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
void put16(uint8_t *p, uint16_t v) { p[0] = uint8_t(v); p[1] = uint8_t(v >> 8); }
void put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = uint8_t(v >> (8 * i));
}
bool same(Peer a, Peer b) { return a.ipv4 == b.ipv4 && a.port == b.port; }
}
Idle::Idle(uint32_t boot_id)
    : boot_id_(boot_id), session_(0), peer_{0, 0}, counts_{}, tx_seq_(0), rx_seq_(0),
      have_peer_(false), online_(false), have_rx_seq_(false), have_status_(false),
      last_rx_us_(0), last_status_us_(0), down_since_us_(0), down_total_us_(0) {}
void Idle::tick(uint64_t now_us) {
    if (online_ && now_us - last_rx_us_ >= ONLINE_US) {
        online_ = false; down_since_us_ = last_rx_us_ + ONLINE_US;
        ++counts_.down_cnt;
        have_rx_seq_ = false;  // offline window is never counted as packet loss
    }
}
void Idle::header(Packet &p, uint8_t type, size_t size, uint64_t now_us) {
    memset(p.bytes, 0, sizeof(p.bytes));
    p.to = peer_; p.size = size;
    put16(p.bytes, 0x4548); p.bytes[2] = type; p.bytes[3] = 1;
    // task stays zero: no task is owned, not even the historic ROI.
    put16(p.bytes + 6, tx_seq_++); stamp(p, now_us);
}
void stamp(Packet &p, uint64_t now_us) { put32(p.bytes + 8, uint32_t(now_us)); }
void Idle::bad_input() { ++counts_.rx_bad; }
bool Idle::receive(const uint8_t *data, size_t size, Peer from,
                   uint64_t now_us, Packet &reply) {
    reply.size = 0; tick(now_us);
    // Check length before dereference: null, short and oversized input is safe.
    if (!data || size != PING_BYTES || u16(data) != 0x4548 ||
        data[2] != 0x05 || data[3] != 1 || from.port == 0 || from.ipv4 == 0) {
        bad_input(); return false;
    }
    const uint32_t session = u32(data + 12);
    const uint16_t seq = u16(data + 6);
    const bool reset = !have_peer_ || !online_ || session != session_ || !same(from, peer_);
    if (reset) have_rx_seq_ = false;
    if (have_rx_seq_) {
        const uint16_t delta = uint16_t(seq - rx_seq_);
        if (delta > 0 && delta < 0x8000) {
            counts_.rx_gap += uint32_t(delta - 1); rx_seq_ = seq;
        }
        // Old/duplicate PING still gets PONG, but is NOT a repeated business command.
    } else { rx_seq_ = seq; have_rx_seq_ = true; }
    if (have_peer_ && !online_) down_total_us_ += now_us - down_since_us_;
    peer_ = from; session_ = session; have_peer_ = online_ = true; last_rx_us_ = now_us;
    if (reset) have_status_ = false;
    ++counts_.rx_pkts;
    header(reply, 0x84, PONG_BYTES, now_us);
    put16(reply.bytes + 12, seq); put32(reply.bytes + 16, u32(data + 8));
    put32(reply.bytes + 20, uint32_t(now_us));
    return true;
}
bool Idle::status(uint64_t now_us, Packet &reply) {
    reply.size = 0; tick(now_us);
    if (!have_peer_) return false;  // never send unsolicited packets to a fixed IP
    const uint64_t period = online_ ? 250000 : ONLINE_US;
    if (have_status_ && now_us - last_status_us_ < period) return false;
    have_status_ = true; last_status_us_ = now_us;
    header(reply, 0x82, STATUS_BYTES, now_us);
    // done/total/state/flags/pad=0: idle without a task, NOT an inference result.
    // IEEE754 quiet NaN: unavailable, never a made-up zero/old board measurement.
    put32(reply.bytes + 20, 0x7fc00000); put32(reply.bytes + 24, 0x7fc00000);
    put32(reply.bytes + 28, 0x7fc00000);
    uint8_t *tail = reply.bytes + 36;
    put32(tail, boot_id_); put32(tail + 4, session_);
    // wcrc/front_row=0: no model/task. PHY bit not asserted (unobserved).
    tail[14] = online_ ? 1 : 0;
    put32(tail + 16, counts_.tx_pkts); put32(tail + 20, counts_.tx_bytes);
    put32(tail + 24, counts_.tx_fail);
    // tx_retx/rx_dup=0: no ROW or executable commands in this subset.
    put32(tail + 32, counts_.rx_pkts); put32(tail + 36, counts_.rx_bad);
    put32(tail + 40, counts_.rx_gap); put16(tail + 48, counts_.down_cnt);
    const uint64_t down = down_total_us_ + (online_ ? 0 : now_us - down_since_us_);
    put32(tail + 52, uint32_t(down / 1000));
    return true;
}
void Idle::sent(size_t size, bool ok) {
    if (ok) { ++counts_.tx_pkts; counts_.tx_bytes += uint32_t(size); }
    else ++counts_.tx_fail;
}
}
