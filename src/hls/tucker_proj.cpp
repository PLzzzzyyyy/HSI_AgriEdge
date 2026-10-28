// tucker_proj —— Tensor Transformer 的 Tucker 投影算子（一次调用 = 1 或 3 个投影，对 n_tok 个 token）
//
//   Y = X ×1 M1 ×2 M2 ×3 M3        Y[a][b][c] = Σ_j M3[c][j] Σ_i2 M2[b][i2] Σ_i1 M1[a][i1] X[i1][i2][j]
//
// DDR 布局（与 torch (7,7,54,N) 的内存序相同，PS 不需要转置）：
//   in / out : D*N 个 data_t，元素 (p, n) 在 p*N + n，p = (i1*7 + i2)*54 + j = i1*378 + r
//   w        : 3014 个 wt_t，M1[7][7]、M2[7][7]、M3[54][54] 依次行主序
// 计算顺序固定 模1 → 模2 → 模3，中间量 mid_t 各舍入一次，出口舍入到 data_t。
// 与 model/quant.py::tucker_proj_int 逐位一致，改任何一处舍入位置都会破坏对拍。
//
// 编译选项（build/hls/run_variant.tcl 的 variant 表；全部不定义 = 已部署 IP 的算法与接口）：
//   TT_FM64        激活块 in/out_* 走 64 位 AXI，一拍 4 个 int16；n_tok 只允许 6/10
//   TT_WT32        因子 w_* 走 32 位 AXI，一拍 2 个 int16（每投影 3014 元素 = 1507 字，DDR 起址需 4 字节对齐）
//   TT_TOKEN_DF    token 级流水：mode1 / mode2 / mode3 三段 DATAFLOW 重叠，t1、t2 变 ping-pong
//   TT_MODE3_DUAL  mode3 一拍算两个空间位置（乘法器 54 → 108）
// 片上缓冲一律"扁平下标 + 跑动计数器"寻址，不出现变量乘法/除法，免得 HLS 把地址运算放进 DSP。
#include "tt_types.h"

// ---------------------------------------------------------------- 片上缓冲布局
// xb[n&1][i1][(r*NMAX + n) >> 1]：先按 token 奇偶分两组、再按 i1 分 7 个 bank，共 14 个 bank。
// 64 位加载时 lane 0/2 永远是偶数 token、lane 1/3 永远是奇数 token（N 为偶数），所以组号是编译期常量，
// 每个 bank 一拍最多两次写（双端口），不需要 HLS 去证明地址奇偶。
#define TT_XB_HALF (TT_R * TT_NMAX / 2)   // 1890
// ob[p*N + n]：就是 DDR 输出块的原样镜像，按下标 mod 4 分 4 路。
// mode3 每拍只写 1 个（DUAL 2 个）元素，store 每拍从 4 路各读 1 个拼成 64 位；16 位宽的 BRAM 不浪费。
#define TT_OB_LEN (TT_D * TT_NMAX)        // 26460

