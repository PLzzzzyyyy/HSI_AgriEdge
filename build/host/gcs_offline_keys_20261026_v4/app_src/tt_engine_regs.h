// tt_engine_regs.h —— 整网引擎（tt_engine）PS/PL 共用契约：常量、DDR 布局、寄存器语义、模式位、错误码。
//
// 纯 C 头文件：HLS 顶层（src/hls/tt_engine.cpp）、PS 驱动（src/ps/tt_hw_engine.cpp）、主机参考（sim/host）都包含它。
// 定点格式（位宽、小数位）不在这里，在 src/hls/tt_types.h 与 model/quant.py::Fmt；两边改动规则见 docs/engine_arch.md §3。
// 寄存器偏移由 Vitis HLS 按顶层函数参数顺序生成（xtt_engine_hw.h），PS 只用生成的 XTt_engine_Set_*/Get_* API，
// 本文件规定的是参数名、位宽、语义和 DDR 侧的布局；顶层参数顺序一旦冻结不得再改（改了驱动偏移就变）。
// 版本：TT_ENGINE_VERSION 在返回值 [15:8] 回读，PS 启动时核对，不一致就拒绝运行。
#ifndef TT_ENGINE_REGS_H
#define TT_ENGINE_REGS_H

#define TT_ENGINE_VERSION      4        // ABI4: genuine attention + RTL cycles; TTE2 package stays version 2.
                                        // v3 = 09-24 立方体改 bfp（波段 270 存每条光谱的 2 幂指数，旧 cube_i16.bin 不可混用）；寄存器、参数顺序、DDR 尺寸与 v2 相同。不兼容改动 +1

// ---------------------------------------------------------------- 网络常量（只支持 unoverlapping：N = 6）
#define TT_ENGINE_W            7        // 空间窗边长
#define TT_ENGINE_J            54       // 每 token 光谱长度
#define TT_ENGINE_D            2646     // 每 token 元素数 7*7*54
#define TT_ENGINE_N            6        // token 数（cls + 5），引擎固定，不支持 overlapping 的 10
#define TT_ENGINE_LAYERS       12
#define TT_ENGINE_NPROJ        4        // 每层 4 个投影：q, k, v, mlp
#define TT_ENGINE_NF           3014     // 每投影因子元素数 M1(49)+M2(49)+M3(2916)
#define TT_ENGINE_BLK_ELEMS    15876    // 一个激活块 D*N 个元素，内存序 (p, n)：元素 (p, n) 在 p*N + n
#define TT_ENGINE_BANDS        270      // 模型波段数
#define TT_ENGINE_PATCH_ELEMS  13230    // 7*7*270
#define TT_ENGINE_NCLS_MAX     24       // 分类头最多类别数（三景最多 22）

// ---------------------------------------------------------------- 批处理
// 片上同时持有的 patch 数 P 是编译参数 TT_P_MAX（docs/engine_arch.md §4.5），PS 不需要知道：
// 一次调用可以给任意 n_patch 个 patch / 像素，引擎内部按 P 轮转。
#define TT_ENGINE_NPATCH_MAX   65535    // 一次调用的 patch / 像素数上限

// ---------------------------------------------------------------- DDR 布局（所有基址 64 字节对齐 = A53 cache 行 = 8 拍 64 位 AXI；全部在低 4 GB）
// 立方体（FULL + CUBE 模式的输入，M3b）：PC 预处理（高斯 + 全景归一化 + 3 像素零边）后逐光谱 2 的幂缩放量化的 int16（bfp，v3），
// HWC：填充后像素 (row, col) 的光谱在 cube + (row * cube_w + col) * CUBE_PIX_BYTES，波段 b 在 +2b；
// 波段 270 = 该光谱的指数 e（0..TT_ENGINE_CUBE_EMAX，q = round(x·2^e)），波段 271 补 0。前端先按窗内最小指数右移舍入对齐（docs/engine_arch.md §3.6）。
#define TT_ENGINE_CUBE_BANDS   272      // 每像素存 272 个 int16 = 544 B = 68 个 64 位字（270 个 = 540 B 不是 8 字节对齐）
#define TT_ENGINE_CUBE_PIX_BYTES 544
#define TT_ENGINE_CUBE_EXP_BAND 270     // 指数所在波段
#define TT_ENGINE_CUBE_EMAX    15       // 指数上限（全零光谱取此值）
#define TT_ENGINE_FRONT_S      48       // 前端 g 的定标：g = trunc(min(float32(sqrt((n-1)/n)·2^S) / sqrtf((float)V), 2^25-1))，xn(Q.24) = d·g >> (S-24)
// 输入块（FULL 且非 CUBE 模式，M3a / 调试；PROJ 模式）：int16 Q3.12，D*N 个元素，内存序，与 v1.4 的 in 完全相同（PS 现有 tt_embed 可用）
#define TT_ENGINE_IN_BYTES     31752                        // 15876 * 2
#define TT_ENGINE_IN_STRIDE    31808                        // 向上取整到 64 B：patch i 的块在 x_in + i*STRIDE
// PROJ 模式输出块（q/k/v/mlp）：int16 Q3.12（饱和），布局同输入；stats 每 patch 64 B：token n 的 64 位字 {inv_q24[63:32], mean_q24[31:0]}，与 v1.4 相同
#define TT_ENGINE_OUT16_STRIDE 31808
#define TT_ENGINE_STATS_STRIDE 64

