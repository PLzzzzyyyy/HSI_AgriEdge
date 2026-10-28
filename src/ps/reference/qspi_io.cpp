/* =============================================================================
 * QSPI Flash 读取实现
 *
 * 参考例程：4_Source_Code/2_Embedded_Vitis/ZYNQ_Vitis_7020/12_qspi_rw_test
 *
 * 与例程的三处不同（都是有意的）：
 *
 *   1. 用 FAST_READ(0x0B) 单线，不用 QUAD_READ(0x6B)
 *      例程的 FlashQuadEnable() 里有个 `if (ReadBuffer[1] == 0x9D)` ——
 *      0x9D 是 ISSI 的厂商 ID，对我们的 Winbond(0xEF) 它什么都不做。
 *      W25Q256 出厂 QE 位(SR2 bit1)可能是 0，那样 Quad 读会读回垃圾，
 *      而且不会报错。单线读不依赖 QE，先保证正确。
 *      提速见文件末尾说明。
 *
 *   2. 分块读到临时缓冲再 memcpy，不直接读进目标地址
 *      XQspiPs_PolledTransfer 会把命令回显和 dummy 字节也写进接收缓冲的
 *      开头，数据从第 RD_OVERHEAD 字节才开始。若直接把 DDR 地址当接收缓冲，
 *      每一块都会踩掉前一块结尾的 5 个字节。
 *
 *   3. 收发用两个独立缓冲
 *      例程的 WriteBuffer 只有 260 字节却按 4101 字节发送，越界读了内存。
 *      能工作是因为 Flash 在读命令之后不看 MOSI —— 属于侥幸，不照抄。
 * ============================================================================= */

#include "qspi_io.h"
#include "xparameters.h"
#include "xqspips.h"
#include "xil_printf.h"
#include "xtime_l.h"
#include <string.h>

/* ---- Flash 命令 ---- */
#define CMD_FAST_READ       0x0Bu
#define CMD_READ_ID         0x9Fu

/* FAST_READ 的头部开销：1 命令 + 3 地址 + 1 dummy */
#define RD_OVERHEAD         5u

/* 单次传输的数据量。32KB x 2 个缓冲 = 64KB BSS。
 * 调大能减少传输次数，但 BSS 也涨；32KB 下每次传输开销已可忽略。 */
#define CHUNK               (32u * 1024u)

/* 3 字节地址上限 */
#define ADDR_LIMIT_16MB     0x1000000u

static XQspiPs s_qspi;
static int     s_ready = 0;

static u8 s_tx[CHUNK + RD_OVERHEAD];
static u8 s_rx[CHUNK + RD_OVERHEAD];

/* -------------------------------------------------------------------------- */

int qspi_read_id(u8 *id3)
{
    u8 tx[4];
    u8 rx[4];

    if (!s_ready) { return XST_FAILURE; }

    memset(tx, 0, sizeof(tx));
    memset(rx, 0, sizeof(rx));
    tx[0] = CMD_READ_ID;

    if (XQspiPs_PolledTransfer(&s_qspi, tx, rx, 4) != XST_SUCCESS) {
        return XST_FAILURE;
    }

    /* rx[0] 是命令回显，ID 从 rx[1] 开始 */
    id3[0] = rx[1];
    id3[1] = rx[2];
    id3[2] = rx[3];
    return XST_SUCCESS;
}

int qspi_init(void)
{
    XQspiPs_Config *cfg;
    u8  id[3];
    int st;

    cfg = XQspiPs_LookupConfig(XPAR_XQSPIPS_0_DEVICE_ID);
    if (cfg == NULL) {
        xil_printf("  !! QSPI: LookupConfig failed "
                   "(is QSPI enabled in the BD?)\r\n");
        return XST_FAILURE;
    }

    st = XQspiPs_CfgInitialize(&s_qspi, cfg, cfg->BaseAddress);
    if (st != XST_SUCCESS) {
        xil_printf("  !! QSPI: CfgInitialize failed (%d)\r\n", st);
        return XST_FAILURE;
    }

    /* 手动启动 + 手动片选 + 驱动 HOLD_B，与例程一致 */
    XQspiPs_SetOptions(&s_qspi, XQSPIPS_MANUAL_START_OPTION |
                                XQSPIPS_FORCE_SSELECT_OPTION |
                                XQSPIPS_HOLD_B_DRIVE_OPTION);

    /* QSPI 参考时钟 200MHz，/8 = 25MHz。
     * 保守起点，与例程相同。提速见文件末尾。 */
    XQspiPs_SetClkPrescaler(&s_qspi, XQSPIPS_CLK_PRESCALE_8);

    XQspiPs_SetSlaveSelect(&s_qspi);

    s_ready = 1;

    /* 自检：读 JEDEC ID。核心板原理图标的是 Winbond W25Q256 -> EF 40 19 */
    if (qspi_read_id(id) != XST_SUCCESS) {
        xil_printf("  !! QSPI: read ID failed\r\n");
        s_ready = 0;
        return XST_FAILURE;
    }
    xil_printf("  QSPI flash JEDEC ID: %02x %02x %02x", id[0], id[1], id[2]);
    if (id[0] == 0xEF) {
        xil_printf("  (Winbond)\r\n");
    } else {
        xil_printf("  <-- expected EF (Winbond), check the board\r\n");
    }

    /* 全 0 或全 FF = 没接上 / 片选不对 / QSPI 没使能 */
    if ((id[0] == 0x00 && id[1] == 0x00) ||
        (id[0] == 0xFF && id[1] == 0xFF)) {
        xil_printf("  !! QSPI: bogus ID, flash not responding\r\n");
        s_ready = 0;
        return XST_FAILURE;
    }

    return XST_SUCCESS;
}

