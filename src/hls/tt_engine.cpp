// tt_engine —— 整网引擎（docs/engine_arch.md）。两种编译（tt_engine.h 的 TT_DB）：
//   M2（TT_DB = 16）：PROJ 模式，Q3.12，与 v1.4 逐位相同；
//   M3a（TT_DB = 18）：FULL 模式块输入（12 层 + 分类头，CLASS / LOGITS / FEAT、DUMP），数值对 model/engine_ref.py 入口 A 逐位；
//                      PROJ 保留为逐层调试口（输出饱和到 int16）。D4a 第一版：每个 patch 串行走完各单元，不做单元间重叠与 P 轮转。
//
// M2 一次调用 = n_patch 个 patch × proj_mask 选中的投影（同一层 layer_lo）。每个 patch：
//   装载 x_in 块（顺带累计 S1/Sxx）→ token 统计量写 stats_out → 片上归一化 → 各投影 mode1 → mode2 → mode3 → 写 q/k/v_out
// 数值与 v1.4（src/hls/tucker_proj.cpp，TT_NORM_IN）及 src/ps/tt_ref_int.h 逐位相同：舍入位置、归一化算法都不变。
// 与 v1.4 的区别：48 个投影的因子一次装载后驻留片上（LOAD_W），mode3 一拍 TT_K3 个位置，批处理 n_patch 个 patch。
// M3a 的块（X、XN、Q、K/V）用 tt_attn.h 的布局 blk[t][h][i]，投影核仍用下面的 xb / ob，两者之间由归一化趟与 copy_ob 转换。
//
// 片上缓冲按"一拍要同时访问的元素落在不同 bank"显式分维（不靠 HLS 证明地址奇偶）：
//   xb[n][i1][r % KA][r / KA]          块：mode1 一拍读同一 token 的 7 个 i1 × KA 个 r
//   t1[a][i2][j % KA][j / KA]          mode1 → mode2
//   t2[a % KA][a / KA][b][j % KA][j / KA]   mode2 → mode3：mode3 一拍读 KA 个 a 行 × 7 个 b
//   ob[n][a & 1][b][(a >> 1) * 54 + c] 投影输出：mode3 倒出一拍写 KA × 7 个 (a, b)，store 一拍读同一 p 的 token。
//                                      存 BRAM；KA = 1 时一拍只写一个 a，a & 1 并进深度（42 个 432 深的 bank，各一块 BRAM18）
// 元素 (p, n) 在 DDR 块里的线性下标 p*6 + n；p = i1*378 + r = (a*7 + b)*54 + c。
// 一个 p 对 (2k, 2k+1) 正好是 12 个元素 = 3 个 64 位字，所以装载 / 写回按 p 对循环，每个 token 的 bank 号是编译期常量。
#include "tt_engine.h"
#if TT_M3
#include "tt_attn.h"
#endif
#include <hls_math.h>
#include <math.h>

#ifdef __SYNTHESIS__
static inline float tt_sqrtf(float v) { return hls::sqrt(v); }
#else
static inline float tt_sqrtf(float v) { return sqrtf(v); }
#endif

typedef ap_int<TT_DB + 12>      s1_t;    // Σx：|x| ≤ 2^(DB−1)，D = 2646 < 2^12（M2 28 位，M3 30 位 = ta_s1_t）
typedef ap_uint<2 * TT_DB + 10> sxx_t;   // Σx²（M2 42 位，M3 46 位 = ta_sxx_t）
typedef ap_int<2 * TT_DB + 24>  var_t;   // D·Sxx − S1²
typedef ap_int<32>  q24_t;     // mean_q24、inv_q24

#define TT_RW (TT_R / TT_KA)   // xb 每 bank 深度
#define TT_JW (TT_J / TT_KA)   // t1/t2 的 j 深度
#define TT_OBW (4 * TT_J)      // ob 每 bank 深度：a >> 1 ∈ 0..3

typedef act_t  xb_t[TT_N][TT_W][TT_KA][TT_RW];
typedef mid_t  t1_t[TT_W][TT_W][TT_KA][TT_JW];
typedef mid_t  t2_t[TT_KA][TT_G][TT_W][TT_KA][TT_JW];
typedef act_t  ob_t[TT_N][2][TT_W][TT_OBW];

// DDR 的 int16 → 片上激活（符号扩展）
static inline act_t raw16(const u64 &w, int lane) {
#pragma HLS INLINE
    ap_int<16> t;
    t.range(15, 0) = w.range(16 * lane + 15, 16 * lane);
    act_t v;
    v.range(TT_DB - 1, 0) = ((ap_int<TT_DB>)t).range(TT_DB - 1, 0);
    return v;
}

// 原始整数饱和到 TT_DB 位
template <int B> static inline act_t sat_db(ap_int<B> r) {
#pragma HLS INLINE
    ap_int<TT_DB> q;
    if (r > (1 << (TT_DB - 1)) - 1) q = (1 << (TT_DB - 1)) - 1;
    else if (r < -(1 << (TT_DB - 1))) q = -(1 << (TT_DB - 1));
    else q = (ap_int<TT_DB>)r;
    act_t out;
    out.range(TT_DB - 1, 0) = q.range(TT_DB - 1, 0);
    return out;
}

// 片上激活 → DDR int16（PROJ 输出；M3 编译下 Q5.12 饱和到 int16）
static inline ap_uint<16> out16(act_t v) {
#pragma HLS INLINE
    ap_int<TT_DB> x;
    x.range(TT_DB - 1, 0) = v.range(TT_DB - 1, 0);
    ap_int<16> q;
    if (x > 32767) q = 32767;
    else if (x < -32768) q = -32768;
    else q = (ap_int<16>)x;
    return q.range(15, 0);
}