// FULL 模式输出（x_out），由 mode 的 OUT 字段选：
//   CLASS （默认）每像素一个 32 位字，像素 i 在 x_out + 4i：[7:0] 类别号，[15:8] 0，[31:16] 置信度 = 最大 softmax 值 Q0.16（1.0 饱和为 0xFFFF）
//   LOGITS 每像素 128 B，像素 i 在 x_out + 128i：int32 × 32 槽，前 ncls 个有效，值 = 整数 × 2^-TT_ENGINE_LOGIT_FRAC，其余槽写 0
//   FEAT  每像素终块 int32 × 15876（内存序），像素 i 在 x_out + i*OUT32_STRIDE，值 = 整数 × 2^-frac，frac 由返回值 [23:16] 给出
//         （int16 版 Q5.12 → 12，int8 版 Q3.4 → 4）；带 DUMP 时每层一组，第 l 层（相对 layer_lo）像素 i 在 OUT32_OFFSET(l, n_patch, i)
#define TT_ENGINE_CLASS_BYTES  4
#define TT_ENGINE_LOGIT_STRIDE 128
#define TT_ENGINE_LOGIT_FRAC   16
// OUT=3, FULL, all 12 layers only; patch-major. 64-byte header (16 u32):
// magic, ABI, CLASS, ncls, layers=12, N=6, frac=24, count=432, eight zeros.
// Then 32 int32 LOGITS at byte64; 12*6*6 uint32 Q0.24 at byte192,
// layer/query/key order. Exactly the matrix consumed by ta_ctx, not features.
#define TT_ENGINE_OUT_ATTENTION 3u
#define TT_ENGINE_ATTN_MAGIC   0x34545441u
#define TT_ENGINE_ATTN_OFFSET  192u
#define TT_ENGINE_ATTN_WORDS   432u
#define TT_ENGINE_ATTN_STRIDE  1920u
// Supplied by the checked RTL counter installation, NOT by HLS C simulation.
// Accepted ap_start to ap_done, includes all PL AXI stalls; excludes PS work.
// 0 = uninstrumented/invalid, UINT32_MAX = saturated, neither a measurement.
#define TT_ENGINE_PL_HZ        200000000u
#define TT_ENGINE_CYCLES_INVALID 0xffffffffu
#define TT_ENGINE_OUT32_BYTES  63504                        // 15876 * 4
#define TT_ENGINE_OUT32_STRIDE 63552                        // 993 * 64
#define TT_ENGINE_OUT32_OFFSET(layer_rel, n_patch, i)  (((layer_rel) * (n_patch) + (i)) * TT_ENGINE_OUT32_STRIDE)

