// 板上实现：通过 Vitis HLS 生成的驱动 XTucker_proj 调用 PL 算子（v1.4：片上归一化 + 投影，多一个 stats 输出）。
// 普通板上应用只编译此后端；运行时切换应用定义 TT_HW_RUNTIME_SWITCH，同时链接两种后端与 tt_hw_switch.cpp。
//
// cache 约定（PL 经 HP 口直接读 DDR，不经 CPU cache）：
//   PS 写 → PL 读：x        启动前只清理不作废（clean_range，见下），x 留在 cache 里给残差内核用
//                  w_*      不 flush：权重是 .rodata 常量，init 的整体 flush 之后 CPU 不再写
//   PL 写 → PS 读：out_*、stats  完成后 Xil_DCacheInvalidateRange（每次）；启动前只有在"CPU 可能写过"时才 flush
// 输入/输出/stats 缓冲必须按 cache 行（TT_CACHE_LINE：A9 32、A53 64 字节）对齐，分配容量也按 cache 行向上取整，尾行不得与其他数据共用。
// outputs_clean：自上次整体 flush（init / tt_pl_flush_all）起 CPU 没写过任何 PL 输出缓冲。PL 模式下 CPU 只读输出，
// 读进 cache 的是干净行，PL 写完 DDR 后被 invalidate 丢掉，不会回写；纯 PS 后端写过输出后切回 PL 时切换层调
// tt_pl_flush_all()。任何用 CPU 写 PL 输出缓冲的新代码都必须在下次 start 前调 tt_pl_flush_all()。
// 板上实测（2026-09-19）：每层 flush 权重 + 3 个输出块约 4700 行 cache 操作、0.17 ms，12 层约 2 ms。
#include "tt_hw.h"
#include "tt_net.h"
#include "xtucker_proj.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include <stdio.h>

static XTucker_proj inst;
static struct { int16_t *q, *k, *v; int32_t *stats; u32 blk, stats_bytes; int n_proj; bool busy; } pending;
static bool initialized = false;
static bool outputs_clean = false;
void tt_pl_proj_wait();

int tt_pl_init() {
    if (initialized) { tt_pl_proj_wait(); return 0; }
    int st = XTucker_proj_Initialize(&inst, 0);   // XPAR_XTUCKER_PROJ_0_DEVICE_ID
    if (st != XST_SUCCESS) { xil_printf("XTucker_proj_Initialize failed %d\r\n", st); return st; }
    pending.busy = false;
    // 包括只链接 PL 后端的应用：启动加载的 DDR 数据（权重、.bss 清零过的缓冲）可能仍有脏 cache 行。
    Xil_DCacheFlush();
    outputs_clean = true;
    initialized = true;
    return 0;
}

// 全局 flush 之前必须完成在飞调用并 invalidate 输出，避免旧 cache 行覆盖 PL 新数据。
void tt_pl_flush_all() { tt_pl_proj_wait(); Xil_DCacheFlush(); outputs_clean = true; }

static inline u32 round_line(u32 n) { return (n + (TT_CACHE_LINE - 1u)) & ~(u32)(TT_CACHE_LINE - 1u); }

// PS 写 → PL 读 只需要"清理"（把脏行写回 DDR），不需要作废。BSP 的 Xil_DCacheFlushRange 在 A9 上是清理+作废
// （L1 DCCIMVAC、L2 0x7F0），会把 x 从 L1/L2 踢掉，接下来的残差内核读 x 全部等 DDR（板上实测 2026-09-20：
// ctx 0.45 → 0.73 ms/层、mlp 残差 0.16 → 0.47）。这里用 L1 DCCMVAC + L2 clean-by-PA（0x7B0），x 留在 cache 里。
// A53（AArch64）：BSP 的 FlushRange 同样是 DC CIVAC（清理+作废）；DC CVAC 按虚拟地址清理到一致性点，L1/L2 一起做，
// 不需要像 A9 那样单独操作 L2 控制器。BSP 恒等映射，VA = PA。板上待验证（pitfalls 继承条目）。
#if defined(__aarch64__)
static void clean_range(INTPTR adr, u32 len) {
    UINTPTR a = (UINTPTR)adr & ~(UINTPTR)(TT_CACHE_LINE - 1u);
    const UINTPTR end = (UINTPTR)adr + len;
    for (; a < end; a += TT_CACHE_LINE) __asm__ __volatile__("dc cvac, %0" : : "r"(a) : "memory");
    __asm__ __volatile__("dsb sy" : : : "memory");
}
#elif defined(__arm__)
#include "xil_io.h"
#include "xpseudo_asm.h"
#include "xparameters.h"
static void clean_range(INTPTR adr, u32 len) {
    const u32 mask = mfcpsr();
    mtcpsr(mask | 0xC0u);                                                            // 屏蔽 IRQ/FIQ（同 BSP 的 IRQ_FIQ_MASK）
    u32 a = (u32)adr & ~31u;
    const u32 end = (u32)adr + len;
    for (; a < end; a += 32u) {
        __asm__ __volatile__("mcr p15, 0, %0, c7, c10, 1" : : "r"(a) : "memory");   // DCCMVAC：L1 清理到 PoC（进 L2）
        Xil_Out32(XPS_L2CC_BASEADDR + 0x07B0u, a);                                  // L2 clean by PA
    }
    Xil_Out32(XPS_L2CC_BASEADDR + 0x0730u, 0u);                                     // L2 cache sync：等写回完成
    dsb();
    mtcpsr(mask);
}
#else
#define clean_range(a, l) Xil_DCacheFlushRange((a), (l))   // 主机测试：仍记为一次输入 flush 事件
#endif