// ---------------------------------------------------------------- DDR 整块 → 片上 xb
#ifndef TT_FM64
// 单层循环 + 手工计数器：整个块 D*N 个元素以 II=1 连续读（嵌套循环每次进入内层都付流水启动开销）
static void load_block(fm_t *in, data_t xb[2][TT_W][TT_XB_HALF], unsigned short n_tok) {
    const unsigned int total = (unsigned int)TT_D * n_tok;
    unsigned short n = 0, r = 0, i1 = 0, idx = 0;       // idx = r*NMAX + n
    for (unsigned int e = 0; e < total; e++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=15876 max=26460
        const data_t value = in[e];
        if (n & 1) xb[1][i1][idx >> 1] = value;
        else       xb[0][i1][idx >> 1] = value;
        if (n == n_tok - 1) {
            n = 0;
            if (r == TT_R - 1) { r = 0; i1++; idx = 0; }
            else { r++; idx += TT_NMAX - (n_tok - 1); }
        } else { n++; idx++; }
    }
}
#else
// 一拍 64 位 = 线性元素 4e..4e+3。N 为偶数、n 从偶数起步，一拍最多跨一次 p 边界，且只会在 lane 2 处跨。
static void load_block(fm_t *in, data_t xb[2][TT_W][TT_XB_HALF], unsigned short n_tok) {
    unsigned short n = 0, r = 0, i1 = 0, rbase = 0;     // rbase = r*NMAX
    const unsigned int beats = (unsigned int)TT_D * n_tok / 4;
    for (unsigned int e = 0; e < beats; e++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=3969 max=6615
#pragma HLS DEPENDENCE variable=xb inter false
        const fm_t word = in[e];
        for (unsigned short lane = 0; lane < 4; lane++) {
#pragma HLS UNROLL
            const unsigned short nn = n + lane;
            const bool next = nn >= n_tok;
            const unsigned short nl = next ? (unsigned short)(nn - n_tok) : nn;
            const bool wrap = next && r == TT_R - 1;                  // 末拍不会发生（块尾正好对齐）
            const unsigned short il = wrap ? (unsigned short)(i1 + 1) : i1;
            const unsigned short base = wrap ? (unsigned short)0
                                             : (next ? (unsigned short)(rbase + TT_NMAX) : rbase);
            const unsigned short idx = base + nl;                     // 奇偶 = lane 奇偶
            data_t value;
            value.range(15, 0) = word.range(16 * lane + 15, 16 * lane);
            xb[lane & 1][il][idx >> 1] = value;
        }
        if (n + 4 >= n_tok) {
            n = n + 4 - n_tok;
            if (r == TT_R - 1) { r = 0; rbase = 0; i1++; } else { r++; rbase += TT_NMAX; }
        } else n += 4;
    }
}
#endif

// ---------------------------------------------------------------- v1.4：片上 token 归一化（TT_NORM_IN）
// 算法与 src/ps/tt_ref_int.h::normalize 逐位一致（整数矩、float32 标量 inv、Q.24 定点乘、四舍五入饱和）。
#ifdef TT_NORM_IN
#include <hls_math.h>
#include <math.h>
// sqrt：综合用 hls::sqrt（IEEE 单精度正确舍入的 CORDIC/查表实现，与 libm sqrtf 逐位相同）；主机预检直接用 sqrtf
#ifdef __SYNTHESIS__
static inline float tt_sqrtf(float v) { return hls::sqrt(v); }
#else
static inline float tt_sqrtf(float v) { return sqrtf(v); }
#endif
typedef ap_int<28>  s1_t;      // Σx：|x| < 2^15，D = 2646 → < 2^27
typedef ap_uint<42> sxx_t;     // Σx²：< 2646·2^30 < 2^42
typedef ap_int<56>  var_t;     // D·Sxx − S1²：< 2^54
typedef ap_int<32>  q24_t;     // mean_q24（|·| ≤ 2^27）、inv_q24（< 2^31）
enum { TT_SLOTS = TT_NMAX / 2 };

