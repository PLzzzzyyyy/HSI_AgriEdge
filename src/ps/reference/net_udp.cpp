/* =============================================================================
 * 阶段 4.0b：lwIP RAW 模式 UDP 发帧。说明见 net_udp.h
 * ============================================================================= */

#include "net_udp.h"

#include "xparameters.h"
#include "xil_printf.h"
#include "xil_exception.h"
#include "xscugic.h"
#include "xstatus.h"

/* lwIP 是 C 库。Xilinx 的头文件大多有 __cplusplus 保护，但不是全都有
 * （netif/xadapter.h 就没有），统一包起来最省事 —— 嵌套 extern "C" 是合法的。
 * 本项目全部源文件是 .cpp（用户决定），这一步躲不掉。 */
extern "C" {
#include "lwip/err.h"
#include "lwip/init.h"
#include "lwip/inet.h"
#include "lwip/udp.h"
#include "netif/xadapter.h"
}

/* ---- 地址配置。与例程 43 一致，要改就改这里 ----
 * ⚠ PC 网卡必须设成同网段静态 IP（192.168.1.102 / 255.255.255.0），
 *   否则 ARP 不通，板子的包发不出去。板上没有 DHCP（见下方 net_init 注释）。 */
#define BOARD_IP_STR    "192.168.1.10"
#define BOARD_MASK_STR  "255.255.255.0"
#define BOARD_GW_STR    "192.168.1.1"

#define PC_IP_1  192
#define PC_IP_2  168
#define PC_IP_3  1
#define PC_IP_4  102

/* ⚠ 别用 5001 —— 本机的 NI 服务（nidmsrv，随 LabVIEW/NI-DAQ 装的）
 *   常驻占用 UDP 5001，PC 端 bind 会报 WinError 10048。例程 43 用的就是 5001。
 *   6001 也被占了（实测）。50001 在私有端口范围，最不容易再撞。
 *   改这里的话，tools/udp_frame_view.py 的 DEF_PORT 要跟着改。 */
#define UDP_PORT  50001

/* ⚠ 例程 43 的 sys_intr.h 用的是 XPAR_SCUGIC_SINGLE_DEVICE_ID，
 *   我们的 BSP 不生成那个名字 —— xparameters.h 里只有 canonical 的
 *   XPAR_SCUGIC_0_DEVICE_ID（= 0U）。照抄例程会直接编不过。 */
#define GIC_DEVICE_ID   XPAR_SCUGIC_0_DEVICE_ID

/* pbuf 池耗尽时的重试上限。每次重试前先跑一次 net_poll()，
 * 让协议栈把已经发完的 pbuf 回收掉。超过这个数就认为真堵死了，丢包并计数。
 * 取 2000 是因为单次 net_poll 很快，链路正常时一两次就够；
 * 链路断了也只是慢，不会死锁。 */
#define SEND_RETRY   2000

static struct netif    s_netif;
static struct udp_pcb *s_pcb;
static XScuGic         s_gic;
static u32             s_dropped;

/* 包头 + 载荷拼在一起，一次 pbuf_take 搞定，省掉 pbuf_take_at 的偏移计算。
 * 裸机不在栈上放 1KB，放 BSS。 */
static u8 s_pkt[NET_HDR_BYTES + NET_PAYLOAD];

/* 本板 MAC。沿用例程 43 的值 —— 网段里只有一块板，不会撞。 */
static unsigned char s_mac[6] = { 0x00, 0x0a, 0x35, 0x00, 0x01, 0x02 };

static void put_u16(u8 *p, u16 v)
{
    p[0] = (u8)(v & 0xFF);
    p[1] = (u8)(v >> 8);
}

static int gic_init(void)
{
    XScuGic_Config *cfg = XScuGic_LookupConfig(GIC_DEVICE_ID);
    if (cfg == NULL) {
        xil_printf("NET: XScuGic_LookupConfig failed\r\n");
        return XST_FAILURE;
    }
    if (XScuGic_CfgInitialize(&s_gic, cfg, cfg->CpuBaseAddress) != XST_SUCCESS) {
        xil_printf("NET: XScuGic_CfgInitialize failed\r\n");
        return XST_FAILURE;
    }

    /* xemac_add 内部会给 EMACPS 注册中断，所以 GIC 必须先就绪 */
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,
                                 (Xil_ExceptionHandler)XScuGic_InterruptHandler,
                                 &s_gic);
    Xil_ExceptionEnable();
    return XST_SUCCESS;
}