// 权重包 weights_engine.bin（每景每个权重版本一份，model/export_scene.py 生成；一次 LOAD_W 全部装入）：
//   [0, 64)        头：u32 magic 'TTE2'、u32 包版本、u32 ncls、u32 权重位宽（16 或 8）、16 B 保留 0、int8 e_head[24]（分类头逐类小数位）、8 B 0
//   [64, +63552)   EMB：int32 Q.24 × 15876，内存序 (p, n)；n = 0 为 cls_token + pos_embed，n ≥ 1 为 pos_embed
//   [63616, +128)  分类头偏置：int32 Q.16 × 24（ncls 之后为 0）
//   [63744, +127488) 分类头权重：int16 × 24 行，行 c 在 63744 + c*5312（2646 个 + 补 0 到 64 B），值 = 整数 × 2^-e_head[c]；ncls 之后的行为 0
//   [191232, ...)  投影因子：int16 版 = weights_all.bin 原样（Q1.14，顺序 层 → 投影(q,k,v,mlp) → M1 行主序、M2、M3），289344 B；
//                  int8 版 = int8 因子 144672 B（顺序同上，逐矩阵 2 的幂缩放）+ 144 B 指数表（48 投影 × {e1,e2,e3} int8）+ 16 B 补 0
// M2 编译只用投影因子段，其余段装载时跳过。
#define TT_ENGINE_WPKG_MAGIC   0x32455454u                  // 'T' 'T' 'E' '2'（小端）
#define TT_ENGINE_WPKG_EMB     64
#define TT_ENGINE_WPKG_HBIAS   63616
#define TT_ENGINE_WPKG_HW      63744
#define TT_ENGINE_WPKG_HW_ROW  5312
#define TT_ENGINE_WPKG_PROJ    191232
#define TT_ENGINE_WPROJ16_BYTES 289344                      // 12 * 4 * 3014 * 2
#define TT_ENGINE_WPROJ8_BYTES  144832                      // 144672 + 144 + 16
#define TT_ENGINE_WPKG16_BYTES (TT_ENGINE_WPKG_PROJ + TT_ENGINE_WPROJ16_BYTES)   // 480576
#define TT_ENGINE_WPKG8_BYTES  (TT_ENGINE_WPKG_PROJ + TT_ENGINE_WPROJ8_BYTES)    // 336064
#define TT_ENGINE_W_BANKS_MAX  2                            // 片上权重库数由编译参数 TT_W_BANKS 决定（1 或 2）；库号超出编译值时报错

// ---------------------------------------------------------------- 顶层参数（= 寄存器；顺序冻结）
// u32 tt_engine(const u64 *x_in, const u64 *cube, u64 *x_out, u64 *q_out, u64 *k_out, u64 *v_out, u64 *stats_out,
//               const u64 *w_ddr, u32 cube_w, u32 seg_row, u32 seg_col, u32 n_patch,
//               u32 layer_lo, u32 layer_hi, u32 proj_mask, u32 mode, u32 *cycles)
//   x_in      输入块基址（PROJ：未归一化的 x；FULL 非 CUBE：embed 后的 x_embed）；CUBE 模式不用
//   cube      立方体基址（FULL + CUBE）；立方体装入 DDR 后 clean 一次，之后只读
//   x_out     FULL 模式输出区基址，内容由 OUT 字段决定（见上）；PROJ 模式不用
//   q_out/k_out/v_out/stats_out   PROJ 模式输出基址（按 patch 跨距）；proj_mask 只含 MLP 时输出写 q_out（沿用 v1.4 n_proj=1 的约定）；FULL 模式不用
//   w_ddr     权重包基址；只在 mode 含 LOAD_W 时读
//   cube_w    填充后立方体宽度（像素，= W + 6）
//   seg_row, seg_col   CUBE 模式：本段第一个像素的坐标（未填充坐标 = 填充立方体里 7×7 窗左上角）；本段是同一行的 n_patch 个连续像素
//   n_patch   patch / 像素数 1..NPATCH_MAX；= 0 时只做权重装载（配 LOAD_W），不算
//   layer_lo, layer_hi   FULL：执行层区间 [lo, hi]，0 ≤ lo ≤ hi ≤ 11（单层调试：lo = hi；分类头只在 hi = 11 时执行）；PROJ：层号 = layer_lo
//   proj_mask PROJ 模式要算的投影（TT_ENGINE_PROJ_*），FULL 模式忽略
//   mode      模式位，见下
//   cycles    输出：本次调用从 ap_start 到 ap_done 的 PL 时钟拍数（32 位，200 MHz 下可计 21 s；整景要分段调用）
//   返回值    [7:0] 错误码（TT_ENGINE_ERR_*）；[15:8] = TT_ENGINE_VERSION；[23:16] = FEAT 输出小数位（int16 版 12，int8 版 4）；
//             [31:24] = 片上激活位宽（18 或 8）。int16 / int8 两版 PS 代码相同

