/* Host-only fake GEM: exercise real scan logic, including write safety. */
#include "phy_id.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint32_t ctrl, cfg, cmd;
    uint16_t ids[32][2];
    unsigned reads[32][2], commands, reports, valid;
    int busy, busy_after, frozen_timer, unstable;
    uint64_t time;
} Fake;

static uint32_t rd(void *ctx, uint32_t off) {
    Fake *f = ctx;
    if (off == PHY_GEM_CTRL) return f->ctrl;
    if (off == PHY_GEM_CFG) return f->cfg;
    if (off == PHY_GEM_STATUS) return f->busy ? 0U : PHY_MDIO_IDLE;
    if (off == PHY_GEM_MAINT) {
        unsigned a = (f->cmd >> 23) & 31, r = (f->cmd >> 18) & 31;
        assert(r == 2 || r == 3);
        unsigned n = f->reads[a][r - 2]++;
        return f->ids[a][r - 2] ^ ((f->unstable && a == 3 && n) ? 1U : 0U);
    }
    assert(0); return 0;
}
static void wr(void *ctx, uint32_t off, uint32_t v) {
    Fake *f = ctx;
    if (off == PHY_GEM_CTRL) { assert(!(v & PHY_RX_TX_ENABLE)); f->ctrl = v; }
    else if (off == PHY_GEM_CFG) f->cfg = v;
    else if (off == PHY_GEM_MAINT) {
        /* Clause 22 READ only; no PHY writes, including reset/page changes. */
        assert((v & 0xF0020000U) == 0x60020000U);
        assert(((v >> 18) & 31) == 2 || ((v >> 18) & 31) == 3);
        assert(!(v & 0xFFFFU));
        f->cmd = v; f->commands++;
        if (f->busy_after) f->busy = 1;
    } else assert(0);
}
static uint64_t now(void *ctx) { Fake *f = ctx; if (!f->frozen_timer) f->time += 100; return f->time; }
static void report(void *ctx, const PhySample *s) {
    Fake *f = ctx; f->reports++;
    if (s->kind >= PHY_UNKNOWN) f->valid++;
}
static void init(Fake *f) {
    memset(f, 0, sizeof(*f)); memset(f->ids, 0xFF, sizeof(f->ids));
    f->cfg = 0x12345678U;
}
static int scan(Fake *f) {
    PhyIo io = {f, rd, wr, now, report};
    return phy_scan(&io);
}
int main(void) {
    Fake f;
    init(&f); assert(scan(&f) == 0); assert(f.reports == 32 && f.commands == 128);
    assert(f.ctrl == 0 && f.cfg == 0x12345678U);
    init(&f); f.ids[0][0] = 0x1234; f.ids[0][1] = 0x5678;
    f.ids[31][0] = 0x937C; f.ids[31][1] = 0x4023;
    assert(scan(&f) == 2 && f.valid == 2); /* include address 0 and 31 */
    init(&f); f.ids[3][0] = 0x0022; f.ids[3][1] = 0x1622;
    assert(scan(&f) == 1);
    assert(phy_classify(0x0022, 0x1622, 0x0022, 0x1622) == PHY_KSZ9031);
    assert(phy_classify(0x0022, 0x1562, 0x0022, 0x1562) == PHY_UNKNOWN);
    assert(phy_classify(0x937C, 0x4023, 0x937C, 0x4023) == PHY_JLSEMI_FAMILY);
    assert(phy_classify(0, 0, 0, 0) == PHY_EMPTY);
    assert(phy_classify(0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF) == PHY_EMPTY);
    assert(phy_classify(0xFFFF, 0x1234, 0xFFFF, 0x1234) == PHY_SUSPICIOUS);
    init(&f); f.unstable = 1; f.ids[3][0] = 0x22; f.ids[3][1] = 0x1622;
    assert(scan(&f) == 0);
    assert(phy_classify(0x22, 0x1622, 0x22, 0x1623) == PHY_UNSTABLE);
    init(&f); f.busy = 1; assert(scan(&f) == PHY_ERR_TIMEOUT);
    assert(f.commands == 0 && f.ctrl == 0 && f.cfg == 0x12345678U);
    init(&f); f.busy_after = 1; assert(scan(&f) == PHY_ERR_TIMEOUT);
    assert(f.commands == 1 && f.ctrl == 0 && f.cfg == 0x12345678U);
    init(&f); f.busy = 1; f.frozen_timer = 1;
    assert(scan(&f) == PHY_ERR_TIMEOUT); /* poll cap still terminates */
    init(&f); f.ctrl = PHY_RX_TX_ENABLE; assert(scan(&f) == PHY_ERR_ACTIVE);
    assert(f.commands == 0 && f.cfg == 0x12345678U);
    puts("PASS: scan 0..31, full-ID matching, ambiguity, repeat reads, read-only transactions, bounded waits, restore, active-MAC refusal");
    return 0;
}
