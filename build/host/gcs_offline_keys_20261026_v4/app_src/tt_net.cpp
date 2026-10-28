// PS 端整网实现（float32 内核，层间激活 int16 Q3.12）。每一步对应 model/fixed_point_sim.py 里同名函数，改动时两边同步。
//
// 性能要点（板上实测教训见 .claude/pitfalls.md）：
//   * A9 的 NEON 只有单精度，double 走 VFP 每 2 拍一条乘加且访存翻倍，所以 PS 侧全部用 float32。
//     A53（ZU5EV）沿用同一份 float32 内核：AArch64 NEON 有 FMA，但编译时用 -ffp-contract=off 保持"乘、加两次舍入"，
//     与主机 x86 路径（sim/golden）逐位可比；A53 也是顺序双发射，下面关于交错独立链的写法仍然适用。
//   * 激活始终保持 DDR 块的 (p, n) 内存序，PS 不做任何转置：per-token 的统计量用"周期 P = lcm(4, N) 的车道模式"处理。
//   * v1.4：token 归一化 + 量化在 PL 里做，PS 只从 PL 回传的 stats（mean_q24、inv_q24）复原 xn 做残差，
//     残差原地写回 int16 x（读 2 字节 + 写 2 字节），DDR 里不再有 float 激活和 in_q。
//   * 注意力分数直接从 PL 输出的 int16 块算，ctx 与残差合并成一趟，MLP 反量化与残差合并成一趟，没有单独的 dequant。
//   * 所有向量内核写在一个 4 车道的小封装 V 上：ARM 编译为 NEON 内联函数，其他平台为标量结构体，两者运算顺序逐条相同，
//     主机端（x86）与板上的 float32 结果只差 libm expf 的 ulp 级差异。
#include "tt_net.h"
#include "tt_hw.h"
#include "tt_measure.h"
#include <math.h>
#include <string.h>

// 预取提示：PL 写进 DDR 的 q/k/v/mlp 块在驱动 invalidate 之后不在任何 cache 里，PS 内核每读一行都要等 DDR。
// 板上实测（2026-09-19）只对还在 L2 里的数据有效；保留不改变任何结果。
#define TT_PF(p) __builtin_prefetch((p), 0, 3)