// ---------------------------------------------------------------- 装载 + 统计量（M2：直接写 xb，原地归一化）
#if !TT_M3
static void load_stats(const u64 *x_in, unsigned int off, xb_t xb, s1_t s1[TT_N], sxx_t sxx[TT_N]) {
    s1_t a1[TT_N];
    sxx_t a2[TT_N];
#pragma HLS ARRAY_PARTITION variable=a1 complete
#pragma HLS ARRAY_PARTITION variable=a2 complete
    for (int n = 0; n < TT_N; n++) { a1[n] = 0; a2[n] = 0; }
    unsigned int e = off;
    unsigned short i1 = 0, r = 0;                         // p = 2k = i1*378 + r，r 为偶数
    for (unsigned short k = 0; k < TT_D / 2; k++) {
#pragma HLS PIPELINE II=3
#pragma HLS DEPENDENCE variable=xb inter false
        const u64 w0 = x_in[e], w1 = x_in[e + 1], w2 = x_in[e + 2];
        e += 3;
        act_t v[2 * TT_N];
#pragma HLS ARRAY_PARTITION variable=v complete
        for (int l = 0; l < 4; l++) { v[l] = raw16(w0, l); v[4 + l] = raw16(w1, l); v[8 + l] = raw16(w2, l); }
        for (int n = 0; n < TT_N; n++) {
            xb[n][i1][r % TT_KA][r / TT_KA] = v[n];
            xb[n][i1][(r + 1) % TT_KA][(r + 1) / TT_KA] = v[TT_N + n];
            ap_int<16> x0, x1;
            x0.range(15, 0) = v[n].range(15, 0);
            x1.range(15, 0) = v[TT_N + n].range(15, 0);
            const ap_int<32> q0 = x0 * x0, q1 = x1 * x1;
            a1[n] = a1[n] + x0 + x1;
            a2[n] = a2[n] + (ap_uint<31>)q0 + (ap_uint<31>)q1;
        }
        if (r == TT_R - 2) { r = 0; i1++; } else r += 2;
    }
    for (int n = 0; n < TT_N; n++) { s1[n] = a1[n]; sxx[n] = a2[n]; }
}
#endif

// mean_q24 = (S1<<12)/D（向零截断）；inv = C / sqrtf((float)var_num)，clamp ≤ 127；inv_q24 = trunc(inv·2^24)；wr 时写 stats_out（PROJ）
static void token_stats(const s1_t s1[TT_N], const sxx_t sxx[TT_N], q24_t mean[TT_N], q24_t inv[TT_N],
                        u64 *stats_out, unsigned int st_off, bool wr) {
    for (int t = 0; t < TT_N; t++) {
#pragma HLS PIPELINE off
        const var_t var_num = (var_t)((ap_uint<2 * TT_DB + 22>)sxx[t] * (ap_uint<12>)TT_D) - (var_t)(s1[t] * s1[t]);
        const ap_int<TT_DB + 24> s1_12 = ((ap_int<TT_DB + 24>)s1[t]) << TT_DF;
        const ap_int<TT_DB + 24> m = s1_12 / (ap_int<13>)TT_D;
        const float vf = (float)(long long)var_num;
        float iv = 10835968.0f / tt_sqrtf(vf);
        if (!(iv <= 127.0f)) iv = 127.0f;
        mean[t] = (q24_t)m;
        inv[t] = (q24_t)(int)(iv * 16777216.0f);
        u64 word;
        word.range(31, 0) = ((ap_uint<32>)mean[t]).range(31, 0);
        word.range(63, 32) = ((ap_uint<32>)inv[t]).range(31, 0);
        if (wr) stats_out[st_off + t] = word;
    }
}

// q = sat_DB((((x<<12) − mean)·inv_q24 + 2^35) >> 36)
static inline act_t norm_one(act_t x, q24_t mean, q24_t inv) {
#pragma HLS INLINE
    ap_int<TT_DB> xi;
    xi.range(TT_DB - 1, 0) = x.range(TT_DB - 1, 0);
    const ap_int<TT_DB + 13> d = (((ap_int<TT_DB + 13>)xi) << TT_DF) - (ap_int<TT_DB + 13>)mean;
    const ap_int<TT_DB + 45> prod = d * inv;
    const ap_int<TT_DB + 46> r = (prod + (ap_int<TT_DB + 46>)(1LL << 35)) >> 36;
    return sat_db<TT_DB + 46>(r);
}

#if !TT_M3
// 原地归一化：一拍 6 个元素（同一 (i1, r) 的 6 个 token，各在自己的 bank）
static void normalize(xb_t xb, const q24_t mean[TT_N], const q24_t inv[TT_N]) {
    for (unsigned short i1 = 0; i1 < TT_W; i1++)
        for (unsigned short r = 0; r < TT_R; r++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=xb inter false
            for (int n = 0; n < TT_N; n++)
                xb[n][i1][r % TT_KA][r / TT_KA] = norm_one(xb[n][i1][r % TT_KA][r / TT_KA], mean[n], inv[n]);
        }
}
#endif

// ---------------------------------------------------------------- 三个模积（token 级）
// 模 1：t1[a][i2][j] = Σ_i1 M1[a][i1] · X[i1][i2][j]，一拍 KA 个 r（49·KA MAC）
static void mode1(xb_t xb, unsigned short n, const wt_t m1[TT_W][TT_W], t1_t t1) {
    unsigned short i2 = 0, jw = 0;
    for (unsigned short s = 0; s < TT_RW; s++) {
#pragma HLS PIPELINE II=1
        for (int kk = 0; kk < TT_KA; kk++) {
            act_t x[TT_W];
#pragma HLS ARRAY_PARTITION variable=x complete
            for (int i1 = 0; i1 < TT_W; i1++) x[i1] = xb[n][i1][kk][s];
            for (int a = 0; a < TT_W; a++) {
                acc_t acc = 0;
                for (int i1 = 0; i1 < TT_W; i1++) acc += x[i1] * m1[a][i1];
                t1[a][i2][kk][jw] = (mid_t)acc;
            }
        }
        if (jw == TT_JW - 1) { jw = 0; i2++; } else jw++;
    }
}

// 模 2：t2[a][b][j] = Σ_i2 M2[b][i2] · t1[a][i2][j]，一拍 KA 个 j
static void mode2(t1_t t1, const wt_t m2[TT_W][TT_W], t2_t t2) {
    for (unsigned short a = 0; a < TT_W; a++)
        for (unsigned short jw = 0; jw < TT_JW; jw++) {
#pragma HLS PIPELINE II=1
            for (int kk = 0; kk < TT_KA; kk++) {
                mid_t x[TT_W];
#pragma HLS ARRAY_PARTITION variable=x complete
                for (int i2 = 0; i2 < TT_W; i2++) x[i2] = t1[a][i2][kk][jw];
                for (int b = 0; b < TT_W; b++) {
                    acc_t acc = 0;
                    for (int i2 = 0; i2 < TT_W; i2++) acc += x[i2] * m2[b][i2];
                    t2[a % TT_KA][a / TT_KA][b][kk][jw] = (mid_t)acc;
                }
            }
        }
}