// 与 load_block（FM64）相同的搬运，同时按车道累加每个 token 的 S1、Sxx。
// 车道 lane 的 token 奇偶 = lane 奇偶，所以每个车道只需 5 个槽（n>>1）；4 个车道各自私有一组累加器，一拍各写一次。
static void load_block_stats(fm_t *in, data_t xb[2][TT_W][TT_XB_HALF], unsigned short n_tok,
                             s1_t s1[TT_NMAX], sxx_t sxx[TT_NMAX]) {
    s1_t  a1[4][TT_SLOTS];
    sxx_t a2[4][TT_SLOTS];
#pragma HLS ARRAY_PARTITION variable=a1 complete dim=0
#pragma HLS ARRAY_PARTITION variable=a2 complete dim=0
    for (unsigned short l = 0; l < 4; l++)
        for (unsigned short s = 0; s < TT_SLOTS; s++) { a1[l][s] = 0; a2[l][s] = 0; }
    unsigned short n = 0, r = 0, i1 = 0, rbase = 0;
    const unsigned int beats = (unsigned int)TT_D * n_tok / 4;
    for (unsigned int e = 0; e < beats; e++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=3969 max=6615
#pragma HLS DEPENDENCE variable=xb inter false
        const fm_t word = in[e];
        for (unsigned short lane = 0; lane < 4; lane++) {
#pragma HLS UNROLL
            const unsigned short nn = n + lane;
            const bool next = nn >= n_tok;
            const unsigned short nl = next ? (unsigned short)(nn - n_tok) : nn;
            const bool wrap = next && r == TT_R - 1;
            const unsigned short il = wrap ? (unsigned short)(i1 + 1) : i1;
            const unsigned short base = wrap ? (unsigned short)0
                                             : (next ? (unsigned short)(rbase + TT_NMAX) : rbase);
            const unsigned short idx = base + nl;
            data_t value;
            value.range(15, 0) = word.range(16 * lane + 15, 16 * lane);
            xb[lane & 1][il][idx >> 1] = value;
            ap_int<16> xi;
            xi.range(15, 0) = word.range(16 * lane + 15, 16 * lane);
            const ap_int<32> sq = xi * xi;                            // 16×16 → 1 DSP
            const unsigned short slot = nl >> 1;
            a1[lane][slot] = a1[lane][slot] + xi;
            a2[lane][slot] = a2[lane][slot] + (ap_uint<31>)sq;
        }
        if (n + 4 >= n_tok) {
            n = n + 4 - n_tok;
            if (r == TT_R - 1) { r = 0; rbase = 0; i1++; } else { r++; rbase += TT_NMAX; }
        } else n += 4;
    }
    for (unsigned short t = 0; t < TT_NMAX; t++) {                    // 整数求和，顺序无关
#pragma HLS UNROLL
        const unsigned short s = t >> 1, p = t & 1;
        s1[t]  = a1[p][s] + a1[p + 2][s];
        sxx[t] = a2[p][s] + a2[p + 2][s];
    }
}

// 每个 token 的标量：mean_q24 = (S1<<12)/D（向零截断）；inv = C / sqrtf((float)var_num)，clamp ≤ 127；inv_q24 = trunc(inv·2^24)
static void token_stats(const s1_t s1[TT_NMAX], const sxx_t sxx[TT_NMAX], unsigned short n_tok,
                        q24_t mean[TT_NMAX], q24_t inv[TT_NMAX], fm_t *stats) {
    for (unsigned short t = 0; t < TT_NMAX; t++) {
#pragma HLS PIPELINE off
        if (t < n_tok) {
            const var_t var_num = (var_t)((ap_uint<54>)sxx[t] * (ap_uint<12>)TT_D) - (var_t)(s1[t] * s1[t]);
            const ap_int<40> s1_12 = ((ap_int<40>)s1[t]) << TT_DF;
            const ap_int<40> m = s1_12 / (ap_int<13>)TT_D;
            const long long vn = (long long)var_num;
            const float vf = (float)vn;
            float iv = 10835968.0f / tt_sqrtf(vf);
            if (!(iv <= 127.0f)) iv = 127.0f;
            const int inv_i = (int)(iv * 16777216.0f);
            mean[t] = (q24_t)m;
            inv[t] = (q24_t)inv_i;
            fm_t word;
            word.range(31, 0) = ((ap_uint<32>)mean[t]).range(31, 0);
            word.range(63, 32) = ((ap_uint<32>)inv[t]).range(31, 0);
            stats[t] = word;
        } else { mean[t] = 0; inv[t] = 0; }
    }
}