// ---------------------------------------------------------------- 4 车道向量封装
#if (defined(__arm__) || defined(__aarch64__)) && !defined(TT_NO_NEON)
#define TT_NEON 1
#ifdef __arm__
#pragma GCC target("fpu=neon")          // 7020 的 Vitis 工程默认 -mfpu=vfpv3，A9 上本文件自行启用 NEON；AArch64 的 NEON 是基线，不需要
#endif
#include <arm_neon.h>
typedef float32x4_t V;
static inline V vload(const float *p) { return vld1q_f32(p); }
static inline void vstore(float *p, V a) { vst1q_f32(p, a); }
static inline V vzero() { return vdupq_n_f32(0.f); }
static inline V vadd(V a, V b) { return vaddq_f32(a, b); }
static inline V vsub(V a, V b) { return vsubq_f32(a, b); }
static inline V vmul(V a, V b) { return vmulq_f32(a, b); }
static inline V vmla(V acc, V a, V b) { return vmlaq_f32(acc, a, b); }          // acc + a*b，两次舍入：A9 无 FMA；A53 编译时加 -ffp-contract=off 禁止融合成 FMLA，与主机路径一致
static inline V vmla_n(V acc, V a, float s) { return vmlaq_n_f32(acc, a, s); }
#ifdef __aarch64__
template <int L> static inline V vmla_lane(V acc, V a, V b) { return vmlaq_laneq_f32(acc, a, b, L); }   // AArch64 按元素乘可直接取 128 位寄存器的任一车道
template <int L> static inline V vdupl(V b) { return vdupq_laneq_f32(b, L); }
#else
template <int L> static inline V vmla_lane(V acc, V a, V b) {                   // acc + a * b[L]
    return L < 2 ? vmlaq_lane_f32(acc, a, vget_low_f32(b), L & 1) : vmlaq_lane_f32(acc, a, vget_high_f32(b), L & 1);
}
template <int L> static inline V vdupl(V b) { return L < 2 ? vdupq_lane_f32(vget_low_f32(b), L & 1) : vdupq_lane_f32(vget_high_f32(b), L & 1); }
#endif
static inline V vcvt4(const int16_t *p) { return vcvtq_f32_s32(vmovl_s16(vld1_s16(p))); }   // 4 个 int16 → float
typedef int16x4_t VH;
static inline VH vldh(const int16_t *p) { return vld1_s16(p); }
static inline V  vcvth(VH h) { return vcvtq_f32_s32(vmovl_s16(h)); }
static inline V vcvt2(const int16_t *p) {                                                    // p[0] p[1] p[0] p[1]
    int32_t w; memcpy(&w, p, 4);
    return vcvtq_f32_s32(vmovl_s16(vreinterpret_s16_s32(vdup_n_s32(w))));
}
// float → Q3.12 魔数法：t = fl(x·4096 + 1.5·2^23)，t 的位模式减 0x4B400000 就是 rne(x·4096)（|x·4096| < 2^22，本网络 |x| < 8）；
// vqmovn 饱和到 int16。依赖链 vmla → vsub.i32 → vqmovn → vst1 共 4 条（原 floor 写法 8 条）。舍入为四舍六入五成双。
#define TT_QMAGIC 12582912.0f
#define TT_QMAGIC_BITS 0x4B400000
typedef int32x4_t VI;
static inline V   vq_a(V x) { return vmlaq_n_f32(vdupq_n_f32(TT_QMAGIC), x, (float)TT_SCALE); }
static inline VI  vq_b(V t) { return vsubq_s32(vreinterpretq_s32_f32(t), vdupq_n_s32(TT_QMAGIC_BITS)); }
static inline void vq_c(VI v, int16_t *q) { vst1_s16(q, vqmovn_s32(v)); }
static inline void vquant_vec(V x, int16_t *q) { vq_c(vq_b(vq_a(x)), q); }
#else
#define TT_NEON 0
struct V { float v[4]; };
static inline V vload(const float *p) { V r; for (int i = 0; i < 4; i++) r.v[i] = p[i]; return r; }
static inline void vstore(float *p, V a) { for (int i = 0; i < 4; i++) p[i] = a.v[i]; }
static inline V vzero() { V r = { { 0, 0, 0, 0 } }; return r; }
static inline V vadd(V a, V b) { V r; for (int i = 0; i < 4; i++) r.v[i] = a.v[i] + b.v[i]; return r; }
static inline V vsub(V a, V b) { V r; for (int i = 0; i < 4; i++) r.v[i] = a.v[i] - b.v[i]; return r; }
static inline V vmul(V a, V b) { V r; for (int i = 0; i < 4; i++) r.v[i] = a.v[i] * b.v[i]; return r; }
static inline V vmla(V acc, V a, V b) { V r; for (int i = 0; i < 4; i++) { float t = a.v[i] * b.v[i]; r.v[i] = acc.v[i] + t; } return r; }
static inline V vmla_n(V acc, V a, float s) { V r; for (int i = 0; i < 4; i++) { float t = a.v[i] * s; r.v[i] = acc.v[i] + t; } return r; }
template <int L> static inline V vmla_lane(V acc, V a, V b) { return vmla_n(acc, a, b.v[L]); }
template <int L> static inline V vdupl(V b) { V r; for (int i = 0; i < 4; i++) r.v[i] = b.v[L]; return r; }
static inline V vcvt4(const int16_t *p) { V r; for (int i = 0; i < 4; i++) r.v[i] = (float)p[i]; return r; }
struct VH { int16_t v[4]; };
static inline VH vldh(const int16_t *p) { VH r; for (int i = 0; i < 4; i++) r.v[i] = p[i]; return r; }
static inline V  vcvth(VH h) { V r; for (int i = 0; i < 4; i++) r.v[i] = (float)h.v[i]; return r; }
static inline V vcvt2(const int16_t *p) { V r = { { (float)p[0], (float)p[1], (float)p[0], (float)p[1] } }; return r; }
#define TT_QMAGIC 12582912.0f
#define TT_QMAGIC_BITS 0x4B400000
struct VI { int32_t v[4]; };
static inline V  vq_a(V x) { V r; for (int i = 0; i < 4; i++) { float m = x.v[i] * (float)TT_SCALE; r.v[i] = TT_QMAGIC + m; } return r; }
static inline VI vq_b(V t) { VI r; for (int i = 0; i < 4; i++) { int32_t b; memcpy(&b, &t.v[i], 4); r.v[i] = b - TT_QMAGIC_BITS; } return r; }
static inline void vq_c(VI v, int16_t *q) {
    for (int i = 0; i < 4; i++) { int32_t t = v.v[i]; q[i] = (int16_t)(t > 32767 ? 32767 : (t < -32768 ? -32768 : t)); }
}
static inline void vquant_vec(V x, int16_t *q) { vq_c(vq_b(vq_a(x)), q); }
#endif

// 标量版，与 vquant_vec 逐位相同（尾巴用）
static inline int16_t quant1(float x) {
    float m = x * (float)TT_SCALE; float t = TT_QMAGIC + m;
    int32_t b; memcpy(&b, &t, 4); b -= TT_QMAGIC_BITS;
    return (int16_t)(b > 32767 ? 32767 : (b < -32768 ? -32768 : b));
}
static const float K_DQ = 1.0f / TT_SCALE;          // Q3.12 → float
static const float K_Q24 = 1.0f / 16777216.0f;      // Q.24 → float

// ---------------------------------------------------------------- 计时
tt_clock_fn tt_clock = 0;
unsigned long long tt_prof[TT_PROF_N];
unsigned long long tt_layer_prof[TT_LAYERS][TT_PROF_N];
unsigned long long tt_layer_ticks[TT_LAYERS];
const char *tt_prof_name[TT_PROF_N] = { "PL norm+qkv", "attn scores", "attn ctx+resid", "PL norm+mlp", "mlp resid" };

void tt_profile_reset() {
    memset(tt_prof, 0, sizeof(tt_prof));
    memset(tt_layer_prof, 0, sizeof(tt_layer_prof));
    memset(tt_layer_ticks, 0, sizeof(tt_layer_ticks));
}

const char *tt_net_backend_name() { return TT_NEON ? "NEON" : "scalar"; }

