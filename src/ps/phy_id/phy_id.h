#ifndef HSI_PHY_ID_H
#define HSI_PHY_ID_H
#include <stdint.h>

/* ZynqMP GEM / Vitis 2020.2 xemacps_hw.h register definitions. */
#define PHY_GEM_CTRL 0x00U
#define PHY_GEM_CFG 0x04U
#define PHY_GEM_STATUS 0x08U
#define PHY_GEM_MAINT 0x34U
#define PHY_RX_TX_ENABLE 0x0CU
#define PHY_MDIO_ENABLE 0x10U
#define PHY_MDIO_IDLE 0x04U
#define PHY_MDC_MASK 0x001C0000U
#define PHY_MDC_DIV224 0x001C0000U
#define PHY_READ_COMMAND 0x60020000U
#define PHY_TIMEOUT_US 10000U
#define PHY_MAX_POLLS 100000U

enum PhyKind { PHY_EMPTY, PHY_SUSPICIOUS, PHY_UNSTABLE, PHY_UNKNOWN,
               PHY_KSZ9031, PHY_JLSEMI_FAMILY };
enum { PHY_ERR_TIMEOUT = -1, PHY_ERR_ACTIVE = -2 };
typedef struct {
    unsigned addr;
    uint16_t id1, id2, repeat1, repeat2;
    enum PhyKind kind;
} PhySample;
typedef struct {
    void *ctx;
    uint32_t (*read)(void *, uint32_t);
    void (*write)(void *, uint32_t, uint32_t);
    uint64_t (*time_us)(void *);
    void (*report)(void *, const PhySample *);
} PhyIo;

enum PhyKind phy_classify(uint16_t a, uint16_t b, uint16_t c, uint16_t d);
/* >=0: number of stable non-empty responders, NOT a board-model verdict. */
int phy_scan(const PhyIo *io);
#endif