// pass2：xb 原地 q = sat16((((x<<12) − mean)·inv_q24 + 2^35) >> 36)。同一拍处理同一 i1 的奇偶两组（两个乘法器），
// 地址 h = r*5 + (n>>1)：n>>1 = h % 5 用跑动计数器。n ≥ n_tok 的槽是无效数据，mean/inv 为 0 → 写 0，无副作用。
static inline data_t norm_one(data_t x, q24_t mean, q24_t inv) {
#pragma HLS INLINE
    ap_int<16> xi;
    xi.range(15, 0) = x.range(15, 0);
    const ap_int<29> d = (((ap_int<29>)xi) << TT_DF) - (ap_int<29>)mean;
    const ap_int<61> prod = d * inv;
    const ap_int<62> r = (prod + (ap_int<62>)(1LL << 35)) >> 36;    // 算术右移 = floor
    ap_int<16> qv;
    if (r > 32767) qv = 32767;
    else if (r < -32768) qv = -32768;
    else qv = (ap_int<16>)r;
    data_t out;
    out.range(15, 0) = qv.range(15, 0);
    return out;
}
static void normalize_block(data_t xb[2][TT_W][TT_XB_HALF], const q24_t mean[TT_NMAX], const q24_t inv[TT_NMAX]) {
    for (unsigned short i1 = 0; i1 < TT_W; i1++) {
        unsigned short s = 0;                                         // = h % 5
        for (unsigned short h = 0; h < TT_XB_HALF; h++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=xb inter false
            const unsigned short n0 = s << 1, n1 = n0 + 1;
            xb[0][i1][h] = norm_one(xb[0][i1][h], mean[n0], inv[n0]);
            xb[1][i1][h] = norm_one(xb[1][i1][h], mean[n1], inv[n1]);
            s = (s == TT_SLOTS - 1) ? (unsigned short)0 : (unsigned short)(s + 1);
        }
    }
}
#endif
#ifndef TT_WT32
static void load_factors(wt_bus_t *w, wt_t m1[TT_W][TT_W], wt_t m2[TT_W][TT_W], wt_t m3[TT_J][TT_J]) {
    unsigned int e = 0;
    for (unsigned short a = 0; a < TT_W; a++)
        for (unsigned short i = 0; i < TT_W; i++) {
#pragma HLS PIPELINE II=1
            m1[a][i] = w[e++];
        }
    for (unsigned short a = 0; a < TT_W; a++)
        for (unsigned short i = 0; i < TT_W; i++) {
#pragma HLS PIPELINE II=1
            m2[a][i] = w[e++];
        }
    for (unsigned short c = 0; c < TT_J; c++)
        for (unsigned short j = 0; j < TT_J; j++) {
#pragma HLS PIPELINE II=1
            m3[c][j] = w[e++];
        }
}
#else
// 32 位字 w[k]：15:0 是元素 2k，31:16 是元素 2k+1。前 49 字 = M1(49)+M2(49)，后 1458 字 = M3(2916)。
// M1/M2 合起来当 14 行 × 7 列扫（第 24 字跨 M1 末尾和 M2 开头）。
// M3 的一个字永远落在同一行 c（54 为偶数），列为偶数 j 和 j+1 → m3 第二维按奇偶分两路，一拍写两个。
static void put_m12(unsigned short row, unsigned short col, wt_t v, wt_t m1[TT_W][TT_W], wt_t m2[TT_W][TT_W]) {
#pragma HLS INLINE
    if (row < TT_W) m1[row][col] = v;
    else            m2[row - TT_W][col] = v;
}
static void load_factors(wt_bus_t *w, wt_t m1[TT_W][TT_W], wt_t m2[TT_W][TT_W], wt_t m3[TT_J][TT_J]) {
    unsigned short row = 0, col = 0;                     // 元素 2k 在 14×7 表里的位置
    for (unsigned short k = 0; k < TT_W * TT_W; k++) {
#pragma HLS PIPELINE II=1
        const wt_bus_t word = w[k];
        wt_t v0, v1;
        v0.range(15, 0) = word.range(15, 0);
        v1.range(15, 0) = word.range(31, 16);
        put_m12(row, col, v0, m1, m2);
        const unsigned short row1 = (col == TT_W - 1) ? (unsigned short)(row + 1) : row;
        const unsigned short col1 = (col == TT_W - 1) ? (unsigned short)0 : (unsigned short)(col + 1);
        put_m12(row1, col1, v1, m1, m2);
        if (col1 == TT_W - 1) { col = 0; row = row1 + 1; } else { col = col1 + 1; row = row1; }
    }
    unsigned short c = 0, j = 0;
    for (unsigned short k = 0; k < TT_J * TT_J / 2; k++) {
#pragma HLS PIPELINE II=1
        const wt_bus_t word = w[TT_W * TT_W + k];
        wt_t v0, v1;
        v0.range(15, 0) = word.range(15, 0);
        v1.range(15, 0) = word.range(31, 16);
        m3[c][j] = v0;
        m3[c][j + 1] = v1;
        if (j == TT_J - 2) { j = 0; c++; } else j += 2;
    }
}
#endif