// ---------------------------------------------------------------- embed
// patch [270*7*7]（CHW 内存序）→ x[D*N]：token 0 = cls，token 1..seq = patch 的 reshape(7,7,54,seq)，再加位置编码，量化 Q3.12
// reshape 是纯内存序操作：token 张量元素 (p, m) = patch_flat[p*seq + m]
// 每次 2 个位置 = 2N 个元素（4 的倍数）先加进小缓冲，再向量量化（标量 quant1 逐元素慢 3 倍）
void tt_embed(const TTNet &net, const float *patch, int16_t *x) {
    TTMeasureScope measured(TT_MEASURE_EMBED);
    const int N = net.N, seq = net.seq, B = 2 * N;
    float t[2 * TT_NMAX];
    for (int p = 0; p < TT_D; p += 2) {
        for (int k = 0; k < 2; k++) {
            const int q = p + k;
            t[k * N] = net.cls_token[q] + net.pos_embed[q * N];
            for (int m = 0; m < seq; m++) t[k * N + 1 + m] = patch[q * seq + m] + net.pos_embed[q * N + 1 + m];
        }
        for (int i = 0; i < B; i += 4) vquant_vec(vload(t + i), x + p * N + i);
    }
}

// ---------------------------------------------------------------- quant
void tt_quant(const tt_real *x, int16_t *q, int count) {
    int i = 0;
    for (; i + 4 <= count; i += 4) vquant_vec(vload(x + i), q + i);
    for (; i < count; i++) q[i] = quant1(x[i]);
}

// ---------------------------------------------------------------- 归一化统计量 → 车道模式
// 布局 (p, n)，n 最内层：扁平下标 i 的 token 是 i % NN。P = lcm(4, NN) 是车道周期；pm/pi 存两个周期再多 4 个，
// 从相位 f 起连续读 4 个就是下标 i..i+3 的 mean / inv，f = (i % P) 或 (段内相位 + 段起点相位)，最大 2P-2。
template <int NN> struct Pat { enum { P = (NN % 4 == 0) ? NN : NN * 2, R = P / 4 }; };   // NN=6 → 12, NN=10 → 20
// xn = (x/4096 − mean)·inv 合成一条乘加：xn = b + x·a，a = inv/4096，b = −mean·inv（每 token 各算一次，float32）。
template <int NN> struct Norm {
    enum { P = Pat<NN>::P, L = 2 * P + 4 };
    float pa[L], pb[L];
    int off[NN];                                                     // ctx 第 n 段起点 n*D 的相位 (n*D) % P
    explicit Norm(const int32_t *stats) {
        float a[NN], b[NN];
        for (int n = 0; n < NN; n++) {
            const float mean = (float)stats[2 * n] * K_Q24, inv = (float)stats[2 * n + 1] * K_Q24;
            a[n] = inv * K_DQ; b[n] = -(mean * inv);
        }
        for (int l = 0; l < L; l++) { pa[l] = a[l % NN]; pb[l] = b[l % NN]; }
        for (int n = 0; n < NN; n++) off[n] = (n * TT_D) % P;
    }
    inline V xn(const int16_t *x, int i, int f) const {              // 下标 i..i+3 的归一化值，f 为相位
        return vmla(vload(pb + f), vcvt4(x + i), vload(pa + f));
    }
    inline float xn1(const int16_t *x, int i) const { float t = (float)x[i] * pa[i % NN]; return pb[i % NN] + t; }
};