int qspi_read(u32 flash_off, void *dst, u32 bytes)
{
    u8  *out = (u8 *)dst;
    u32  done = 0;
    XTime t0, t1;

    if (!s_ready) {
        xil_printf("  !! QSPI: not initialized\r\n");
        return XST_FAILURE;
    }

    /* 越过 16MB 会静默读回错误数据（地址高位被丢掉），必须挡住 */
    if (flash_off > ADDR_LIMIT_16MB || bytes > ADDR_LIMIT_16MB ||
        (flash_off + bytes) > ADDR_LIMIT_16MB) {
        xil_printf("  !! QSPI: range 0x%08x+0x%x exceeds 16MB "
                   "(3-byte addressing)\r\n",
                   (unsigned)flash_off, (unsigned)bytes);
        return XST_FAILURE;
    }

    XTime_GetTime(&t0);

    while (done < bytes) {
        u32 n = bytes - done;
        u32 addr = flash_off + done;
        if (n > CHUNK) { n = CHUNK; }

        /* 发送缓冲整体清零，只有前 5 字节有意义；
         * 其余字节在读事务中会被 Flash 忽略，但缓冲必须够长（见文件头注释 3）*/
        memset(s_tx, 0, n + RD_OVERHEAD);
        s_tx[0] = CMD_FAST_READ;
        s_tx[1] = (u8)((addr >> 16) & 0xFF);
        s_tx[2] = (u8)((addr >>  8) & 0xFF);
        s_tx[3] = (u8)( addr        & 0xFF);
        /* s_tx[4] 是 dummy 字节，保持 0 */

        if (XQspiPs_PolledTransfer(&s_qspi, s_tx, s_rx,
                                   n + RD_OVERHEAD) != XST_SUCCESS) {
            xil_printf("  !! QSPI: transfer failed at 0x%08x\r\n",
                       (unsigned)addr);
            return XST_FAILURE;
        }

        memcpy(out + done, s_rx + RD_OVERHEAD, n);
        done += n;
    }

    XTime_GetTime(&t1);
    {
        /* COUNTS_PER_SECOND 是全局定时器频率（CPU/2） */
        u32 us = (u32)(((t1 - t0) * 1000000ULL) / COUNTS_PER_SECOND);
        u32 kbps = (us > 0) ? (u32)(((u64)bytes * 1000ULL) / us) : 0;
        xil_printf("  QSPI: read %u bytes from 0x%08x in %u us (%u KB/s)\r\n",
                   (unsigned)bytes, (unsigned)flash_off,
                   (unsigned)us, (unsigned)kbps);
    }

    return XST_SUCCESS;
}

/* =============================================================================
 * 提速余地（先把正确性跑通再动这里）
 *
 * 当前：FAST_READ 单线 @25MHz -> 约 3.1 MB/s -> 11.28MB 约 3.6 秒
 *       （仍比 JTAG 的 42 秒快十倍以上）
 *
 * 1) 提时钟：W25Q256 的 FAST_READ 支持到 104MHz
 *      XQSPIPS_CLK_PRESCALE_4 -> 50MHz  -> 约 1.8 秒
 *      XQSPIPS_CLK_PRESCALE_2 -> 100MHz -> 约 0.9 秒
 *    改完必须重新校验数据（见下），提频后读错是不会报错的。
 *
 * 2) 上 Quad：理论再快 4 倍，但必须先正确使能 Winbond 的 QE 位
 *    （SR2 bit1，用 0x31 写 SR2，或 0x01 写双字节 SR1+SR2）。
 *    例程那个 FlashQuadEnable() 对 Winbond 是空操作，不能直接用。
 *
 * ⚠ 每次改这里，都要用 main.cpp 里的 sanity_check() 复验权重内容，
 *   或者跑整网对拍那 10 个检测框。读错数据不会有任何报错。
 * ============================================================================= */