// mode 位
#define TT_ENGINE_MODE_FULL    (1u << 0)   // 1 = 整网模式（M3）；0 = 投影模式（M2 / 逐层调试）
#define TT_ENGINE_MODE_LOAD_W  (1u << 1)   // 先从 w_ddr 装载权重包到片上库 LOAD_BANK 再算（或只装载，n_patch = 0）
#define TT_ENGINE_MODE_LOAD_BANK (1u << 2) // 装载到哪个库（0/1）
#define TT_ENGINE_MODE_USE_BANK  (1u << 3) // 本次计算用哪个库（0/1）；双库编译下可与 LOAD_BANK 不同，实现"后台装载 + 批边界切换"
#define TT_ENGINE_MODE_DUMP    (1u << 4)   // FULL：每层的块都写 DDR（逐层对拍用），要求 OUT = FEAT
#define TT_ENGINE_MODE_CUBE    (1u << 5)   // FULL：输入取自立方体（片上取窗 + patch 归一化 + embed，M3b）；0 = 取自 x_in 块（M3a / 调试）
#define TT_ENGINE_MODE_OUT_SHIFT 6         // [7:6] 输出选择
#define TT_ENGINE_MODE_OUT_MASK  (3u << 6)
#define TT_ENGINE_OUT_CLASS    0u          // 类别 + 置信度（整景巡检、区域识别、评测）
#define TT_ENGINE_OUT_LOGITS   1u          // 全部 logits（单点探查）
#define TT_ENGINE_OUT_FEAT     2u          // 终块 / 逐层块（调试）
#define TT_ENGINE_MODE_OUT(o)  ((o) << TT_ENGINE_MODE_OUT_SHIFT)

// proj_mask 位（PROJ 模式）
#define TT_ENGINE_PROJ_Q       (1u << 0)
#define TT_ENGINE_PROJ_K       (1u << 1)
#define TT_ENGINE_PROJ_V       (1u << 2)
#define TT_ENGINE_PROJ_MLP     (1u << 3)
#define TT_ENGINE_PROJ_QKV     (TT_ENGINE_PROJ_Q | TT_ENGINE_PROJ_K | TT_ENGINE_PROJ_V)

// 错误码（返回值低 8 位）
#define TT_ENGINE_ERR_OK       0
#define TT_ENGINE_ERR_NPATCH   1    // n_patch > NPATCH_MAX，或 n_patch = 0 且没有 LOAD_W
#define TT_ENGINE_ERR_LAYER    2    // layer 区间非法
#define TT_ENGINE_ERR_PROJ     3    // PROJ 模式 proj_mask = 0，或 MLP 与 Q/K/V 混选
#define TT_ENGINE_ERR_BANK     4    // 库号超出编译的 TT_W_BANKS
#define TT_ENGINE_ERR_NOWEIGHT 5    // 所选库从未装载过
#define TT_ENGINE_ERR_MODE     6    // 编译未包含的模式（例如 M2 编译下请求 FULL），OUT = 3，或 DUMP 未配 FEAT，或 CLASS/LOGITS 而 layer_hi ≠ 11
#define TT_ENGINE_ERR_CUBE     7    // CUBE 模式段越界：seg_col + n_patch > cube_w − 6
#define TT_ENGINE_ERR_WPKG     8    // 权重包头 magic / 位宽与编译不符，或 ncls 为 0 或 > NCLS_MAX

// 返回值位域
#define TT_ENGINE_RET_ERR(r)     ((r) & 0xFFu)
#define TT_ENGINE_RET_VERSION(r) (((r) >> 8) & 0xFFu)
#define TT_ENGINE_RET_FRAC(r)    (((r) >> 16) & 0xFFu)   // FEAT 输出小数位
#define TT_ENGINE_RET_BITS(r)    (((r) >> 24) & 0xFFu)   // 片上激活位宽：18（int16 版）或 8（int8 版）

// ---------------------------------------------------------------- PS 侧约定（细节 docs/engine_arch.md §5.3）
// 启动前：立方体与权重包各在装入 DDR 后 clean（dc cvac）一次；x_in 各块每次 clean；输出区若被 CPU 写过需 flush。
// 完成后：读输出前 invalidate（x_out / q_out / k_out / v_out / stats_out 的实际使用范围）。
// 同一时刻只允许一个调用在飞。整景巡检：每行一次调用（CUBE + CLASS），PS 处理上一行结果时 PL 算下一行。
// 分类头在 PL（v2 起）：CLASS 输出直接是类别与置信度；LOGITS 供单点探查。PS 不再做 embed 与分类头（M3a 仍由 PS embed）。

#endif