// 模 3：y[a][b][c] = Σ_j M3[c][j] · t2[a][b][j]。一组 = KA 个 a 行 × 7 个 b = TT_K3 个位置，54 拍累加（不舍入不饱和，
// 所以与累加顺序无关）；组末结果进 pend，在下一组的 54 拍里按 c = j 倒出（一拍 KA×7 个，各在自己的 bank）。
// 累加器用原始整数（acc_t 的 28 位小数），j = 0 时清零；组末 pend 只存 acc >> 15，
// 倒出时 (v + 1) >> 1 再饱和到 TT_DB 位，等于 AP_RND 舍到 12 位小数 + AP_SAT（floor((⌊y⌋ + 1) / 2) = floor((y + 1) / 2)）。
// 舍入与饱和只在倒出时做——每拍 KA×7 个，而不是组末 378 个同时做。
// 累加器 39 位：|x| ≤ 2^17、|w| ≤ 2^15，54 项之和 < 54·2^32 < 2^38，精确。清零选择器与 HLS 的旁路选择器在 fabric 里，
// 每位一个 LUT（Vivado 网表：DSP 的 Z 选 C，C 口 48 位来自 LUT5），所以位宽直接决定这部分 LUT。
#define TT_M3_SH (48 - 20 - TT_DF)             // acc_t 小数位 28 − data_t 小数位 12
#define TT_M3_ACCW 39
typedef ap_int<TT_M3_ACCW> accr_t;
typedef ap_int<TT_M3_ACCW - TT_M3_SH + 1> pend_t;   // acc >> 15

static inline act_t sat_pend(pend_t v) {
#pragma HLS INLINE
    const pend_t r = (v + 1) >> 1;
    return sat_db<TT_M3_ACCW - TT_M3_SH + 1>(r);
}

static void mode3(t2_t t2, const ap_uint<64> wm3[TT_M3G][TT_NPROJ * TT_J], unsigned short pbase, unsigned short n, ob_t ob) {
    accr_t acc[TT_KA][TT_W][TT_J];
    pend_t pend[TT_KA][TT_W][TT_J];
#pragma HLS ARRAY_PARTITION variable=acc complete dim=0
#pragma HLS ARRAY_PARTITION variable=pend complete dim=0
    bool have = false, podd = false;                      // pend 有效；上一组 a0 的奇偶（KA = 1 时用）
    unsigned short pobase = 0, obase = 0;                 // 上一组 / 本组的 (a0 >> 1) * 54
    for (unsigned short g = 0; g < TT_G; g++)
        for (unsigned short j = 0; j < TT_J; j++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=ob inter false
            ap_int<16> w[TT_J];
#pragma HLS ARRAY_PARTITION variable=w complete
            for (int c = 0; c < TT_J; c++) w[c].range(15, 0) = wm3[c >> 2][pbase + j].range(16 * (c & 3) + 15, 16 * (c & 3));
            for (int ka = 0; ka < TT_KA; ka++)
                for (int b = 0; b < TT_W; b++) {
                    const bool valid = g * TT_KA + ka < TT_W;
                    ap_int<18> x = 0;
                    if (valid) x.range(17, 0) = t2[ka][g][b][j % TT_KA][j / TT_KA].range(17, 0);
                    for (int c = 0; c < TT_J; c++) {
                        const accr_t base = (j == 0) ? accr_t(0) : acc[ka][b][c];
                        acc[ka][b][c] = base + x * w[c];
                    }
                }
            if (have)
                for (int ka = 0; ka < TT_KA; ka++) {
                    const bool par = TT_KA == 2 ? (ka == 1) : podd;
                    const bool valid = TT_KA == 1 || ka == 0 || pobase < 3 * TT_J;   // KA = 2 的末组只有 a = 6
                    if (valid)
                        for (int b = 0; b < TT_W; b++) ob[n][par][b][pobase + j] = sat_pend(pend[ka][b][j]);
                }
            if (j == TT_J - 1) {
                for (int ka = 0; ka < TT_KA; ka++)
                    for (int b = 0; b < TT_W; b++)
                        for (int c = 0; c < TT_J; c++) pend[ka][b][c] = (pend_t)(acc[ka][b][c] >> (TT_M3_SH - 1));
                have = true;
                podd = (g & 1) != 0;
                pobase = obase;
                if (TT_KA == 2 || (g & 1)) obase += TT_J;
            }
        }
    for (unsigned short j = 0; j < TT_J; j++) {           // 最后一组
#pragma HLS PIPELINE II=1
        for (int ka = 0; ka < TT_KA; ka++) {
            const bool par = TT_KA == 2 ? (ka == 1) : podd;
            const bool valid = TT_KA == 1 || ka == 0 || pobase < 3 * TT_J;
            if (valid)
                for (int b = 0; b < TT_W; b++) ob[n][par][b][pobase + j] = sat_pend(pend[ka][b][j]);
        }
    }
}

// token 级流水：token n 的 mode3 与 token n+1 的 mode1/mode2 重叠；t1、t2 在 DATAFLOW 区内声明，HLS 做成 ping-pong。
// m1/m2/wm3/xb 在一次投影内不变（STABLE），不随 token 走通道
static void token_pipeline(xb_t xb, const wt_t m1[TT_W][TT_W], const wt_t m2[TT_W][TT_W],
                           const ap_uint<64> wm3[TT_M3G][TT_NPROJ * TT_J], unsigned short pbase, ob_t ob) {
#pragma HLS STABLE variable=m1
#pragma HLS STABLE variable=m2
#pragma HLS STABLE variable=wm3
#pragma HLS STABLE variable=xb
    for (unsigned short n = 0; n < TT_N; n++) {
#pragma HLS DATAFLOW
        t1_t t1;
        t2_t t2;
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=1
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=2
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=3
#pragma HLS BIND_STORAGE variable=t1 type=ram_2p impl=lutram
#pragma HLS ARRAY_PARTITION variable=t2 complete dim=1
#pragma HLS ARRAY_PARTITION variable=t2 complete dim=3
#pragma HLS ARRAY_PARTITION variable=t2 complete dim=4
        mode1(xb, n, m1, t1);
        mode2(t1, m2, t2);
        mode3(t2, wm3, pbase, n, ob);
    }
}

static void one_projection(xb_t xb, const wt_t wm12[2 * TT_W * TT_W][TT_NPROJ],
                           const ap_uint<64> wm3[TT_M3G][TT_NPROJ * TT_J], unsigned short proj, unsigned short pbase, ob_t ob) {
#if TT_M3_OVERLAP
#pragma HLS INLINE off
#endif
    wt_t m1[TT_W][TT_W], m2[TT_W][TT_W];
#pragma HLS ARRAY_PARTITION variable=m1 complete dim=0
#pragma HLS ARRAY_PARTITION variable=m2 complete dim=0
    for (int a = 0; a < TT_W; a++)
        for (int i = 0; i < TT_W; i++) {
#pragma HLS UNROLL
            m1[a][i] = wm12[a * TT_W + i][proj];
            m2[a][i] = wm12[TT_W * TT_W + a * TT_W + i][proj];
        }
    token_pipeline(xb, m1, m2, wm3, pbase, ob);
}

