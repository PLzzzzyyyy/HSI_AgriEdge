#ifndef QSPI_IO_H
#define QSPI_IO_H
/* =============================================================================
 * QSPI Flash 读取 —— 把权重/输入从板载 W25Q256 搬进 DDR
 *
 * 为什么需要这个文件：
 *   加速器的 AXI Master 只能访问 DDR，读不了 Flash。
 *   所以开机时必须有人把权重从 Flash 搬到 DDR，这就是这段代码干的事。
 *
 *   替代原来的 JTAG 灌数据（11.28MB / 0.3MB\s = 42 秒）。
 *
 * ⚠ 只支持低 16MB
 *   标准读命令带 3 字节地址 = 2^24 = 16MB，而 W25Q256 有 32MB。
 *   要用上半部分必须进 4 字节地址模式(0xB7)或用扩展地址寄存器(0xC5)。
 *   本文件不做这件事，布局上保证所有数据都在低 16MB 内。
 *   详见 docs/QSPI_PLAN.md
 * ============================================================================= */

#include "xil_types.h"

/* ---- Flash 布局（与烧写命令的 -offset 必须一致）---- */
#define QSPI_OFF_WEIGHT     0x0000000u   /* 权重，预留 12MB */
#define QSPI_OFF_INPUT      0x0C00000u   /* 输入图，预留 2MB */

/* ---- 实际字节数（用于校验，改数据后要同步）---- */
#define QSPI_WEIGHT_BYTES   11829888u    /* weights/weights_q.bin */
#define QSPI_INPUT_BYTES    1384448u     /* data/input_q_pad4.bin */

#ifdef __cplusplus
extern "C" {
#endif

/* 初始化 QSPI 控制器并读 Flash ID 自检。
 * 返回 XST_SUCCESS / XST_FAILURE。失败时已打印原因。 */
int qspi_init(void);

/* 从 Flash 偏移 flash_off 读 bytes 字节到 dst。
 * dst 通常是 DDR 地址（如 ADDR_WEIGHT_BASE）。
 * ⚠ flash_off + bytes 必须 <= 16MB。 */
int qspi_read(u32 flash_off, void *dst, u32 bytes);

/* 读 JEDEC ID，id3 至少 3 字节。Winbond W25Q256 应为 EF 40 19。 */
int qspi_read_id(u8 *id3);

#ifdef __cplusplus
}
#endif

#endif /* QSPI_IO_H */
