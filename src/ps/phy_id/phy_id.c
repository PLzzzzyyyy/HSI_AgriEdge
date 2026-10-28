#include "phy_id.h"

enum PhyKind phy_classify(uint16_t a, uint16_t b, uint16_t c, uint16_t d) {
    if (a != c || b != d) return PHY_UNSTABLE;
    if ((a == 0 && b == 0) || (a == 0xFFFF && b == 0xFFFF)) return PHY_EMPTY;
    if (a == 0 || a == 0xFFFF || b == 0 || b == 0xFFFF) return PHY_SUSPICIOUS;
    /* KSZ9031 ID 0x0022162x, low nibble is silicon revision. */
    if (a == 0x0022 && (b & 0xFFF0) == 0x1620) return PHY_KSZ9031;
    /* ALINX patch identifies JL2121 by vendor ID1 only; do not overclaim model. */
    if (a == 0x937C) return PHY_JLSEMI_FAMILY;
    return PHY_UNKNOWN;
}

static int idle(const PhyIo *io) {
    uint64_t start = io->time_us(io->ctx);
    for (unsigned n = 0; n < PHY_MAX_POLLS; ++n) {
        if (io->read(io->ctx, PHY_GEM_STATUS) & PHY_MDIO_IDLE) return 0;
        if (io->time_us(io->ctx) - start >= PHY_TIMEOUT_US) break;
    }
    return PHY_ERR_TIMEOUT;
}

static int read_id(const PhyIo *io, unsigned addr, unsigned reg, uint16_t *v) {
    if (idle(io) < 0) return PHY_ERR_TIMEOUT;
    io->write(io->ctx, PHY_GEM_MAINT,
              PHY_READ_COMMAND | (addr << 23) | (reg << 18));
    if (idle(io) < 0) return PHY_ERR_TIMEOUT;
    *v = (uint16_t)io->read(io->ctx, PHY_GEM_MAINT);
    return 0;
}

int phy_scan(const PhyIo *io) {
    uint32_t ctrl = io->read(io->ctx, PHY_GEM_CTRL);
    uint32_t cfg = io->read(io->ctx, PHY_GEM_CFG);
    int count = 0;
    /* Never take over a running network application. Cold PS init is required. */
    if (ctrl & PHY_RX_TX_ENABLE) return PHY_ERR_ACTIVE;
    io->write(io->ctx, PHY_GEM_CFG, (cfg & ~PHY_MDC_MASK) | PHY_MDC_DIV224);
    io->write(io->ctx, PHY_GEM_CTRL, PHY_MDIO_ENABLE);
    for (unsigned addr = 0; addr < 32; ++addr) {
        PhySample s = {addr, 0, 0, 0, 0, PHY_EMPTY};
        if (read_id(io, addr, 2, &s.id1) < 0 ||
            read_id(io, addr, 3, &s.id2) < 0 ||
            read_id(io, addr, 2, &s.repeat1) < 0 ||
            read_id(io, addr, 3, &s.repeat2) < 0) {
            count = PHY_ERR_TIMEOUT;
            break; /* a stuck management bus is not 32 absent PHYs */
        }
        s.kind = phy_classify(s.id1, s.id2, s.repeat1, s.repeat2);
        if (s.kind >= PHY_UNKNOWN) ++count;
        io->report(io->ctx, &s);
    }
    io->write(io->ctx, PHY_GEM_CTRL, ctrl);
    io->write(io->ctx, PHY_GEM_CFG, cfg);
    return count;
}
