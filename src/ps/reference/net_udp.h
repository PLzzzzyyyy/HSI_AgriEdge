#ifndef NET_UDP_H
#define NET_UDP_H
/* =============================================================================
 * 阶段 4.0b：DDR 里的一帧 RGB888 -> PS 以太网 UDP -> PC
 *
 * 只借了正点原子例程 43 的网络代码（udp_perf_server.c + main.c 里的 lwIP
 * 初始化 + sys_intr.c 的 GIC 初始化）。**它的采集半边是 JPEG 链路，一行没抄**
 * —— 见 docs/PITFALLS.md [2026-08-24] 那条。我们的采集走 VDMA（cam_vdma.cpp）。
 *
 * 与例程 43 的四处差异（都是它的问题，不是风格偏好）：
 *   ① 它的 udp_tx_data(buf, len) 收了 len 却在函数体里硬编码 1024，
 *      只能发定长包。我们一帧 921600 字节 = 900 包，必须真的分包。
 *   ② 它忽略 udp_send 的返回值。pbuf 池耗尽时返回 ERR_MEM，包就静默丢了。
 *      这里检查返回值 + 重试 + 统计丢包数。
 *   ③ 它没有包头，PC 端无法重组（UDP 不保证顺序，也可能丢包）。这里加了 8 字节。
 *   ④ 它的 GIC 宏是 XPAR_SCUGIC_SINGLE_DEVICE_ID，我们的 BSP 不生成那个名字。
 * ============================================================================= */

#include "xil_types.h"

/* ---- 包格式 ----
 * 每包 = 8 字节包头 + 1440 字节载荷 = 1448 字节。
 * 帧长 = 1448 + 8(UDP) + 20(IP) = 1476 < 1500 MTU，不会被 IP 分片。
 * 一帧 640*480*3 = 921600 字节，正好 640 包，无余数（1440 * 640 = 921600）。
 *
 *   偏移 0  u16  magic      固定 0x5A5A，PC 端拿它丢弃杂包
 *   偏移 2  u16  frame_id   帧号，每帧 +1（回绕无所谓，PC 端只比较是否相等）
 *   偏移 4  u16  pkt_id     包序号 0..pkt_total-1，PC 端据此算写入偏移
 *   偏移 6  u16  pkt_total  本帧总包数
 *
 * 全部小端（ARM 和 x86 都是小端，PC 端直接 struct.unpack('<HHHH')）。
 *
 * ⚠ 为什么必须有包头：UDP 既不保证顺序也不保证到达。没有 pkt_id 就没法重组，
 *   没有 frame_id 就分不清"这包属于哪一帧"—— 两帧的包混在一起会拼成乱码，
 *   而且看起来很像"采集坏了"，白查半天。
 *
 * ⚠ 改 NET_PAYLOAD 必须同步改 tools/udp_frame_view.py 的 PAYLOAD ——
 *   PC 端按 pkt_id * PAYLOAD 算写入偏移，两边不一致会拼出错位的花屏。
 *
 * ★ 2026-08-30 从 1024 提到 1440 的理由：发一帧的 25.4ms 里几乎全是
 *   lwIP 每包的固定开销（900 包 × 28.2us），跟数据量关系不大。
 *   包数 -29% -> tx 约 18ms。流水化之后 tx 吃掉钩子 81% 的 CPU，
 *   是显示帧率上不去的直接原因（钩子 CPU 已用 86%）。
 *   上限来自 BSP 的 PBUF_POOL_BUFSIZE=1700：1448 仍装在**单个** pbuf 里，
 *   再大就会被拆成 pbuf 链，反而变慢。 */
#define NET_MAGIC        0x5A5Au
#define NET_HDR_BYTES    8
#define NET_PAYLOAD      1440