// ---------------------------------------------------------------- 三个模积
// 模 1：t1[a][i2][j] = Σ_i1 M1[a][i1] · X[i1][i2][j]      49 MAC/周期，378 次迭代
static void mode1(data_t xb[2][TT_W][TT_XB_HALF], unsigned short n, wt_t m1[TT_W][TT_W],
                  mid_t t1[TT_W][TT_W][TT_J]) {
    const bool odd = n & 1;
    unsigned short idx = n >> 1, i2 = 0, j = 0;          // idx = (r*NMAX + n) >> 1，r = i2*54 + j
    for (unsigned short r = 0; r < TT_R; r++) {
#pragma HLS PIPELINE II=1
        data_t x[TT_W];
#pragma HLS ARRAY_PARTITION variable=x complete
        for (unsigned short i1 = 0; i1 < TT_W; i1++) x[i1] = odd ? xb[1][i1][idx] : xb[0][i1][idx];
        for (unsigned short a = 0; a < TT_W; a++) {
            acc_t acc = 0;
            for (unsigned short i1 = 0; i1 < TT_W; i1++) acc += x[i1] * m1[a][i1];      // 16×16 原生位宽 → 1 DSP；转成 acc_t 再乘会变 48 位乘法
            t1[a][i2][j] = (mid_t)acc;
        }
        idx += TT_NMAX / 2;
        if (j == TT_J - 1) { j = 0; i2++; } else j++;
    }
}

// 模 2：t2[a][b][j] = Σ_i2 M2[b][i2] · t1[a][i2][j]       49 MAC/周期，378 次迭代
static void mode2(mid_t t1[TT_W][TT_W][TT_J], wt_t m2[TT_W][TT_W], mid_t t2[TT_W][TT_W][TT_J]) {
    for (unsigned short a = 0; a < TT_W; a++)
        for (unsigned short j = 0; j < TT_J; j++) {
#pragma HLS PIPELINE II=1
            mid_t x[TT_W];
#pragma HLS ARRAY_PARTITION variable=x complete
            for (unsigned short i2 = 0; i2 < TT_W; i2++) x[i2] = t1[a][i2][j];
            for (unsigned short b = 0; b < TT_W; b++) {
                acc_t acc = 0;
                for (unsigned short i2 = 0; i2 < TT_W; i2++) acc += x[i2] * m2[b][i2];      // 18×16 → 1 DSP
                t2[a][b][j] = (mid_t)acc;
            }
        }
}