// ---------------------------------------------------------------- attention
// 逐字复刻原代码：Q/K 是 (D,N) 正常内积；V 是内存序按 D 切块（不是转置）；ctx 也直接是内存序。
//   scores[n][c] = Σ_p q[p,n] k[p,c]             softmax 沿 c，无缩放
//   ctx_flat[n*D + j] = Σ_c attn[n][c] · v_flat[c*D + j]
// scores 沿 c 向量化，按 k 行的 4 列一段（segment）分趟：一趟里每个 p 取 k 行的一段 + q 行全部，acc[n] += k 段 · q[n]。
// 分趟是为了寄存器：NN=6 时一趟 6 个累加器 + 1 段 + 2 个 q 向量 = 9 个 q 寄存器；一次算全部 (n,c) 要 16 个，GCC 会把累加器溢出到栈。
// 累加器必须是独立的具名变量：写成 V acc[NN] 数组时 GCC 9 每次迭代都把它回写栈（反汇编实测），所以按 NN 手写两份。
// 求和顺序 p 升序、每个 (n,c) 一个累加器，主机标量版完全相同。
template <int NN> struct Row {
    enum { KV = (NN + 3) / 4 };
    static inline V seg(const int16_t *row, int v) { return (v < NN / 4) ? vcvt4(row + 4 * v) : vcvt2(row + 4 * v); }
};
// 一趟：out[n] = Σ_p kseg_v(p) · q[p][n]，v 为 k 行的段号
template <int NN> static void scores_pass(const int16_t *q, const int16_t *k, int v, float *out);
template <> void scores_pass<6>(const int16_t *q, const int16_t *k, int v, float *out) {
    V a0 = vzero(), a1 = a0, a2 = a0, a3 = a0, a4 = a0, a5 = a0;
    for (int p = 0; p < TT_D; p++) {
        TT_PF(k + (p + 32) * 6); TT_PF(q + (p + 32) * 6);           // 12 字节/迭代，提前约 6 行
        const V ks = Row<6>::seg(k + p * 6, v);
        const V q0 = vcvt4(q + p * 6), q1 = vcvt2(q + p * 6 + 4);
        a0 = vmla_lane<0>(a0, ks, q0); a1 = vmla_lane<1>(a1, ks, q0);
        a2 = vmla_lane<2>(a2, ks, q0); a3 = vmla_lane<3>(a3, ks, q0);
        a4 = vmla_lane<0>(a4, ks, q1); a5 = vmla_lane<1>(a5, ks, q1);
    }
    vstore(out + 0 * 8, a0); vstore(out + 1 * 8, a1); vstore(out + 2 * 8, a2);
    vstore(out + 3 * 8, a3); vstore(out + 4 * 8, a4); vstore(out + 5 * 8, a5);
}
template <> void scores_pass<10>(const int16_t *q, const int16_t *k, int v, float *out) {
    V a0 = vzero(), a1 = a0, a2 = a0, a3 = a0, a4 = a0, a5 = a0, a6 = a0, a7 = a0, a8 = a0, a9 = a0;
    for (int p = 0; p < TT_D; p++) {
        TT_PF(k + (p + 20) * 10); TT_PF(q + (p + 20) * 10);         // 20 字节/迭代，提前约 6 行
        const V ks = Row<10>::seg(k + p * 10, v);
        const V q0 = vcvt4(q + p * 10), q1 = vcvt4(q + p * 10 + 4), q2 = vcvt2(q + p * 10 + 8);
        a0 = vmla_lane<0>(a0, ks, q0); a1 = vmla_lane<1>(a1, ks, q0);
        a2 = vmla_lane<2>(a2, ks, q0); a3 = vmla_lane<3>(a3, ks, q0);
        a4 = vmla_lane<0>(a4, ks, q1); a5 = vmla_lane<1>(a5, ks, q1);
        a6 = vmla_lane<2>(a6, ks, q1); a7 = vmla_lane<3>(a7, ks, q1);
        a8 = vmla_lane<0>(a8, ks, q2); a9 = vmla_lane<1>(a9, ks, q2);
    }
    vstore(out + 0 * 12, a0); vstore(out + 1 * 12, a1); vstore(out + 2 * 12, a2); vstore(out + 3 * 12, a3);
    vstore(out + 4 * 12, a4); vstore(out + 5 * 12, a5); vstore(out + 6 * 12, a6); vstore(out + 7 * 12, a7);
    vstore(out + 8 * 12, a8); vstore(out + 9 * 12, a9);
}

template <int NN>
static void scores_t(const int16_t *q, const int16_t *k, tt_real attn[TT_NMAX][TT_NMAX]) {
    enum { KV = Row<NN>::KV, KV4 = KV * 4 };
    static_assert(NN % 4 == 2, "row loader assumes NN = 6 or 10");
    float s[NN * KV4];                                              // s[n*KV4 + c]
    for (int v = 0; v < KV; v++) scores_pass<NN>(q, k, v, s + 4 * v);
    const float k2 = 1.0f / ((float)TT_SCALE * (float)TT_SCALE);    // q、k 都是 Q3.12 整数值
    for (int n = 0; n < NN; n++) {
        const float *sn = s + n * KV4;
        float mx = sn[0];
        for (int c = 1; c < NN; c++) if (sn[c] > mx) mx = sn[c];
        float sum = 0;
        for (int c = 0; c < NN; c++) { attn[n][c] = expf((sn[c] - mx) * k2); sum += attn[n][c]; }
        for (int c = 0; c < NN; c++) attn[n][c] /= sum;
    }
}

void tt_scores(const int16_t *q, const int16_t *k, int N, tt_real attn[TT_NMAX][TT_NMAX]) {
    if (N == 6) scores_t<6>(q, k, attn);
    else if (N == 10) scores_t<10>(q, k, attn);
}

