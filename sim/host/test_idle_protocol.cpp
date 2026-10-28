// Pure byte/state boundary checks. No lwIP stubs, sockets, engine or fake board.
#include "idle_protocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
using namespace hsi_idle;
static unsigned checks = 0;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static void p16(uint8_t *p, uint16_t x) { p[0] = uint8_t(x); p[1] = uint8_t(x >> 8); }
static void p32(uint8_t *p, uint32_t x) {
    for (unsigned i=0; i<4; ++i) p[i] = uint8_t(x >> (8*i));
}
static uint32_t u32(const uint8_t *p) {
    return uint32_t(p[0]) | (uint32_t(p[1])<<8) | (uint32_t(p[2])<<16) | (uint32_t(p[3])<<24);
}
static void ping(uint8_t *p, uint16_t seq, uint32_t session, uint32_t time=0x89abcdef) {
    memset(p, 0, PING_BYTES); p16(p, 0x4548); p[2]=5; p[3]=1;
    p16(p+4, 0xffff); p16(p+6, seq); p32(p+8, time); p32(p+12, session);
}
static void vector(const char *name, const uint8_t *p, size_t n) {
    printf("%s=", name);
    for (size_t i=0; i<n; ++i) printf("%02x", unsigned(p[i]));
    puts("");
}
int main() {
    const Peer a={0x0201a8c0, 54321}, b={0x0301a8c0, 60000};
    uint8_t p[PING_BYTES]; Packet out;
    Idle idle(0x12345678);
    CHECK(!idle.status(100, out)); CHECK(out.size==0);
    ping(p, 0xfffe, 0x10203040);
    vector("ping", p, sizeof(p));
    CHECK(idle.receive(p, sizeof(p), a, 0x100000123ULL, out));
    CHECK(out.size==24 && out.to.ipv4==a.ipv4 && out.to.port==a.port);
    stamp(out, 0x100000130ULL);
    vector("pong", out.bytes, out.size);
    idle.sent(out.size, true);
    CHECK(idle.status(0x100000140ULL, out));
    vector("status", out.bytes, out.size);
    CHECK(out.size==92 && out.bytes[32]==0 && out.bytes[33]==0);
    CHECK(u32(out.bytes+20)==0x7fc00000 && u32(out.bytes+24)==0x7fc00000);
    CHECK(u32(out.bytes+28)==0x7fc00000);
    // First STATUS snapshot includes PONG, not its own not-yet-completed send.
    CHECK(u32(out.bytes+52)==1 && u32(out.bytes+56)==24);
    idle.sent(92, false);
    CHECK(idle.counters().tx_fail==1 && idle.counters().tx_pkts==1);

    // Exact bounds: reject without reading data, or copying to a reply.
    Idle bad(1);
    for (size_t n=0; n<=17; ++n) if (n!=16) {
        CHECK(!bad.receive(p, n, b, 0, out)); CHECK(out.size==0);
    }
    CHECK(!bad.receive(0, 16, a, 0, out));
    CHECK(!bad.receive(p, size_t(-1), a, 0, out));
    // Wrong magic (each byte), every unsupported version/type, including business commands.
    for (unsigned i=0; i<2; ++i) { p[i]^=1; CHECK(!bad.receive(p,16,a,0,out)); p[i]^=1; }
    for (unsigned v=0; v<256; ++v) if (v!=1) {
        p[3]=uint8_t(v); CHECK(!bad.receive(p,16,a,0,out));
    }
    p[3]=1;
    for (unsigned t=0; t<256; ++t) if (t!=5) {
        p[2]=uint8_t(t); CHECK(!bad.receive(p,16,a,0,out));
    }
    p[2]=5;
    CHECK(!bad.receive(p,16,Peer{a.ipv4,0},0,out));
    CHECK(!bad.receive(p,16,Peer{0,a.port},0,out));
    CHECK(bad.counters().rx_bad==533 && bad.counters().rx_pkts==0);
    CHECK(!bad.status(2000000,out));  // invalid traffic cannot establish a peer

    // Unaligned input and max-valued fields, including source port, are supported.
    uint8_t unaligned[17]; ping(unaligned+1,0xffff,0xffffffff,0xffffffff);
    CHECK(bad.receive(unaligned+1,16,Peer{0x0100007f,65535},0,out));
    CHECK(out.to.port==65535 && u32(out.bytes+16)==0xffffffff);

    Idle state(42);
    ping(p,65535,7); CHECK(state.receive(p,16,a,0,out));
    CHECK(state.status(0,out)); CHECK(out.bytes[50]==1);
    CHECK(!state.status(249999,out)); CHECK(state.status(250000,out));
    ping(p,0,7); CHECK(state.receive(p,16,a,250001,out));
    CHECK(state.counters().rx_gap==0);
    ping(p,3,7); CHECK(state.receive(p,16,a,300000,out));
    CHECK(state.counters().rx_gap==2);
    CHECK(state.receive(p,16,a,300001,out));  // duplicate heartbeat, not command retry
    ping(p,2,7); CHECK(state.receive(p,16,a,300002,out));
    CHECK(state.counters().rx_gap==2);
    ping(p,4,7); CHECK(state.receive(p,16,a,300003,out));
    CHECK(state.counters().rx_gap==2);  // old packet did not roll back sequence baseline
    // Non-PING does not change source/session or refresh liveness.
    p[2]=1; CHECK(!state.receive(p,16,b,500000,out)); p[2]=5;
    CHECK(state.status(1050004,out)); CHECK(out.to.ipv4==a.ipv4 && out.to.port==a.port);
    CHECK(!state.status(1300002,out)); CHECK(state.counters().down_cnt==0);
    CHECK(!state.status(1300003,out)); CHECK(state.counters().down_cnt==1);
    CHECK(state.status(2050004,out)); CHECK(out.bytes[50]==0);
    CHECK(u32(out.bytes+88)==750);
    ping(p,100,7); CHECK(state.receive(p,16,a,2200003,out));
    CHECK(state.counters().rx_gap==2);  // offline gap suppressed
    CHECK(state.status(2200003,out)); CHECK(out.bytes[50]==1);
    CHECK(u32(out.bytes+88)==900 && out.bytes[84]==1);
    // Endpoint changes (IP and port) and new sessions reset only RX baseline.
    ping(p,30000,7); CHECK(state.receive(p,16,b,2200010,out));
    CHECK(out.to.ipv4==b.ipv4 && out.to.port==b.port);
    CHECK(state.counters().rx_gap==2);
    ping(p,40000,7); CHECK(state.receive(p,16,Peer{b.ipv4,1234},2200020,out));
    CHECK(out.to.port==1234 && state.counters().rx_gap==2);
    ping(p,0,0); CHECK(state.receive(p,16,b,2200030,out));
    CHECK(state.counters().rx_gap==2 && state.status(2200030,out));
    CHECK(u32(out.bytes+40)==0 && out.bytes[54]==0 && out.bytes[55]==0);
    // 16-bit TX wrap is a pure encoding boundary, not a performance/network test.
    Idle wrap(1); ping(p,0,1);
    for (unsigned i=0; i<=65536; ++i) {
        CHECK(wrap.receive(p,16,a,i,out));
        CHECK(out.bytes[6]==uint8_t(i) && out.bytes[7]==uint8_t(i>>8));
    }
    printf("rejected_datagrams=533\nchecks=%u\nresult=PASS\n", checks);
    return 0;
}