// ---------------------------------------------------------------- 片上 ob → DDR（按 p 对，3 个字）
static void store_block(ob_t ob, u64 *out, unsigned int off) {
    unsigned int e = off;
    unsigned short a = 0, b = 0, c = 0, abase = 0;        // p = 2k = (a*7 + b)*54 + c，c 为偶数；abase = (a >> 1) * 54
    for (unsigned short k = 0; k < TT_D / 2; k++) {
#pragma HLS PIPELINE II=3
        const bool par = a & 1;
        act_t v[2 * TT_N];
#pragma HLS ARRAY_PARTITION variable=v complete
        for (int n = 0; n < TT_N; n++) {
            v[n] = ob[n][par][b][abase + c];
            v[TT_N + n] = ob[n][par][b][abase + c + 1];
        }
        u64 w0, w1, w2;
        for (int l = 0; l < 4; l++) {
            w0.range(16 * l + 15, 16 * l) = out16(v[l]);
            w1.range(16 * l + 15, 16 * l) = out16(v[4 + l]);
            w2.range(16 * l + 15, 16 * l) = out16(v[8 + l]);
        }
        out[e] = w0; out[e + 1] = w1; out[e + 2] = w2;
        e += 3;
        if (c == TT_J - 2) {
            c = 0;
            if (b == TT_W - 1) { b = 0; if (a & 1) abase += TT_J; a++; } else b++;
        } else c += 2;
    }
}

// ---------------------------------------------------------------- 权重包投影段装载（每景一次）
// M3 驻留在 14 个 URAM 字阵列里：wm3p[g][proj*54 + j] 的 16 位车道 q 是 M3[4g + q][j]（g = 13 只有 c = 52、53）。
// DDR 里 M3 按 c 行主序，一个字的 4 个 c 相距 54 个元素，所以每个投影先原样搬进暂存 tmp，再转置写 URAM：
//   tmp 按全局元素号 e 的低 3 位分 8 个 bank：搬运时一拍 2 个 64 位字 = 8 个元素，bank 号是常量；
//   转置时一拍读 e0 + 54q（q = 0..3），54q mod 8 = 0/6/4/2 两两不同，4 个读落在不同 bank。
// 每投影 ≈ 380×2 + 98 + 756 拍，48 个投影约 78k 拍（0.39 ms @200 MHz）。
#define TT_TMP_DEPTH 380
static void load_weights(const u64 *w_ddr, wt_t wm12[2 * TT_W * TT_W][TT_NPROJ], ap_uint<64> wm3p[TT_M3G][TT_NPROJ * TT_J]) {
    wt_t tmp[8][TT_TMP_DEPTH];
#pragma HLS ARRAY_PARTITION variable=tmp complete dim=1
    unsigned int start = 0;                               // 本投影第一个元素的全局元素号
    unsigned short pbase = 0;
    for (unsigned short proj = 0; proj < TT_NPROJ; proj++) {
        const unsigned int c0 = start >> 3, c1 = (start + TT_NF - 1) >> 3;
        for (unsigned int i = c0; i <= c1; i++) {
#pragma HLS PIPELINE II=2
#pragma HLS LOOP_TRIPCOUNT min=377 max=378
            const u64 w0 = w_ddr[TT_WPROJ_W0 + 2 * i], w1 = w_ddr[TT_WPROJ_W0 + 2 * i + 1];
            for (int l = 0; l < 4; l++) {
                tmp[l][i - c0].range(15, 0) = w0.range(16 * l + 15, 16 * l);
                tmp[4 + l][i - c0].range(15, 0) = w1.range(16 * l + 15, 16 * l);
            }
        }
        unsigned int e = start;
        for (unsigned short off = 0; off < 2 * TT_W * TT_W; off++) {
#pragma HLS PIPELINE II=1
            wm12[off][proj] = tmp[e & 7][(e >> 3) - c0];
            e++;
        }
        for (unsigned short j = 0; j < TT_J; j++) {
            unsigned int eg = start + 2 * TT_W * TT_W + j;     // = 元素 M3[4g][j]
            for (unsigned short g = 0; g < TT_M3G; g++) {
#pragma HLS PIPELINE II=1
                ap_uint<64> word = 0;
                for (int q = 0; q < 4; q++) {
                    const unsigned int eq = eg + q * TT_J;
                    wt_t v = tmp[eq & 7][(eq >> 3) - c0];
                    if (4 * g + q >= TT_J) v = 0;
                    word.range(16 * q + 15, 16 * q) = v.range(15, 0);
                }
                wm3p[g][pbase + j] = word;
                eg += 4 * TT_J;
            }
        }
        start += TT_NF;
        pbase += TT_J;
    }
}

#if TT_M3
// ---------------------------------------------------------------- M3a：块（tt_attn.h 的布局 blk[t·TA_H + h][i]）上的单元
static inline ta_act_t to_ta(act_t v) {
#pragma HLS INLINE
    ta_act_t t;
    t.range(17, 0) = v.range(17, 0);
    return t;
}

// 分类头段（每景一次，随 LOAD_W）：eh 在头的字节 32..55，偏置 24 个 int32，权重 24 行 × 664 字（行 c 的字 k 是 p = 4k..4k+3）。
// wh[g][p] 的 lane q = 行 4g + q 的 W[p]：一次读 4 行的同一个字，攒 4 个 p 的 wh 字，II = 4，6 × 662 × 4 ≈ 15.9k 拍
#define TT_HW_W0   (TT_ENGINE_WPKG_HW / 8)
#define TT_HW_ROWW (TT_ENGINE_WPKG_HW_ROW / 8)
#define TT_HW_WK   ((TT_D + 3) / 4)
static void load_head(const u64 *w_ddr, ap_uint<64> wh[TA_HW][TT_D], ap_int<8> eh[TA_NCLS], ap_int<32> hb[TA_NCLS]) {
    for (int c = 0; c < TA_NCLS; c++) {
#pragma HLS PIPELINE II=2
        const u64 we = w_ddr[4 + (c >> 3)], wb = w_ddr[TT_ENGINE_WPKG_HBIAS / 8 + (c >> 1)];
        eh[c].range(7, 0) = we.range(8 * (c & 7) + 7, 8 * (c & 7));
        hb[c].range(31, 0) = wb.range(32 * (c & 1) + 31, 32 * (c & 1));
    }
    unsigned int rb = TT_HW_W0;                           // 行 4g 的首字
    for (unsigned short g = 0; g < TA_HW; g++) {
        for (unsigned short k = 0; k < TT_HW_WK; k++) {
#pragma HLS PIPELINE II=4
            u64 r[4];
#pragma HLS ARRAY_PARTITION variable=r complete
            for (int q = 0; q < 4; q++) r[q] = w_ddr[rb + q * TT_HW_ROWW + k];
            for (int j = 0; j < 4; j++) {
                const unsigned short p = 4 * k + j;
                ap_uint<64> word;
                for (int q = 0; q < 4; q++) word.range(16 * q + 15, 16 * q) = r[q].range(16 * j + 15, 16 * j);
                if (p < TT_D) wh[g][p] = word;
            }
        }
        rb += 4 * TT_HW_ROWW;
    }
}