// x = quant(xn + ctx)：xn2 = normalize(xn + ctx) 的残差加在归一化后的 xn 上（原代码 x 已被 normalize 覆盖）。
// ctx_flat 按内存序直接重解释为 (p,n) 块（原代码的 reshape 语义），所以 ctx 的第 n 段与 xn 的第 n 段扁平相加。
// 第 n 段第 j 列的扁平下标 i = n*D + j，其 token = i % N，所以每段的车道相位随 n 变（N=6：2646%6=0，相位只随 j；N=10：2646%10=6）。
// 每 4 个 j 一组：把 NN 个 v 段各取 4 个转成 float（反量化在此合并），对每个 n 累加 NN 项后量化写回 x。c 升序。
// 系数 a[n][·] 以向量装载、用车道立即数取；v 段用具名变量（数组会被 GCC 9 放到栈上）。
template <int NN> static void ctx_group(int16_t *x, int j, const int16_t *v, const float *a, const Norm<NN> &nm);
template <> inline void ctx_group<6>(int16_t *x, int j, const int16_t *v, const float *a, const Norm<6> &nm) {
    if ((j & 8) == 0) {                                              // 每 16 列（一行）预取一次，提前 128 字节
#pragma GCC unroll 10
        for (int c = 0; c < 6; c++) TT_PF(v + c * TT_D + j + 64);
#pragma GCC unroll 10
        for (int n = 0; n < 6; n++) TT_PF(x + n * TT_D + j + 64);
    }
    // A9 的 NEON 顺序发射：一条链停住，后面的独立指令也发不出去，所以要让独立指令在源码里交错（GCC 基本保持源码顺序）。
    // 但 q 寄存器只有 16 个：6 个 v 常驻 6 个，剩下的只够两个 n 同时算。每个 n 的 6 项乘加再拆成两条 3 项链（顺序变了，
    // 舍入随之变；主机回归重验），一次 4 条独立链，寄存器 6 v + 4 累加 + 4 系数 = 14。
    const int f0 = j % Norm<6>::P;
    const V v0 = vcvt4(v + j), v1 = vcvt4(v + TT_D + j), v2 = vcvt4(v + 2 * TT_D + j);
    const V v3 = vcvt4(v + 3 * TT_D + j), v4 = vcvt4(v + 4 * TT_D + j), v5 = vcvt4(v + 5 * TT_D + j);
#define TT_CTX6_PAIR(n0, n1) { \
        int16_t *xp = x + n0 * TT_D + j, *xq = x + n1 * TT_D + j; \
        const VH hp = vldh(xp), hq = vldh(xq); \
        const V ap0 = vload(a + n0 * 8), ap1 = vload(a + n0 * 8 + 4), aq0 = vload(a + n1 * 8), aq1 = vload(a + n1 * 8 + 4); \
        V p0 = vmla(vload(nm.pb + f0 + nm.off[n0]), vcvth(hp), vload(nm.pa + f0 + nm.off[n0])); \
        V q0 = vmla(vload(nm.pb + f0 + nm.off[n1]), vcvth(hq), vload(nm.pa + f0 + nm.off[n1])); \
        V p1 = vmul(v3, vdupl<3>(ap0)), q1 = vmul(v3, vdupl<3>(aq0)); \
        p0 = vmla_lane<0>(p0, v0, ap0); q0 = vmla_lane<0>(q0, v0, aq0); p1 = vmla_lane<0>(p1, v4, ap1); q1 = vmla_lane<0>(q1, v4, aq1); \
        p0 = vmla_lane<1>(p0, v1, ap0); q0 = vmla_lane<1>(q0, v1, aq0); p1 = vmla_lane<1>(p1, v5, ap1); q1 = vmla_lane<1>(q1, v5, aq1); \
        p0 = vmla_lane<2>(p0, v2, ap0); q0 = vmla_lane<2>(q0, v2, aq0); \
        p0 = vadd(p0, p1); q0 = vadd(q0, q1); \
        p0 = vq_a(p0); q0 = vq_a(q0); \
        const VI ip = vq_b(p0), iq = vq_b(q0); \
        vq_c(ip, xp); vq_c(iq, xq); }
    TT_CTX6_PAIR(0, 1) TT_CTX6_PAIR(2, 3) TT_CTX6_PAIR(4, 5)
#undef TT_CTX6_PAIR
}
template <> inline void ctx_group<10>(int16_t *x, int j, const int16_t *v, const float *a, const Norm<10> &nm) {
    if ((j & 8) == 0) {
#pragma GCC unroll 10
        for (int c = 0; c < 10; c++) TT_PF(v + c * TT_D + j + 64);
#pragma GCC unroll 10
        for (int n = 0; n < 10; n++) TT_PF(x + n * TT_D + j + 64);
    }
    const V v0 = vcvt4(v + 0 * TT_D + j), v1 = vcvt4(v + 1 * TT_D + j), v2 = vcvt4(v + 2 * TT_D + j);
    const V v3 = vcvt4(v + 3 * TT_D + j), v4 = vcvt4(v + 4 * TT_D + j), v5 = vcvt4(v + 5 * TT_D + j);
    const V v6 = vcvt4(v + 6 * TT_D + j), v7 = vcvt4(v + 7 * TT_D + j), v8 = vcvt4(v + 8 * TT_D + j);
    const V v9 = vcvt4(v + 9 * TT_D + j);
    const int f0 = j % Norm<10>::P;
    for (int n = 0; n < 10; n++) {
        const V a0 = vload(a + n * 12), a1 = vload(a + n * 12 + 4), a2 = vload(a + n * 12 + 8);
        V o = nm.xn(x, n * TT_D + j, f0 + nm.off[n]);
        o = vmla_lane<0>(o, v0, a0); o = vmla_lane<1>(o, v1, a0); o = vmla_lane<2>(o, v2, a0); o = vmla_lane<3>(o, v3, a0);
        o = vmla_lane<0>(o, v4, a1); o = vmla_lane<1>(o, v5, a1); o = vmla_lane<2>(o, v6, a1); o = vmla_lane<3>(o, v7, a1);
        o = vmla_lane<0>(o, v8, a2); o = vmla_lane<1>(o, v9, a2);
        vquant_vec(o, x + n * TT_D + j);
    }
}