/* ---- 4.1 新增：检测框包 ----
 * 用另一个 magic 与帧包区分，PC 端一个 socket 收两种包。
 *
 *   偏移 0  u16  magic = 0x5B5B
 *   偏移 2  u16  frame_id      与哪一帧的画面对应
 *   偏移 4  u16  n_box
 *   偏移 6  u16  (保留, 0)
 *   之后每框 12 字节：
 *          s16 left, s16 top, s16 right, s16 bottom, u16 score_milli, u8 cls, u8 pad
 *
 * 40 框 = 8 + 480 = 488 字节，一个包装得下，不用分包。
 * 类别只发索引，**不发字符串** —— PC 端有自己的 VOC 名字表。
 * score 是千分位整数（0..1000），与 detect_get 一致：xil_printf 没有 %f，
 * 线格式也本该是定宽整数。 */
#define NET_MAGIC_BOX     0x5B5Bu
#define NET_BOX_HDR       8
#define NET_BOX_BYTES     12
#define NET_MAX_SEND_BOX  40

typedef struct {
    s16 left, top, right, bottom;
    u16 score_milli;      /* 0..1000 */
    u8  cls;              /* 类别索引，VOC 是 0..19 */
} NetBox;

#ifdef __cplusplus
extern "C" {
#endif

/* GIC + lwIP + UDP socket 一次性初始化。返回 XST_SUCCESS / XST_FAILURE。 */
int  net_init(void);

/* 把 frame[0..nbytes) 分包发出去，返回实际发出的包数。
 * nbytes 不必是 NET_PAYLOAD 的整数倍，最后一包会短一些。
 *
 * ⚠ 调用方负责先 invalidate cache。这里是 CPU memcpy 读 DDR，
 *   而帧是 VDMA 绕过 CPU 写进去的 —— 不 invalidate 会读到 cache 里的旧帧。
 *   用 cam_frame_invalidate()，别用 Flush（方向反了，见 docs/PITFALLS.md）。 */
int  net_send_frame(const u8 *frame, u32 nbytes, u16 frame_id);

/* 把 n 个检测框打成一个包发出去（n 会被钳到 NET_MAX_SEND_BOX）。
 * 返回 1 成功、0 失败。n == 0 时也发 —— PC 端据此清掉上一帧的框，
 * 否则画面上会残留一组永远不消失的框。 */
int  net_send_boxes(const NetBox *boxes, int n, u16 frame_id);

/* 喂 lwIP 收包。ARP 请求要回应，否则 PC 那边根本收不到我们的包。
 * 主循环里必须一直调。 */
void net_poll(void);

/* 累计因 pbuf 池耗尽丢掉的包数。一直是 0 说明 BSP 的 lwIP 参数够用；
 * 一直在涨就去调大 pbuf_pool_size / memp_n_pbuf（见 docs/PITFALLS.md）。 */
u32  net_dropped(void);

/* ---- 增量发帧（4.1 让推理期间画面继续流动用）----
 *
 * net_send_frame() 一次把 900 个包全发完，要 25.5ms。在加速器的忙等循环里
 * 这么干是不行的：这 25.5ms 内不轮询 ap_done，每层都可能晚 25ms 才发现算完，
 * 30 层累计能多出 750ms —— 比省下来的多得多。
 *
 * 拆成 begin + 反复 step，每次只发几个包（几十 us），
 * 调用方就能在包与包之间继续查 ap_done。
 *
 *     net_frame_begin(addr, nbytes, id);
 *     while (!done) { net_frame_step(8); ...poll ap_done... }
 *
 * ⚠ 一次只能有一帧在发。net_frame_active() 非 0 时再 begin 会丢掉前一帧的剩余部分。
 * ⚠ 整个发送期间 frame 指向的缓冲不能被覆盖 —— 三缓冲下余量是
 *   (N-1)×帧周期≈58ms，按每次 8 包、调用足够频繁算，发完一帧约 10ms，够用。 */
void net_frame_begin(const u8 *frame, u32 nbytes, u16 frame_id);

/* 最多发 max_pkts 个包。返回 1 表示这一帧已发完（或本来就没有在发的帧）。 */
int  net_frame_step(int max_pkts);

/* 1 = 还有帧没发完 */
int  net_frame_active(void);

#ifdef __cplusplus
}
#endif

#endif /* NET_UDP_H */