// x_in（int16，内存序）→ 块 X，顺带累计 S1/Sxx。一个 p 对 = 12 个元素 = 3 个字，II = 3
static void load_x(const u64 *x_in, unsigned int off, ta_blk_t x, s1_t s1[TT_N], sxx_t sxx[TT_N]) {
    s1_t a1[TT_N];
    sxx_t a2[TT_N];
#pragma HLS ARRAY_PARTITION variable=a1 complete
#pragma HLS ARRAY_PARTITION variable=a2 complete
    for (int n = 0; n < TT_N; n++) { a1[n] = 0; a2[n] = 0; }
    unsigned int e = off;
    unsigned short hp = 0, i = 0;                         // p = 2k：lane 2·hp、2·hp + 1，字 i
    for (unsigned short k = 0; k < TT_D / 2; k++) {
#pragma HLS PIPELINE II=3
#pragma HLS DEPENDENCE variable=x inter false
        const u64 w0 = x_in[e], w1 = x_in[e + 1], w2 = x_in[e + 2];
        e += 3;
        ap_int<16> v[2 * TT_N];
#pragma HLS ARRAY_PARTITION variable=v complete
        for (int l = 0; l < 4; l++) {
            v[l].range(15, 0) = w0.range(16 * l + 15, 16 * l);
            v[4 + l].range(15, 0) = w1.range(16 * l + 15, 16 * l);
            v[8 + l].range(15, 0) = w2.range(16 * l + 15, 16 * l);
        }
        for (int n = 0; n < TT_N; n++) {
            const ap_int<16> x0 = v[n], x1 = v[TT_N + n];
            x[n][2 * hp][i] = x0;
            x[n][2 * hp + 1][i] = x1;
            a1[n] = a1[n] + x0 + x1;
            a2[n] = a2[n] + (ap_uint<31>)(ap_int<32>)(x0 * x0) + (ap_uint<31>)(ap_int<32>)(x1 * x1);
        }
        if (hp == TA_H / 2 - 1) { hp = 0; i++; } else hp++;
    }
    for (int n = 0; n < TT_N; n++) { s1[n] = a1[n]; sxx[n] = a2[n]; }
}

// 归一化趟：X → xb（投影核 mode1 的布局）+ XN（CTX / RES2 用），一拍一个 p 的 6 个 token
static void norm_full(const ta_blk_t x, const q24_t mean[TT_N], const q24_t inv[TT_N], xb_t xb, ta_blk_t xn) {
    unsigned short i1 = 0, r = 0, h = 0, i = 0;          // p = i1·378 + r = TA_H·i + h
    for (unsigned short p = 0; p < TT_D; p++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=xb inter false
#pragma HLS DEPENDENCE variable=xn inter false
        for (int n = 0; n < TT_N; n++) {
            act_t v;
            v.range(17, 0) = x[n][h][i].range(17, 0);
            const act_t q = norm_one(v, mean[n], inv[n]);
            xb[n][i1][r % TT_KA][r / TT_KA] = q;
            xn[n][h][i] = to_ta(q);
        }
        if (h == TA_H - 1) { h = 0; i++; } else h++;
        if (r == TT_R - 1) { r = 0; i1++; } else r++;
    }
}

// ob（mode3 倒出布局）→ 块，一拍一个 p 的 6 个 token；p = (a·7 + b)·54 + c，计数器同 store_block
static void copy_ob(ob_t ob, ta_blk_t blk) {
    unsigned short a = 0, b = 0, c = 0, abase = 0, h = 0, i = 0;
    for (unsigned short p = 0; p < TT_D; p++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=blk inter false
        const bool par = a & 1;
        for (int n = 0; n < TT_N; n++) blk[n][h][i] = to_ta(ob[n][par][b][abase + c]);
        if (h == TA_H - 1) { h = 0; i++; } else h++;
        if (c == TT_J - 1) {
            c = 0;
            if (b == TT_W - 1) { b = 0; if (a & 1) abase += TT_J; a++; } else b++;
        } else c++;
    }
}

// RES2：x'' = sat18(xn2_q + m)，写 X，顺带累计 S1/Sxx（下一层归一化用）
static void res2(ob_t ob, const ta_blk_t xn, ta_blk_t x, s1_t s1[TT_N], sxx_t sxx[TT_N]) {
    s1_t a1[TT_N];
    sxx_t a2[TT_N];
#pragma HLS ARRAY_PARTITION variable=a1 complete
#pragma HLS ARRAY_PARTITION variable=a2 complete
    for (int n = 0; n < TT_N; n++) { a1[n] = 0; a2[n] = 0; }
    unsigned short a = 0, b = 0, c = 0, abase = 0, h = 0, i = 0;
    for (unsigned short p = 0; p < TT_D; p++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=x inter false
        const bool par = a & 1;
        for (int n = 0; n < TT_N; n++) {
            const ap_int<19> s = (ap_int<19>)xn[n][h][i] + (ap_int<19>)to_ta(ob[n][par][b][abase + c]);
            const ta_act_t v = s > 131071 ? ta_act_t(131071) : (s < -131072 ? ta_act_t(-131072) : ta_act_t(s));
            x[n][h][i] = v;
            a1[n] = a1[n] + v;
            a2[n] = a2[n] + (ap_uint<35>)(ap_int<36>)(v * v);
        }
        if (h == TA_H - 1) { h = 0; i++; } else h++;
        if (c == TT_J - 1) {
            c = 0;
            if (b == TT_W - 1) { b = 0; if (a & 1) abase += TT_J; a++; } else b++;
        } else c++;
    }
    for (int n = 0; n < TT_N; n++) { s1[n] = a1[n]; sxx[n] = a2[n]; }
}