int net_init(void)
{
    ip_addr_t ip, mask, gw, dst;

    if (gic_init() != XST_SUCCESS)
        return XST_FAILURE;

    /* lwIP 核心初始化。
     * ⚠ 这里**没有**调 platform_setup_timer() —— 例程 43 里那个 platform.h
     *   是 Xilinx echo-server 模板的残留，src 下根本没有对应的 .c，
     *   例程自己也从没调用过。纯 UDP 发送 + 静态 IP 不需要 lwIP 定时器
     *   （DHCP、TCP 重传、ARP 老化才需要）。别看到 platform.h 就以为漏了初始化。 */
    lwip_init();

    if (!xemac_add(&s_netif, NULL, NULL, NULL, s_mac,
                   XPAR_XEMACPS_0_BASEADDR)) {
        xil_printf("NET: xemac_add failed (link down? cable?)\r\n");
        return XST_FAILURE;
    }
    netif_set_default(&s_netif);
    netif_set_up(&s_netif);

    if (!inet_aton(BOARD_IP_STR, &ip) ||
        !inet_aton(BOARD_MASK_STR, &mask) ||
        !inet_aton(BOARD_GW_STR, &gw)) {
        xil_printf("NET: bad static IP literal\r\n");
        return XST_FAILURE;
    }
    s_netif.ip_addr = ip;
    s_netif.netmask = mask;
    s_netif.gw      = gw;

    s_pcb = udp_new();
    if (s_pcb == NULL) {
        xil_printf("NET: udp_new failed (out of memory)\r\n");
        return XST_FAILURE;
    }
    if (udp_bind(s_pcb, IP_ADDR_ANY, UDP_PORT) != ERR_OK) {
        xil_printf("NET: udp_bind port %d failed\r\n", UDP_PORT);
        udp_remove(s_pcb);
        s_pcb = NULL;
        return XST_FAILURE;
    }

    IP4_ADDR(&dst, PC_IP_1, PC_IP_2, PC_IP_3, PC_IP_4);
    if (udp_connect(s_pcb, &dst, UDP_PORT) != ERR_OK) {
        xil_printf("NET: udp_connect failed\r\n");
        return XST_FAILURE;
    }

    s_dropped = 0;

    xil_printf("NET: board %s -> PC %d.%d.%d.%d, UDP port %d\r\n",
               BOARD_IP_STR, PC_IP_1, PC_IP_2, PC_IP_3, PC_IP_4, UDP_PORT);
    xil_printf("NET: packet = %d hdr + %d payload = %d bytes\r\n",
               NET_HDR_BYTES, NET_PAYLOAD, NET_HDR_BYTES + NET_PAYLOAD);
    return XST_SUCCESS;
}

void net_poll(void)
{
    xemacif_input(&s_netif);
}

u32 net_dropped(void)
{
    return s_dropped;
}

/* 发一个包。成功返回 1，放弃返回 0（已计入 s_dropped）。 */
static int send_one(const u8 *payload, u32 len,
                    u16 frame_id, u16 pkt_id, u16 pkt_total)
{
    u32 total = NET_HDR_BYTES + len;
    u32 i;
    int retry;

    put_u16(s_pkt + 0, (u16)NET_MAGIC);
    put_u16(s_pkt + 2, frame_id);
    put_u16(s_pkt + 4, pkt_id);
    put_u16(s_pkt + 6, pkt_total);
    for (i = 0; i < len; i++)
        s_pkt[NET_HDR_BYTES + i] = payload[i];

    for (retry = 0; retry < SEND_RETRY; retry++) {
        struct pbuf *p = pbuf_alloc(PBUF_TRANSPORT, (u16)total, PBUF_POOL);
        err_t err;

        if (p == NULL) {
            /* 池空了。跑一次协议栈让它回收已发完的 pbuf，然后重试。 */
            net_poll();
            continue;
        }

        pbuf_take(p, s_pkt, (u16)total);
        err = udp_send(s_pcb, p);
        pbuf_free(p);

        if (err == ERR_OK)
            return 1;
        if (err != ERR_MEM) {
            /* 不是内存问题（链路断、路由不通……），重试也没用，别死循环 */
            s_dropped++;
            return 0;
        }
        net_poll();
    }

    s_dropped++;
    return 0;
}