template <int NN>
static void ctx_residual_t(int16_t *x, const tt_real attn[TT_NMAX][TT_NMAX], const int16_t *v, const int32_t *stats) {
    enum { KV4 = Row<NN>::KV * 4 };
    Norm<NN> nm(stats);
    float a[NN * KV4];                                              // a[n*KV4 + c]，尾部补零
    for (int i = 0; i < NN * KV4; i++) a[i] = 0;
    for (int n = 0; n < NN; n++) for (int c = 0; c < NN; c++) a[n * KV4 + c] = attn[n][c] * (1.0f / TT_SCALE);
    int j = 0;
    for (; j + 4 <= TT_D; j += 4) ctx_group<NN>(x, j, v, a, nm);
    for (; j < TT_D; j++)                                           // D = 2646 = 4*661 + 2：最后 2 列
        for (int n = 0; n < NN; n++) {
            float o = nm.xn1(x, n * TT_D + j);
            for (int c = 0; c < NN; c++) { float t = (float)v[c * TT_D + j] * a[n * KV4 + c]; o += t; }
            x[n * TT_D + j] = quant1(o);
        }
}

void tt_ctx_residual(int16_t *x, const tt_real attn[TT_NMAX][TT_NMAX], const int16_t *v, const int32_t *stats, int N) {
    if (N == 6) ctx_residual_t<6>(x, attn, v, stats);
    else if (N == 10) ctx_residual_t<10>(x, attn, v, stats);
}

// x = quant(xn + mlp / 4096)（2 的幂，乘法与除法逐位相同）；扁平扫，每组 P 个元素相位固定
// 一个向量：x = quant(b + x·a + mlp/4096)。a/b 具名向量（数组会被 GCC 9 放到栈上）。
static inline void resid4(int16_t *x, const int16_t *mlp, V a, V b) {
    V o = vmla(b, vcvt4(x), a);
    o = vmla_n(o, vcvt4(mlp), K_DQ);
    vquant_vec(o, x);
}
template <int NN> static void mlp_residual_t(int16_t *x, const int16_t *mlp, const int32_t *stats);
// N=6：每次 24 个元素 = 6 个向量，6 条链按阶段交错（见 ctx_group<6> 的说明）；1323 个周期是奇数，最后一个周期单独收尾
template <> void mlp_residual_t<6>(int16_t *x, const int16_t *mlp, const int32_t *stats) {
    enum { P = 12, DN = TT_D * 6, DN2 = DN - DN % (2 * P) };
    static_assert(DN % P == 0, "block must be a whole number of lane periods");
    Norm<6> nm(stats);
    const float kd[4] = { K_DQ, K_DQ, K_DQ, K_DQ };
    const V kq = vload(kd);
    int i = 0;
    for (; i < DN2; i += 2 * P) {                                     // a/b 系数按需从 L1 装载（常驻会把 q 寄存器用光）
        TT_PF(mlp + i + 64); TT_PF(x + i + 64);
        int16_t *p0 = x + i, *p1 = p0 + 4, *p2 = p0 + 8, *p3 = p0 + 12, *p4 = p0 + 16, *p5 = p0 + 20;
        const int16_t *m0 = mlp + i;
        const VH hx0 = vldh(p0), hx1 = vldh(p1), hx2 = vldh(p2), hx3 = vldh(p3), hx4 = vldh(p4), hx5 = vldh(p5);
        V o0 = vcvth(hx0), o1 = vcvth(hx1), o2 = vcvth(hx2), o3 = vcvth(hx3), o4 = vcvth(hx4), o5 = vcvth(hx5);
        o0 = vmla(vload(nm.pb), o0, vload(nm.pa)); o1 = vmla(vload(nm.pb + 4), o1, vload(nm.pa + 4)); o2 = vmla(vload(nm.pb + 8), o2, vload(nm.pa + 8));
        o3 = vmla(vload(nm.pb), o3, vload(nm.pa)); o4 = vmla(vload(nm.pb + 4), o4, vload(nm.pa + 4)); o5 = vmla(vload(nm.pb + 8), o5, vload(nm.pa + 8));
        const VH hm0 = vldh(m0), hm1 = vldh(m0 + 4), hm2 = vldh(m0 + 8), hm3 = vldh(m0 + 12), hm4 = vldh(m0 + 16), hm5 = vldh(m0 + 20);
        const V f0 = vcvth(hm0), f1 = vcvth(hm1), f2 = vcvth(hm2), f3 = vcvth(hm3), f4 = vcvth(hm4), f5 = vcvth(hm5);
        o0 = vmla(o0, f0, kq); o1 = vmla(o1, f1, kq); o2 = vmla(o2, f2, kq);
        o3 = vmla(o3, f3, kq); o4 = vmla(o4, f4, kq); o5 = vmla(o5, f5, kq);
        o0 = vq_a(o0); o1 = vq_a(o1); o2 = vq_a(o2); o3 = vq_a(o3); o4 = vq_a(o4); o5 = vq_a(o5);
        const VI i0 = vq_b(o0), i1 = vq_b(o1), i2 = vq_b(o2), i3 = vq_b(o3), i4 = vq_b(o4), i5 = vq_b(o5);
        vq_c(i0, p0); vq_c(i1, p1); vq_c(i2, p2); vq_c(i3, p3); vq_c(i4, p4); vq_c(i5, p5);
    }
    for (; i < DN; i += P) {
        resid4(x + i, mlp + i, vload(nm.pa), vload(nm.pb)); resid4(x + i + 4, mlp + i + 4, vload(nm.pa + 4), vload(nm.pb + 4));
        resid4(x + i + 8, mlp + i + 8, vload(nm.pa + 8), vload(nm.pb + 8));
    }
}
template <> void mlp_residual_t<10>(int16_t *x, const int16_t *mlp, const int32_t *stats) {
    enum { P = 20, DN = TT_D * 10 };
    static_assert(DN % P == 0, "block must be a whole number of lane periods");
    Norm<10> nm(stats);
    const V a0 = vload(nm.pa), a1 = vload(nm.pa + 4), a2 = vload(nm.pa + 8), a3 = vload(nm.pa + 12), a4 = vload(nm.pa + 16);
    const V b0 = vload(nm.pb), b1 = vload(nm.pb + 4), b2 = vload(nm.pb + 8), b3 = vload(nm.pb + 12), b4 = vload(nm.pb + 16);
    for (int i = 0; i < DN; i += P) {
        TT_PF(mlp + i + 64); TT_PF(x + i + 64);
        resid4(x + i,      mlp + i,      a0, b0); resid4(x + i + 4,  mlp + i + 4,  a1, b1); resid4(x + i + 8, mlp + i + 8, a2, b2);
        resid4(x + i + 12, mlp + i + 12, a3, b3); resid4(x + i + 16, mlp + i + 16, a4, b4);
    }
}
void tt_mlp_residual(int16_t *x, const int16_t *mlp, const int32_t *stats, int N) {
    if (N == 6) mlp_residual_t<6>(x, mlp, stats);
    else if (N == 10) mlp_residual_t<10>(x, mlp, stats);
}

