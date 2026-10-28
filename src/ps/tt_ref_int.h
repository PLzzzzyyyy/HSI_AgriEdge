// PL 算子 tucker_proj v1.4 的逐位整数参考：token 归一化（量化到 Q3.12）+ Tucker 投影。
// 被 tt_hw_sim.cpp（主机 / 板上纯 PS 后端）、sim/hls_tb（IP 期望值）和主机测试共用；HLS 源码实现完全相同的算术。
// 只用 long long 与 float，不依赖 ap_int。改任何一处舍入都要同步改 src/hls/tucker_proj.cpp 并重跑 cosim。
//
// 归一化（每个 token n，遍历 p；x、q 是 Q3.12，布局 x[p*N+n]）：
//   S1 = Σx, Sxx = Σx²（整数精确，与求和顺序无关）    var_num = D·Sxx − S1² = D(D−1)·无偏方差（2^-24 单位，< 2^54）
//   mean_q24 = (S1 << 12) / D（向零截断，|·| ≤ 2^27）   inv = 10835968.0f / sqrtf((float)var_num)，clamp ≤ 127（零方差也落到这里）
//   inv_q24 = trunc(inv · 2^24)（< 2^31）                d = (x << 12) − mean_q24（|d| < 2^28）
//   q = sat16((d · inv_q24 + 2^35) >> 36)                stats[2n] = mean_q24, stats[2n+1] = inv_q24（int32）
// PS 残差用 stats 复原归一化值：xn = ((float)x · 2^-12 − (float)mean_q24 · 2^-24) · ((float)inv_q24 · 2^-24)。
// 2026-09-19 主机 4096 像素实验（float stats 版）：与 float32 归一化只差 ±1 LSB（0.07%），标签 4096/4096，max|dlogit| 0.0086。
#ifndef TT_REF_INT_H
#define TT_REF_INT_H
#include <stdint.h>
#include <math.h>

namespace tt_ref {
enum { W = 7, J = 54, D = W * W * J, NF = 2 * W * W + J * J, DF = 12, WF = 14, MF = 14, MB = 18 };
static const float INV_C = 10835968.0f;   // float32(sqrt(2646 * 2645) * 4096)

static inline void normalize(const int16_t *x, int16_t *q, int32_t *stats, int N) {
    for (int n = 0; n < N; n++) {
        long long s1 = 0, sxx = 0;
        for (int p = 0; p < D; p++) { const long long v = x[p * N + n]; s1 += v; sxx += v * v; }
        const long long var_num = (long long)D * sxx - s1 * s1;
        const long long mean_q24 = (s1 << 12) / D;
        float inv = INV_C / sqrtf((float)var_num);
        if (!(inv <= 127.0f)) inv = 127.0f;
        const int32_t inv_q24 = (int32_t)(inv * 16777216.0f);
        stats[2 * n] = (int32_t)mean_q24;
        stats[2 * n + 1] = inv_q24;
        for (int p = 0; p < D; p++) {
            const long long d = ((long long)x[p * N + n] << 12) - mean_q24;
            long long r = (d * inv_q24 + (1LL << 35)) >> 36;      // 算术右移 = floor：四舍五入（.5 向上）
            if (r > 32767) r = 32767;
            if (r < -32768) r = -32768;
            q[p * N + n] = (int16_t)r;
        }
    }
}

static inline long long rnd_sat(long long acc, int shift, int bits) {
    const long long half = 1LL << (shift - 1);
    long long v = (acc + half) >> shift;                          // floor 除法
    const long long lim = 1LL << (bits - 1);
    if (v < -lim) v = -lim;
    if (v > lim - 1) v = lim - 1;
    return v;
}

// 一个投影：与 src/hls/tucker_proj.cpp、model/quant.py::tucker_proj_int 逐位一致
static inline void project(const int16_t *in, int16_t *out, const int16_t *w, int N) {
    const int16_t *m1 = w, *m2 = w + W * W, *m3 = w + 2 * W * W;
    static long long t1[W][W][J], t2[W][W][J];
    for (int n = 0; n < N; n++) {
        for (int a = 0; a < W; a++)                                // 模 1：定标 DF+WF → MF
            for (int i2 = 0; i2 < W; i2++)
                for (int j = 0; j < J; j++) {
                    long long acc = 0;
                    for (int i1 = 0; i1 < W; i1++) acc += (long long)m1[a * W + i1] * in[((i1 * W + i2) * J + j) * N + n];
                    t1[a][i2][j] = rnd_sat(acc, DF + WF - MF, MB);
                }
        for (int a = 0; a < W; a++)                                // 模 2：定标 MF+WF → MF
            for (int b = 0; b < W; b++)
                for (int j = 0; j < J; j++) {
                    long long acc = 0;
                    for (int i2 = 0; i2 < W; i2++) acc += (long long)m2[b * W + i2] * t1[a][i2][j];
                    t2[a][b][j] = rnd_sat(acc, WF, MB);
                }
        for (int a = 0; a < W; a++)                                // 模 3：定标 MF+WF → DF
            for (int b = 0; b < W; b++)
                for (int c = 0; c < J; c++) {
                    long long acc = 0;
                    for (int j = 0; j < J; j++) acc += (long long)m3[c * J + j] * t2[a][b][j];
                    out[((a * W + b) * J + c) * N + n] = (int16_t)rnd_sat(acc, MF + WF - DF, 16);
                }
    }
}
}  // namespace tt_ref

#endif