// 64 位 FM / 32 位 WT 接口的 IP 要求激活块与 stats 8 字节对齐、因子块 4 字节对齐（当前分配：激活按 cache 行对齐，
// 权重数组 32 字节对齐、每投影跨距 6028 = 4×1507 字节）。不满足时 PL 会读错位的数据，只提示一次。
// IP 的 m_axi 地址是 32 位（HLS config_interface -m_axi_addr64=false）：所有 PL 缓冲必须在低 4 GB（ZU5EV 低 2 GB DDR），
// 否则 (u32) 截断后 PL 读写错地址，只提示一次。
static void check_alignment(const void *x, const void *oq, const void *ok, const void *ov, const void *stats,
                            const void *wq, const void *wk, const void *wv) {
    static bool reported = false;
    if (reported) return;
    const unsigned long long fm = (UINTPTR)x | (UINTPTR)oq | (UINTPTR)ok | (UINTPTR)ov | (UINTPTR)stats;
    const unsigned long long wt = (UINTPTR)wq | (UINTPTR)wk | (UINTPTR)wv;
    if ((fm & 7u) || (wt & 3u)) {
        printf("tt_hw: WARNING unaligned PL buffers (fm|=%llx wt|=%llx)\n", fm, wt);
        reported = true;
    }
    if ((fm | wt) >> 32) {
        printf("tt_hw: ERROR PL buffer above 4 GB, IP addresses are 32-bit (fm|=%llx wt|=%llx)\n", fm, wt);
        reported = true;
    }
}

void tt_pl_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    if (pending.busy) tt_pl_proj_wait();
    check_alignment(x, out_q, out_k, out_v, stats, w_q, w_k, w_v);
    const u32 blk = round_line((u32)(TT_D * n_tok * sizeof(int16_t)));
    const u32 stats_bytes = round_line((u32)(2 * n_tok * sizeof(int32_t)));
    clean_range((INTPTR)x, blk);
    if (!outputs_clean) {                             // 只有整体 flush 之前 CPU 写过输出时才需要（见文件头）
        Xil_DCacheFlushRange((INTPTR)out_q, blk);
        if (n_proj >= 2) Xil_DCacheFlushRange((INTPTR)out_k, blk);
        if (n_proj >= 3) Xil_DCacheFlushRange((INTPTR)out_v, blk);
        Xil_DCacheFlushRange((INTPTR)stats, stats_bytes);
    }

    XTucker_proj_Set_in_r(&inst, (u32)(UINTPTR)x);
    XTucker_proj_Set_out_q(&inst, (u32)(UINTPTR)out_q);
    XTucker_proj_Set_out_k(&inst, (u32)(UINTPTR)out_k);
    XTucker_proj_Set_out_v(&inst, (u32)(UINTPTR)out_v);
    XTucker_proj_Set_stats(&inst, (u32)(UINTPTR)stats);
    XTucker_proj_Set_w_q(&inst, (u32)(UINTPTR)w_q);
    XTucker_proj_Set_w_k(&inst, (u32)(UINTPTR)w_k);
    XTucker_proj_Set_w_v(&inst, (u32)(UINTPTR)w_v);
    XTucker_proj_Set_n_tok(&inst, (u32)n_tok);
    XTucker_proj_Set_n_proj(&inst, (u32)n_proj);
    pending.q = out_q; pending.k = out_k; pending.v = out_v; pending.stats = stats;
    pending.blk = blk; pending.stats_bytes = stats_bytes; pending.n_proj = n_proj;
    pending.busy = true;
    XTucker_proj_Start(&inst);
}

void tt_pl_proj_wait() {
    if (!pending.busy) return;
    while (!XTucker_proj_IsDone(&inst)) { }
    Xil_DCacheInvalidateRange((INTPTR)pending.q, pending.blk);
    if (pending.n_proj >= 2) Xil_DCacheInvalidateRange((INTPTR)pending.k, pending.blk);
    if (pending.n_proj >= 3) Xil_DCacheInvalidateRange((INTPTR)pending.v, pending.blk);
    Xil_DCacheInvalidateRange((INTPTR)pending.stats, pending.stats_bytes);
    pending.busy = false;
}

void tt_pl_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_pl_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
    tt_pl_proj_wait();
}

#ifndef TT_HW_RUNTIME_SWITCH
int tt_hw_init() { return tt_pl_init(); }
void tt_hw_proj_start(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                      const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_pl_proj_start(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
void tt_hw_proj_wait() { tt_pl_proj_wait(); }
void tt_hw_proj(const int16_t *x, int16_t *out_q, int16_t *out_k, int16_t *out_v, int32_t *stats,
                const int16_t *w_q, const int16_t *w_k, const int16_t *w_v, int n_tok, int n_proj) {
    tt_pl_proj(x, out_q, out_k, out_v, stats, w_q, w_k, w_v, n_tok, n_proj);
}
#endif