// ---------------------------------------------------------------- 一层，拆成 PL 调用之间的两段 PS 工作
// 单 patch：PL qkv → mid → PL mlp → post_mlp。双 patch 流水（tt_forward_pair）用同样两段交错调度，
// 每个 patch 的运算顺序与单 patch 完全相同，结果逐位一致。
struct Tk {                                                          // 分段计时：每段耗时同时记进 tt_prof / 层 / 层总计
    unsigned long long last; int layer;
    explicit Tk(int l) : last(tt_clock ? tt_clock() : 0), layer(l) {}
    void tick(int slot) {
        if (!tt_clock) return;
        const unsigned long long t = tt_clock(), dt = t - last;
        tt_prof[slot] += dt; tt_layer_prof[layer][slot] += dt; tt_layer_ticks[layer] += dt; last = t;
    }
};
static inline const int16_t *layer_w(const TTNet &net, int layer) { return net.weights + (size_t)layer * 4 * TT_NF; }

static void start_qkv(const TTNet &net, TTWork &wk, int layer) {
    Tk tk(layer);
    const int16_t *wq = layer_w(net, layer);
    tt_hw_proj_start(wk.x, wk.out_q, wk.out_k, wk.out_v, wk.stats, wq, wq + TT_NF, wq + 2 * TT_NF, net.N, 3);
    tk.tick(TT_PROF_PL_QKV);
}
static void stage_mid(const TTNet &net, TTWork &wk, int layer) {       // x = quant(xn + attn(q,k)·v)
    Tk tk(layer);
    tt_real attn[TT_NMAX][TT_NMAX];
    tt_scores(wk.out_q, wk.out_k, net.N, attn);                 tk.tick(TT_PROF_SCORES);
    tt_ctx_residual(wk.x, attn, wk.out_v, wk.stats, net.N);     tk.tick(TT_PROF_CTX);
}
static void start_mlp(const TTNet &net, TTWork &wk, int layer) {
    Tk tk(layer);
    const int16_t *wm = layer_w(net, layer) + 3 * TT_NF;
    tt_hw_proj_start(wk.x, wk.out_q, wk.out_k, wk.out_v, wk.stats, wm, wm, wm, net.N, 1);
    tk.tick(TT_PROF_PL_MLP);
}
static void stage_post_mlp(const TTNet &net, TTWork &wk, int layer) {  // x = quant(xn + mlp)
    Tk tk(layer);
    tt_mlp_residual(wk.x, wk.out_q, wk.stats, net.N);           tk.tick(TT_PROF_RESID);
}
static void wait_pl(int layer, int slot) { Tk tk(layer); tt_hw_proj_wait(); tk.tick(slot); }

void tt_layer(const TTNet &net, TTWork &wk, int layer) {
    start_qkv(net, wk, layer);  wait_pl(layer, TT_PROF_PL_QKV);
    stage_mid(net, wk, layer);
    start_mlp(net, wk, layer);  wait_pl(layer, TT_PROF_PL_MLP);
    stage_post_mlp(net, wk, layer);
}

// 取 token 1（不是 cls），flatten 顺序 (i1,i2,j) = p；x 反量化后与分类权重内积
static int head(const TTNet &net, const TTWork &wk, tt_real *logits) {
    static float xf[TT_D];                                            // token 1 反量化一次，9 个类共用
    for (int p = 0; p < TT_D; p++) xf[p] = (float)wk.x[p * net.N + 1] * K_DQ;
    int best = 0;
    for (int c = 0; c < TT_CLASSES; c++) {
        float s = net.cls_b[c];
        for (int p = 0; p < TT_D; p++) { float t = net.cls_w[c * TT_D + p] * xf[p]; s += t; }
        logits[c] = s;
        if (s > logits[best]) best = c;
    }
    return best;
}