#if TT_M3_OVERLAP
// Q/K are read-only until this task joins. Always define attn to avoid a
// conditionally unproduced DATAFLOW output on the non-V jobs.
static void attention_for_v(bool enable, const ta_blk_t qb, const ta_blk_t kb,
                            ta_attn_t attn[TT_N][TT_N]) {
#pragma HLS INLINE off
    ta_s_t sc[TT_N][TT_N];
#pragma HLS ARRAY_PARTITION variable=sc complete dim=1
    if (enable) {
        ta_scores(qb, kb, sc);
        ta_softmax(sc, attn);
    } else {
        for (int n = 0; n < TT_N; ++n)
            for (int c = 0; c < TT_N; ++c) {
#pragma HLS PIPELINE II=1
                attn[n][c] = 0;
            }
    }
}

// One call site for the projection engine for ALL jobs: do not duplicate the
// expensive projection hardware. V projection and attention are independent;
// ob is copied over the old K block only AFTER both tasks have completed.
static void projection_with_attention(xb_t xb, const wt_t wm12[2 * TT_W * TT_W][TT_NPROJ],
    const ap_uint<64> wm3[TT_M3G][TT_NPROJ * TT_J], unsigned short proj,
    unsigned short pbase, ob_t ob, bool enable, const ta_blk_t qb,
    const ta_blk_t kb, ta_attn_t attn[TT_N][TT_N]) {
#pragma HLS INLINE off
#pragma HLS DATAFLOW
#pragma HLS STABLE variable=xb
#pragma HLS STABLE variable=wm12
#pragma HLS STABLE variable=wm3
#pragma HLS STABLE variable=qb
#pragma HLS STABLE variable=kb
    one_projection(xb, wm12, wm3, proj, pbase, ob);
    attention_for_v(enable, qb, kb, attn);
}
#endif

// 块 → DDR int32 内存序（FEAT / DUMP）：一个 p 的 6 个 token = 3 个字，II = 3
static void dump_x(const ta_blk_t x, u64 *out, unsigned int off) {
    unsigned int e = off;
    unsigned short h = 0, i = 0;
    for (unsigned short p = 0; p < TT_D; p++) {
#pragma HLS PIPELINE II=3
        u64 w[3];
#pragma HLS ARRAY_PARTITION variable=w complete
        for (int n = 0; n < TT_N; n++) {
            const ap_int<32> v = x[n][h][i];
            w[n >> 1].range(32 * (n & 1) + 31, 32 * (n & 1)) = v.range(31, 0);
        }
        out[e] = w[0]; out[e + 1] = w[1]; out[e + 2] = w[2];
        e += 3;
        if (h == TA_H - 1) { h = 0; i++; } else h++;
    }
}
#endif