// 模 3：y[a][b][c] = Σ_j M3[c][j] · t2[a][b][j]           54 MAC/周期，2646 次迭代（DUAL：108 MAC，1350 次）
// 每 54 拍算完一个位置 ab 的 54 个输出，存进 pend[]；接下来 54 拍里每拍把 pend[j] 写到 ob[(ab*54 + j)*N + n]，
// 写地址每拍 +N，全程连续递增，所以 ob 每拍只有一次写（DUAL 两次），不需要 54 个并行写端口。
// 累加器 48 位不舍入不饱和，中途不会溢出，所以累加顺序不影响逐位结果。
// t2 只按 b 分 bank：DUAL 的两个位置 b 一定不同（b+1 或回绕到 0），两路读不抢端口。
static void mode3(mid_t t2[TT_W][TT_W][TT_J], wt_t m3[TT_J][TT_J], unsigned short n, unsigned short n_tok,
                  data_t ob[TT_OB_LEN]) {
#ifdef TT_MODE3_DUAL
    acc_t acc0[TT_J], acc1[TT_J];
    data_t pend0[TT_J], pend1[TT_J];
#pragma HLS ARRAY_PARTITION variable=acc0 complete
#pragma HLS ARRAY_PARTITION variable=acc1 complete
#pragma HLS ARRAY_PARTITION variable=pend0 complete
#pragma HLS ARRAY_PARTITION variable=pend1 complete
    const unsigned short step = TT_J * n_tok;            // 相邻两个位置在 ob 里相距 54*N
    unsigned short a0 = 0, b0 = 0, wl = n;               // (a0,b0) = 位置 ab；wl = 待写元素的线性下标
    bool have = false, pair = false;                     // pend 有效；pend1 也有效
    for (unsigned short ab = 0; ab < TT_W * TT_W; ab += 2)
        for (unsigned short j = 0; j < TT_J; j++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=ob inter false     // 两路写地址 wl、wl+54N 每拍各 +N，跨迭代永不相同
            const bool last = ab == TT_W * TT_W - 1;      // 49 为奇数：最后一对只有一个有效位置
            const unsigned short a1 = (b0 == TT_W - 1) ? (last ? (unsigned short)0 : (unsigned short)(a0 + 1)) : a0;
            const unsigned short b1 = (b0 == TT_W - 1) ? (unsigned short)0 : (unsigned short)(b0 + 1);
            const mid_t x0 = t2[a0][b0][j];
            const mid_t x1 = last ? mid_t(0) : t2[a1][b1][j];
            for (unsigned short c = 0; c < TT_J; c++) {
                const acc_t p0 = x0 * m3[c][j], p1 = x1 * m3[c][j];      // 18×16 → 1 DSP 各一个
                acc0[c] = (j == 0) ? p0 : (acc_t)(acc0[c] + p0);
                acc1[c] = (j == 0) ? p1 : (acc_t)(acc1[c] + p1);
            }
            if (have) {
                ob[wl] = pend0[j];
                if (pair) ob[wl + step] = pend1[j];
                wl += n_tok;
            }
            if (j == TT_J - 1) {
                for (unsigned short c = 0; c < TT_J; c++) { pend0[c] = (data_t)acc0[c]; pend1[c] = (data_t)acc1[c]; }
                if (have && pair) wl += step;             // 跳过刚由 pend1 写完的那个位置
                have = true; pair = !last;
                if (b0 >= TT_W - 2) { b0 = b0 + 2 - TT_W; a0++; } else b0 += 2;
            }
        }
    for (unsigned short j = 0; j < TT_J; j++) {          // 最后一对（只有 pend0 有效）
#pragma HLS PIPELINE II=1
        ob[wl] = pend0[j];
        wl += n_tok;
    }
#else
    acc_t acc[TT_J];
    data_t pend[TT_J];
#pragma HLS ARRAY_PARTITION variable=acc complete
#pragma HLS ARRAY_PARTITION variable=pend complete
    unsigned short a = 0, b = 0, wl = n;
    bool have = false;
    for (unsigned short ab = 0; ab < TT_W * TT_W; ab++)
        for (unsigned short j = 0; j < TT_J; j++) {
#pragma HLS PIPELINE II=1
            const mid_t x = t2[a][b][j];
            for (unsigned short c = 0; c < TT_J; c++) {
                const acc_t p = x * m3[c][j];             // 18×16 → 1 DSP
                acc[c] = (j == 0) ? p : (acc_t)(acc[c] + p);
            }
            if (have) { ob[wl] = pend[j]; wl += n_tok; }
            if (j == TT_J - 1) {
                for (unsigned short c = 0; c < TT_J; c++) pend[c] = (data_t)acc[c];
                have = true;
                if (b == TT_W - 1) { b = 0; a++; } else b++;
            }
        }
    for (unsigned short j = 0; j < TT_J; j++) {          // 最后一个位置
#pragma HLS PIPELINE II=1
        ob[wl] = pend[j];
        wl += n_tok;
    }
#endif
}

// ---------------------------------------------------------------- 片上 ob → DDR（ob 就是 DDR 镜像）
#ifndef TT_FM64
static void store_block(data_t ob[TT_OB_LEN], fm_t *out, unsigned short n_tok) {
    const unsigned int total = (unsigned int)TT_D * n_tok;
    for (unsigned int e = 0; e < total; e++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=15876 max=26460
        out[e] = ob[e];
    }
}
#else
// 一拍 64 位 = 线性元素 4e..4e+3，正好是 4 路 bank 各取地址 e 的一个元素
static void store_block(data_t ob[TT_OB_LEN], fm_t *out, unsigned short n_tok) {
    const unsigned int beats = (unsigned int)TT_D * n_tok / 4;
    for (unsigned int e = 0; e < beats; e++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=3969 max=6615
        fm_t word = 0;
        for (unsigned short lane = 0; lane < 4; lane++) {
#pragma HLS UNROLL
            const data_t value = ob[4 * e + lane];
            word.range(16 * lane + 15, 16 * lane) = value.range(15, 0);
        }
        out[e] = word;
    }
}
#endif