int tt_forward(const TTNet &net, TTWork &wk, const float *patch, tt_real *logits) {
    if ((net.N != 6 && net.N != 10) || net.seq != net.N - 1) return -1;
    tt_embed(net, patch, wk.x);
    for (int l = 0; l < TT_LAYERS; l++) tt_layer(net, wk, l);
    return head(net, wk, logits);
}

// 双 patch 流水。PL 阶段编号 s = 0..23：偶数 = 第 s/2 层 qkv，奇数 = 第 s/2 层 mlp。
// 循环不变量：进入第 s 轮时 PL 正在算 A 的阶段 s，B 的阶段 s 已准备好（x 就绪）。
//   等 A(s) → 启动 B(s) → PS 做 A 的下一段（A(s+1) 的准备，或收尾）→ 等 B(s) → 启动 A(s+1) → PS 做 B 的下一段。
// PS 段与 PL 段重叠：PL 两栏计启动/cache 开销与未被掩盖的等待，不是完整硬件运行时间。
static void start_stage(const TTNet &net, TTWork &wk, int s) {
    if (s % 2 == 0) start_qkv(net, wk, s / 2); else start_mlp(net, wk, s / 2);
}
// PL 阶段 s 完成后该 patch 的 PS 工作；s = 23 之后是收尾。返回 argmax（仅收尾时有效）
static int after_stage(const TTNet &net, TTWork &wk, int s, tt_real *logits) {
    const int l = s / 2;
    if (s % 2 == 0) { stage_mid(net, wk, l); return -1; }
    stage_post_mlp(net, wk, l);
    if (l + 1 < TT_LAYERS) return -1;
    return head(net, wk, logits);
}

void tt_forward_pair(const TTNet &net, TTWork &wa, TTWork &wb, const float *pa, const float *pb,
                     tt_real *la, tt_real *lb, int *best_a, int *best_b) {
    *best_a = *best_b = -1;
    if ((net.N != 6 && net.N != 10) || net.seq != net.N - 1) return;
    enum { STAGES = 2 * TT_LAYERS };
    tt_embed(net, pa, wa.x); start_stage(net, wa, 0);
    tt_embed(net, pb, wb.x);
    for (int s = 0; s < STAGES; s++) {
        const int slot = (s % 2 == 0) ? TT_PROF_PL_QKV : TT_PROF_PL_MLP;
        wait_pl(s / 2, slot);
        start_stage(net, wb, s);
        *best_a = after_stage(net, wa, s, la);
        wait_pl(s / 2, slot);
        if (s + 1 < STAGES) start_stage(net, wa, s + 1);
        *best_b = after_stage(net, wb, s, lb);
    }
}

// ---------------------------------------------------------------- 板上取 patch（复刻 preprocess.patch_tensor）
// region: 预处理后的 (rw, rw, 270) float32 HWC；窗左上角 (i, j)（region 已含 3 像素零填充，所以像素 (r,c) 的窗左上角就是 (r,c)）。
// 输出 (270, 7, 7) CHW 内存序，再做 patch 级归一化：(p - mean) / std，std 无偏（ddof=1），全部 float32。
void tt_patch_extract(const float *region, int rw, int i, int j, float *patch) {
    TTMeasureScope extraction(TT_MEASURE_EXTRACT);
    enum { PW = 270 * TT_W * TT_W };
    for (int h = 0; h < TT_W; h++)
        for (int w = 0; w < TT_W; w++) {
            const float *px = region + ((size_t)(i + h) * rw + (j + w)) * 270;
            float *o = patch + h * TT_W + w;
            for (int c = 0; c < 270; c++) o[c * TT_W * TT_W] = px[c];
        }
    extraction.finish();
    TTMeasureScope normalization(TT_MEASURE_NORMALIZE);
    V a0 = vzero(), a1 = vzero();
    int t = 0;
    for (; t + 8 <= PW; t += 8) { a0 = vadd(a0, vload(patch + t)); a1 = vadd(a1, vload(patch + t + 4)); }
    float lane[4]; vstore(lane, vadd(a0, a1));
    float s = (lane[0] + lane[1]) + (lane[2] + lane[3]);
    for (; t < PW; t++) s += patch[t];
    const float mean = s / (float)PW;
    a0 = vzero(); a1 = vzero();
    float pat[4] = { mean, mean, mean, mean };
    const V mv = vload(pat);
    for (t = 0; t + 8 <= PW; t += 8) {
        V d0 = vsub(vload(patch + t), mv), d1 = vsub(vload(patch + t + 4), mv);
        a0 = vmla(a0, d0, d0); a1 = vmla(a1, d1, d1);
    }
    vstore(lane, vadd(a0, a1));
    float ss = (lane[0] + lane[1]) + (lane[2] + lane[3]);
    for (; t < PW; t++) { float d = patch[t] - mean; ss += d * d; }
    const float inv = 1.0f / sqrtf(ss / (float)(PW - 1));
    pat[0] = pat[1] = pat[2] = pat[3] = inv;
    const V iv = vload(pat);
    for (t = 0; t + 4 <= PW; t += 4) vstore(patch + t, vmul(vsub(vload(patch + t), mv), iv));
    for (; t < PW; t++) patch[t] = (patch[t] - mean) * inv;
}