// ---------------------------------------------------------------- 顶层
unsigned int tt_engine(const u64 *x_in, const u64 *cube, u64 *x_out, u64 *q_out, u64 *k_out, u64 *v_out, u64 *stats_out,
                       const u64 *w_ddr, unsigned int cube_w, unsigned int seg_row, unsigned int seg_col, unsigned int n_patch,
                       unsigned int layer_lo, unsigned int layer_hi, unsigned int proj_mask, unsigned int mode,
                       unsigned int *cycles) {
#pragma HLS INTERFACE m_axi port=x_in      offset=slave bundle=FM depth=11928 max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=cube      offset=slave bundle=FM depth=1     max_read_burst_length=64 max_write_burst_length=64
#if TT_M3
#pragma HLS INTERFACE m_axi port=x_out     offset=slave bundle=FM depth=95328 max_read_burst_length=64 max_write_burst_length=64
#else
#pragma HLS INTERFACE m_axi port=x_out     offset=slave bundle=FM depth=1     max_read_burst_length=64 max_write_burst_length=64
#endif
#pragma HLS INTERFACE m_axi port=q_out     offset=slave bundle=FM depth=11928 max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=k_out     offset=slave bundle=FM depth=11928 max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=v_out     offset=slave bundle=FM depth=11928 max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=stats_out offset=slave bundle=FM depth=24    max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=w_ddr     offset=slave bundle=WT depth=60072 max_read_burst_length=64
#pragma HLS INTERFACE s_axilite port=x_in      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=cube      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=x_out     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=q_out     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=k_out     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=v_out     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=stats_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=w_ddr     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=cube_w    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=seg_row   bundle=CTRL
#pragma HLS INTERFACE s_axilite port=seg_col   bundle=CTRL
#pragma HLS INTERFACE s_axilite port=n_patch   bundle=CTRL
#pragma HLS INTERFACE s_axilite port=layer_lo  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=layer_hi  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=proj_mask bundle=CTRL
#pragma HLS INTERFACE s_axilite port=mode      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=cycles    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return    bundle=CTRL

    // 驻留权重（跨调用保持）：M1/M2 每个元素一个 LUTRAM bank × 48 投影；M3 按 c 分 54 个 bank × (48 投影 × 54 个 j)
    static wt_t wm12[2 * TT_W * TT_W][TT_NPROJ];
    static ap_uint<64> wm3[TT_M3G][TT_NPROJ * TT_J];
    static bool loaded = false;
#pragma HLS ARRAY_PARTITION variable=wm12 complete dim=1
#pragma HLS BIND_STORAGE variable=wm12 type=ram_1p impl=lutram
#pragma HLS ARRAY_PARTITION variable=wm3 complete dim=1
#pragma HLS BIND_STORAGE variable=wm3 type=ram_2p impl=uram

    xb_t xb;
#pragma HLS ARRAY_PARTITION variable=xb complete dim=1
#pragma HLS ARRAY_PARTITION variable=xb complete dim=2
#pragma HLS ARRAY_PARTITION variable=xb complete dim=3
    ob_t ob;
#pragma HLS ARRAY_PARTITION variable=ob complete dim=1
#if TT_KA == 2
#pragma HLS ARRAY_PARTITION variable=ob complete dim=2
#endif
#pragma HLS ARRAY_PARTITION variable=ob complete dim=3
#pragma HLS BIND_STORAGE variable=ob type=ram_2p impl=bram

#if TT_M3
    // 分类头（驻留，随 LOAD_W）：W_HEAD 6 个字阵列（URAM），逐类小数位与偏置
    static ap_uint<64> wh[TA_HW][TT_D];
    static ap_int<8> eh[TA_NCLS];
    static ap_int<32> hb[TA_NCLS];
    static unsigned int ncls_r = 0;
#pragma HLS ARRAY_PARTITION variable=wh complete dim=1
#pragma HLS BIND_STORAGE variable=wh type=ram_1p impl=uram
#pragma HLS ARRAY_PARTITION variable=eh complete
#pragma HLS ARRAY_PARTITION variable=hb complete
    // 块：X（残差流）、XN（归一化块）、QB、KB（K 用完后装 V）
    ta_blk_t xa, xn, qb, kb;
#pragma HLS ARRAY_PARTITION variable=xa complete dim=1
#pragma HLS ARRAY_PARTITION variable=xa complete dim=2
#pragma HLS ARRAY_PARTITION variable=xn complete dim=1
#pragma HLS ARRAY_PARTITION variable=xn complete dim=2
#pragma HLS ARRAY_PARTITION variable=qb complete dim=1
#pragma HLS ARRAY_PARTITION variable=qb complete dim=2
#pragma HLS ARRAY_PARTITION variable=kb complete dim=1
#pragma HLS ARRAY_PARTITION variable=kb complete dim=2
#pragma HLS BIND_STORAGE variable=xa type=ram_2p impl=bram
#pragma HLS BIND_STORAGE variable=xn type=ram_2p impl=bram
#pragma HLS BIND_STORAGE variable=qb type=ram_2p impl=bram
#pragma HLS BIND_STORAGE variable=kb type=ram_2p impl=bram
    ta_attn_t attn[TT_N][TT_N];
    ta_logit_t lg[TA_LOGITS];
#if !TT_M3_OVERLAP
    ta_s_t sc[TT_N][TT_N];
#pragma HLS ARRAY_PARTITION variable=sc complete dim=1
#endif
#pragma HLS ARRAY_PARTITION variable=attn complete dim=1
#endif

    (void)cube; (void)cube_w; (void)seg_row; (void)seg_col;
    const unsigned int ret_hi = ((unsigned int)TT_ENGINE_VERSION << 8) | ((unsigned int)TT_DF << 16) | ((unsigned int)TT_DB << 24);
    const bool load_w = (mode & TT_ENGINE_MODE_LOAD_W) != 0;
    const bool mlp = (proj_mask & TT_ENGINE_PROJ_MLP) != 0;
    const bool full = (mode & TT_ENGINE_MODE_FULL) != 0;
    const bool dump = (mode & TT_ENGINE_MODE_DUMP) != 0;
    const unsigned int out_sel = (mode & TT_ENGINE_MODE_OUT_MASK) >> TT_ENGINE_MODE_OUT_SHIFT;
    unsigned int err = TT_ENGINE_ERR_OK;
#if TT_M3
    // M3a 编译：FULL（块输入）与 PROJ；没有前端（CUBE）
    const bool attention = full && out_sel == TT_ENGINE_OUT_ATTENTION;
    const bool bad_mode = (mode & TT_ENGINE_MODE_CUBE) || (!full && (dump || out_sel == TT_ENGINE_OUT_ATTENTION)) ||
                          (attention && (layer_lo != 0 || layer_hi != 11)) ||
                          (full && dump && out_sel != TT_ENGINE_OUT_FEAT) || (full && out_sel != TT_ENGINE_OUT_FEAT && layer_hi != TT_ENGINE_LAYERS - 1);
    const bool bad_layer = full ? (layer_lo > layer_hi || layer_hi >= TT_ENGINE_LAYERS) : layer_lo >= TT_ENGINE_LAYERS;
#else
    (void)x_out; (void)layer_hi; (void)dump;
    const bool bad_mode = full || dump || (mode & TT_ENGINE_MODE_CUBE) || out_sel == 3;   // M2 编译只有 PROJ
    const bool bad_layer = layer_lo >= TT_ENGINE_LAYERS;
#endif
    if (bad_mode)
        err = TT_ENGINE_ERR_MODE;
    else if (n_patch > TT_ENGINE_NPATCH_MAX || (n_patch == 0 && !load_w))
        err = TT_ENGINE_ERR_NPATCH;
    else if (n_patch > 0 && bad_layer)
        err = TT_ENGINE_ERR_LAYER;
    else if (n_patch > 0 && !full && (proj_mask == 0 || (proj_mask & ~0xFu) || (mlp && (proj_mask & TT_ENGINE_PROJ_QKV))))
        err = TT_ENGINE_ERR_PROJ;
    else if (mode & (TT_ENGINE_MODE_LOAD_BANK | TT_ENGINE_MODE_USE_BANK))
        err = TT_ENGINE_ERR_BANK;                          // 单库编译
    if (err == TT_ENGINE_ERR_OK && load_w) {
        const u64 h0 = w_ddr[0], h1 = w_ddr[1];
        const unsigned int magic = h0.range(31, 0), ncls = h1.range(31, 0), bits = h1.range(63, 32);
        if (magic != TT_ENGINE_WPKG_MAGIC || bits != 16 || ncls == 0 || ncls > TT_ENGINE_NCLS_MAX)
            err = TT_ENGINE_ERR_WPKG;
        else {
            load_weights(w_ddr, wm12, wm3);
#if TT_M3
            load_head(w_ddr, wh, eh, hb);
            ncls_r = ncls;
#endif
            loaded = true;
        }
    }
    if (err == TT_ENGINE_ERR_OK && n_patch > 0 && !loaded) err = TT_ENGINE_ERR_NOWEIGHT;
    // cycles：HLS C 里拿不到时钟，D2 先写 0；真实 PL 拍数由 cosim 与板上 PS 计时给出（见 sim/m2/README.md）
    *cycles = 0;
    if (err != TT_ENGINE_ERR_OK) return err | ret_hi;

#if TT_M3
    // 每个 patch：装载 → 每层两半（注意力：统计 → 归一化 → Q、K → SCORES/SOFTMAX → V → CTX+残差；MLP：统计 → 归一化 → M → RES2）
    // → 末层后分类头 / 输出。PROJ（逐层调试口）走同一套调用点：只做 layer_lo 的一半、proj_mask 选中的投影，写 q/k/v/stats（饱和到 int16）。
    // 投影核、归一化、统计各只有一个调用点，HLS 只例化一份。
    const bool feat = full && out_sel == TT_ENGINE_OUT_FEAT;
    const unsigned int l_end = full ? layer_hi : layer_lo;
    const unsigned int wpx = TT_ENGINE_OUT32_STRIDE / 8;   // FEAT 每像素 7,944 字
    const unsigned int lstride = n_patch * wpx;            // DUMP 的层跨距（DDR 偏移，每次调用算一次）
    unsigned int in_off = 0, st_off = 0, fo = 0, lo_off = 0;
    u64 cw = 0;
    for (unsigned int i = 0; i < n_patch; i++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=3
        s1_t s1[TT_N]; sxx_t sxx[TT_N]; q24_t mean[TT_N], inv[TT_N];
#pragma HLS ARRAY_PARTITION variable=s1 complete
#pragma HLS ARRAY_PARTITION variable=sxx complete
#pragma HLS ARRAY_PARTITION variable=mean complete
#pragma HLS ARRAY_PARTITION variable=inv complete
        load_x(x_in, in_off, xa, s1, sxx);
        unsigned int doff = fo;
        for (unsigned int l = layer_lo; l <= l_end; l++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=12
            for (unsigned int ph = 0; ph < 2; ph++) {
                const bool mph = ph == 1;
                if (!full && mph != mlp) continue;
                token_stats(s1, sxx, mean, inv, stats_out, st_off, !full);
                norm_full(xa, mean, inv, xb, xn);
                for (unsigned int job = 0; job < 3; job++) {
                    const unsigned int pj = mph ? 3 : job;
                    if (mph && job > 0) break;
                    if (!full && !((proj_mask >> pj) & 1)) continue;
                    const unsigned short pid = (unsigned short)(l * TT_ENGINE_NPROJ + pj);
#if TT_M3_OVERLAP
                    projection_with_attention(xb, wm12, wm3, pid, (unsigned short)(pid * TT_J), ob,
                                              full && !mph && pj == 2, qb, kb, attn);
#else
                    one_projection(xb, wm12, wm3, pid, (unsigned short)(pid * TT_J), ob);
#endif
                    if (!full) {
                        if (pj == 1) store_block(ob, k_out, in_off);
                        else if (pj == 2) store_block(ob, v_out, in_off);
                        else store_block(ob, q_out, in_off);
                    } else if (mph) {
                        res2(ob, xn, xa, s1, sxx);
                    } else if (pj == 0) {
                        copy_ob(ob, qb);
                    } else {
                        copy_ob(ob, kb);
                        if (pj == 1) {
#if !TT_M3_OVERLAP
                            ta_scores(qb, kb, sc); ta_softmax(sc, attn);
#endif
                        }
                        else {
                            // Copy the actual softmax matrix, before CTX consumes it.
                            // No extra full-tensor BRAM and no second attention pass.
                            if (attention) {
                                const unsigned int ao = (i * TT_ENGINE_ATTN_STRIDE + TT_ENGINE_ATTN_OFFSET + l * 144) / 8;
                                for (unsigned int ar=0;ar<TT_N;++ar)
                                    for (unsigned int ac=0;ac<TT_N/2;++ac) {
#pragma HLS PIPELINE II=1
                                        u64 aw=0;
                                        aw.range(31,0)=attn[ar][2*ac];
                                        aw.range(63,32)=attn[ar][2*ac+1];
                                        x_out[ao+ar*3+ac]=aw;
                                    }
                            }
                            ta_ctx(attn, kb, xn, xa, s1, sxx);
                        }
                    }
                }
            }
            if (dump || (feat && l == l_end)) { dump_x(xa, x_out, doff); doff += lstride; }
        }
        if (full && !feat) {
            const unsigned int cls = ta_head(xa, wh, eh, hb, ncls_r, lg);
            if (attention) {
                const unsigned int base=i*TT_ENGINE_ATTN_STRIDE/8;
                u64 hw=0;
                hw.range(31,0)=TT_ENGINE_ATTN_MAGIC; hw.range(63,32)=TT_ENGINE_VERSION; x_out[base]=hw;
                hw.range(31,0)=cls; hw.range(63,32)=ncls_r; x_out[base+1]=hw;
                hw.range(31,0)=12; hw.range(63,32)=6; x_out[base+2]=hw;
                hw.range(31,0)=24; hw.range(63,32)=432; x_out[base+3]=hw;
                for (unsigned int z=4;z<8;++z) {
#pragma HLS PIPELINE II=1
                    x_out[base+z]=0;
                }
                for (int k=0;k<TA_LOGITS/2;++k) {
#pragma HLS PIPELINE II=1
                    u64 w=0;w.range(31,0)=lg[2*k].range(31,0);w.range(63,32)=lg[2*k+1].range(31,0);
                    x_out[base+8+k]=w;
                }
            } else if (out_sel == TT_ENGINE_OUT_LOGITS) {
                for (int k = 0; k < TA_LOGITS / 2; k++) {
#pragma HLS PIPELINE II=1
                    u64 w;
                    w.range(31, 0) = lg[2 * k].range(31, 0);
                    w.range(63, 32) = lg[2 * k + 1].range(31, 0);
                    x_out[lo_off + k] = w;
                }
                lo_off += TA_LOGITS / 2;
            } else {                                        // CLASS：两个像素一个字；像素数为奇数时末字高半写 0
                if (i & 1) { cw.range(63, 32) = cls; x_out[i >> 1] = cw; }
                else {
                    cw = cls;
                    if (i == n_patch - 1) x_out[i >> 1] = cw;
                }
            }
        }
        in_off += TT_IN_WORDS;
        st_off += TT_ST_WORDS;
        fo += wpx;
    }
#else
    const unsigned short pid0 = (unsigned short)(layer_lo * TT_ENGINE_NPROJ);
    unsigned int in_off = 0, st_off = 0;
    for (unsigned int i = 0; i < n_patch; i++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=3
        s1_t s1[TT_N]; sxx_t sxx[TT_N]; q24_t mean[TT_N], inv[TT_N];
#pragma HLS ARRAY_PARTITION variable=s1 complete
#pragma HLS ARRAY_PARTITION variable=sxx complete
#pragma HLS ARRAY_PARTITION variable=mean complete
#pragma HLS ARRAY_PARTITION variable=inv complete
        load_stats(x_in, in_off, xb, s1, sxx);
        token_stats(s1, sxx, mean, inv, stats_out, st_off, true);
        normalize(xb, mean, inv);
        if (mlp) {
            const unsigned short p = pid0 + 3;
            one_projection(xb, wm12, wm3, p, (unsigned short)(p * TT_J), ob);
            store_block(ob, q_out, in_off);
        } else {
            if (proj_mask & TT_ENGINE_PROJ_Q) {
                one_projection(xb, wm12, wm3, pid0, (unsigned short)(pid0 * TT_J), ob);
                store_block(ob, q_out, in_off);
            }
            if (proj_mask & TT_ENGINE_PROJ_K) {
                const unsigned short p = pid0 + 1;
                one_projection(xb, wm12, wm3, p, (unsigned short)(p * TT_J), ob);
                store_block(ob, k_out, in_off);
            }
            if (proj_mask & TT_ENGINE_PROJ_V) {
                const unsigned short p = pid0 + 2;
                one_projection(xb, wm12, wm3, p, (unsigned short)(p * TT_J), ob);
                store_block(ob, v_out, in_off);
            }
        }
        in_off += TT_IN_WORDS;
        st_off += TT_ST_WORDS;
    }
#endif
    return err | ret_hi;
}