// ---------------------------------------------------------------- 一个投影
#ifdef TT_TOKEN_DF
// token 级流水：第 n 个 token 的 mode3（最长，2646 或 1350 拍）与第 n+1 个 token 的 mode1/mode2 重叠。
// t1、t2 在 DATAFLOW 区内声明，HLS 自动做成 ping-pong；xb 只被 mode1 读，ob 只被 mode3 写。
// t1 是 49 个 54 字的小块，ping-pong 后放 LUTRAM（默认会占 49 块 BRAM18K）。
static void token_pipeline(data_t xb[2][TT_W][TT_XB_HALF], wt_t m1[TT_W][TT_W], wt_t m2[TT_W][TT_W],
                           wt_t m3[TT_J][TT_J], data_t ob[TT_OB_LEN], unsigned short n_tok) {
    for (unsigned short n = 0; n < n_tok; n++) {
#pragma HLS LOOP_TRIPCOUNT min=6 max=10
#pragma HLS DATAFLOW
        mid_t t1[TT_W][TT_W][TT_J], t2[TT_W][TT_W][TT_J];
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=1
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=2
#pragma HLS BIND_STORAGE variable=t1 type=ram_2p impl=lutram
#pragma HLS ARRAY_PARTITION variable=t2 complete dim=2
        mode1(xb, n, m1, t1);
        mode2(t1, m2, t2);
        mode3(t2, m3, n, n_tok, ob);
    }
}
#endif

static void one_projection(data_t xb[2][TT_W][TT_XB_HALF], wt_bus_t *w, fm_t *out, unsigned short n_tok) {
    wt_t m1[TT_W][TT_W], m2[TT_W][TT_W], m3[TT_J][TT_J];
#pragma HLS ARRAY_PARTITION variable=m1 complete dim=0
#pragma HLS ARRAY_PARTITION variable=m2 complete dim=0
#pragma HLS ARRAY_PARTITION variable=m3 complete dim=1
#ifdef TT_WT32
#pragma HLS ARRAY_PARTITION variable=m3 cyclic factor=2 dim=2      // 一拍写同一行的 j、j+1
#endif
    data_t ob[TT_OB_LEN];
#pragma HLS ARRAY_PARTITION variable=ob cyclic factor=4
#ifdef TT_MODE3_DUAL
#pragma HLS BIND_STORAGE variable=ob type=ram_t2p impl=bram        // 两个位置相距 54*N，落在同一路，一拍两次写
#endif

    load_factors(w, m1, m2, m3);
#ifdef TT_TOKEN_DF
    token_pipeline(xb, m1, m2, m3, ob, n_tok);
#else
    mid_t t1[TT_W][TT_W][TT_J], t2[TT_W][TT_W][TT_J];
    // mode1 一拍写全部 a；mode2 一拍读全部 i2：t1 两维都分开，读写两侧都不被 RAM 端口串行化
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=1
#pragma HLS ARRAY_PARTITION variable=t1 complete dim=2
#pragma HLS ARRAY_PARTITION variable=t2 complete dim=2
    for (unsigned short n = 0; n < n_tok; n++) {
#pragma HLS LOOP_TRIPCOUNT min=6 max=10
        mode1(xb, n, m1, t1);
        mode2(t1, m2, t2);
        mode3(t2, m3, n, n_tok, ob);
    }
#endif
    store_block(ob, out, n_tok);
}