int net_send_boxes(const NetBox *boxes, int n, u16 frame_id)
{
    u32 total;
    int i;

    if (s_pcb == NULL)
        return 0;
    if (n < 0)
        n = 0;
    if (n > NET_MAX_SEND_BOX)
        n = NET_MAX_SEND_BOX;      /* 超了就截断。2fps 下不可能塞满 40 个 */

    put_u16(s_pkt + 0, (u16)NET_MAGIC_BOX);
    put_u16(s_pkt + 2, frame_id);
    put_u16(s_pkt + 4, (u16)n);
    put_u16(s_pkt + 6, 0);

    for (i = 0; i < n; i++) {
        u8 *p = s_pkt + NET_BOX_HDR + i * NET_BOX_BYTES;
        put_u16(p + 0, (u16)boxes[i].left);     /* s16 按小端原样放，PC 端用 '<h' 解 */
        put_u16(p + 2, (u16)boxes[i].top);
        put_u16(p + 4, (u16)boxes[i].right);
        put_u16(p + 6, (u16)boxes[i].bottom);
        put_u16(p + 8, boxes[i].score_milli);
        p[10] = boxes[i].cls;
        p[11] = 0;
    }

    total = NET_BOX_HDR + (u32)n * NET_BOX_BYTES;

    /* 框包只有几百字节，不像帧包那样会把 pbuf 池打空，一次就该成功。
     * 真失败了也不重试 —— 下一帧马上又发一组，重试没意义。 */
    {
        struct pbuf *p = pbuf_alloc(PBUF_TRANSPORT, (u16)total, PBUF_POOL);
        err_t err;
        if (p == NULL) {
            s_dropped++;
            return 0;
        }
        pbuf_take(p, s_pkt, (u16)total);
        err = udp_send(s_pcb, p);
        pbuf_free(p);
        if (err != ERR_OK) {
            s_dropped++;
            return 0;
        }
    }
    return 1;
}

int net_send_frame(const u8 *frame, u32 nbytes, u16 frame_id){
    u16 pkt_total;
    u16 pkt_id;
    int sent = 0;
    u32 off = 0;

    if (s_pcb == NULL || frame == NULL || nbytes == 0)
        return 0;

    /* 向上取整。921600 / 1024 = 900 整除，但别把这个当前提写死 ——
     * 换分辨率就不整除了。 */
    pkt_total = (u16)((nbytes + NET_PAYLOAD - 1) / NET_PAYLOAD);

    for (pkt_id = 0; pkt_id < pkt_total; pkt_id++) {
        u32 len = nbytes - off;
        if (len > NET_PAYLOAD)
            len = NET_PAYLOAD;

        sent += send_one(frame + off, len, frame_id, pkt_id, pkt_total);
        off  += len;
    }

    return sent;
}

/* ---- 增量发帧 ----
 * 说明见 net_udp.h。状态是文件级 static —— 同一时刻只允许一帧在发，
 * 这条链路上不存在并发发送（主循环和加速器忙等钩子是串行执行的）。 */
static const u8 *s_tx_buf   = NULL;
static u32       s_tx_bytes = 0;
static u16       s_tx_id    = 0;
static u16       s_tx_pkt   = 0;   /* 下一个要发的包号 */
static u16       s_tx_total = 0;

void net_frame_begin(const u8 *frame, u32 nbytes, u16 frame_id)
{
    if (s_pcb == NULL || frame == NULL || nbytes == 0) {
        s_tx_buf = NULL;
        return;
    }
    s_tx_buf   = frame;
    s_tx_bytes = nbytes;
    s_tx_id    = frame_id;
    s_tx_pkt   = 0;
    s_tx_total = (u16)((nbytes + NET_PAYLOAD - 1) / NET_PAYLOAD);
}

int net_frame_active(void)
{
    return (s_tx_buf != NULL && s_tx_pkt < s_tx_total);
}

int net_frame_step(int max_pkts)
{
    int i;

    if (!net_frame_active())
        return 1;

    for (i = 0; i < max_pkts && s_tx_pkt < s_tx_total; i++, s_tx_pkt++) {
        u32 off = (u32)s_tx_pkt * NET_PAYLOAD;
        u32 len = s_tx_bytes - off;
        if (len > NET_PAYLOAD)
            len = NET_PAYLOAD;
        send_one(s_tx_buf + off, len, s_tx_id, s_tx_pkt, s_tx_total);
    }

    if (s_tx_pkt >= s_tx_total) {
        s_tx_buf = NULL;
        return 1;
    }
    return 0;
}