// ---------------------------------------------------------------- 顶层
#ifdef TT_NORM_IN
void tucker_proj(fm_t *in, fm_t *out_q, fm_t *out_k, fm_t *out_v, fm_t *stats,
                 wt_bus_t *w_q, wt_bus_t *w_k, wt_bus_t *w_v,
                 unsigned short n_tok, unsigned short n_proj) {
#pragma HLS INTERFACE m_axi depth=10 port=stats offset=slave bundle=FM max_write_burst_length=256
#pragma HLS INTERFACE s_axilite port=stats bundle=CTRL
#else
void tucker_proj(fm_t *in, fm_t *out_q, fm_t *out_k, fm_t *out_v,
                 wt_bus_t *w_q, wt_bus_t *w_k, wt_bus_t *w_v,
                 unsigned short n_tok, unsigned short n_proj) {
#endif
#ifdef TT_FM64
#pragma HLS INTERFACE m_axi depth=6615 port=in    offset=slave bundle=FM max_read_burst_length=256
#pragma HLS INTERFACE m_axi depth=6615 port=out_q offset=slave bundle=FM max_write_burst_length=256
#pragma HLS INTERFACE m_axi depth=6615 port=out_k offset=slave bundle=FM max_write_burst_length=256
#pragma HLS INTERFACE m_axi depth=6615 port=out_v offset=slave bundle=FM max_write_burst_length=256
#else
#pragma HLS INTERFACE m_axi depth=26460 port=in    offset=slave bundle=FM max_read_burst_length=256
#pragma HLS INTERFACE m_axi depth=26460 port=out_q offset=slave bundle=FM max_write_burst_length=256
#pragma HLS INTERFACE m_axi depth=26460 port=out_k offset=slave bundle=FM max_write_burst_length=256
#pragma HLS INTERFACE m_axi depth=26460 port=out_v offset=slave bundle=FM max_write_burst_length=256
#endif
#ifdef TT_WT32
#pragma HLS INTERFACE m_axi depth=1507  port=w_q   offset=slave bundle=WT max_read_burst_length=256
#pragma HLS INTERFACE m_axi depth=1507  port=w_k   offset=slave bundle=WT max_read_burst_length=256
#pragma HLS INTERFACE m_axi depth=1507  port=w_v   offset=slave bundle=WT max_read_burst_length=256
#else
#pragma HLS INTERFACE m_axi depth=3014  port=w_q   offset=slave bundle=WT max_read_burst_length=256
#pragma HLS INTERFACE m_axi depth=3014  port=w_k   offset=slave bundle=WT max_read_burst_length=256
#pragma HLS INTERFACE m_axi depth=3014  port=w_v   offset=slave bundle=WT max_read_burst_length=256
#endif
#pragma HLS INTERFACE s_axilite port=in     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=out_q  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=out_k  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=out_v  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=w_q    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=w_k    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=w_v    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=n_tok  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=n_proj bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL

    data_t xb[2][TT_W][TT_XB_HALF];
#pragma HLS ARRAY_PARTITION variable=xb complete dim=1
#pragma HLS ARRAY_PARTITION variable=xb complete dim=2
#ifdef TT_FM64
#pragma HLS BIND_STORAGE variable=xb type=ram_t2p impl=bram        // 一拍两个同奇偶 lane 写同一 bank
    if ((n_tok != 6 && n_tok != 10) || n_proj < 1 || n_proj > 3) return;
#endif

    if (n_tok > TT_NMAX) n_tok = TT_NMAX;
#ifdef TT_NORM_IN
    s1_t s1[TT_NMAX]; sxx_t sxx[TT_NMAX]; q24_t mean[TT_NMAX], inv[TT_NMAX];
#pragma HLS ARRAY_PARTITION variable=s1 complete
#pragma HLS ARRAY_PARTITION variable=sxx complete
#pragma HLS ARRAY_PARTITION variable=mean complete
#pragma HLS ARRAY_PARTITION variable=inv complete
    load_block_stats(in, xb, n_tok, s1, sxx);
    token_stats(s1, sxx, n_tok, mean, inv, stats);
    normalize_block(xb, mean, inv);
#else
    load_block(in, xb, n_tok);
#endif
    one_projection(xb, w_q, out_q, n_tok);
    if (n_proj >= 2) one_projection(xb, w_k, out_k, n_tok);
    if (n_proj >= 3) one_projection(xb, w_v, out_v, n_tok);
}
