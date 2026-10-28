// engine_ref.cpp —— 整网引擎 M3 整数参考的 C 版（int16 版 W16A18、int8 版 W8A8，按权重包头的位宽选），与 model/engine_ref.py 逐位一致（docs/engine_arch.md §3、§3.7）。
// 只用 long long 与 float（每 token / patch 一次 sqrtf + 除法），不依赖 ap_int；HLS 引擎（D4 / D5）按同样的算术写。
//
// 用法：engine_ref.exe <golden_dir> [batch_dir...]
//   <golden_dir>/weights_engine.bin、cube_win_i16.bin、a/（入口 A）、b/（入口 B）：逐文件逐位比对，打印 PASS/FAIL
//   <golden_dir>/batch_<scene>/：weights_engine.bin、wins_i16.bin (n,7,7,272)、expect_logits_i32.bin (n,32)、expect_class_u32.bin (n)
//   int16 版黄金 sim/golden/n6_engine，int8 版 sim/golden/n6_engine_i8
// 编译：g++ -O2 -std=c++11 -ffp-contract=off sim/host/engine_ref.cpp -o build/host/engine_ref.exe
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "../../src/hls/tt_engine_regs.h"

typedef long long i64;
enum { W = 7, J = 54, D = 2646, N = 6, L = 12, NF = 3014, PN = 13230 };
static int DF, DB, MF, MB;                // set_num：int16 版 12 / 18 / 14 / 18，int8 版 4 / 8 / 4 / 8
static const int FRONT_S = 43, FRONT_T = FRONT_S - 24;
static const int BFP_S = 48, BFP_T = BFP_S - 24;
static const i64 GMAX = (1LL << 25) - 1;
static const i64 LOG2E_Q24 = 24204406, EXP_CUT = 25LL << 24;

static i64 T_HI[256], T_LO[256];
static float INV_C, GC, BFP_GC;

static inline i64 sat(i64 v, int bits) {
    const i64 lim = 1LL << (bits - 1);
    return v < -lim ? -lim : (v > lim - 1 ? lim - 1 : v);
}
static inline i64 rnd(i64 v, int s) { return s > 0 ? (v + (1LL << (s - 1))) >> s : v * (1LL << -s); }

static void init_consts() {
    for (int a = 0; a < 256; a++) T_HI[a] = llround(pow(2.0, -a / 256.0) * 16777216.0);
    for (int b = 0; b < 256; b++) T_LO[b] = llround(pow(2.0, -b / 65536.0) * 16777216.0);
    GC = (float)(sqrt((PN - 1.0) / PN) * ldexp(1.0, FRONT_S));
    BFP_GC = (float)(sqrt((PN - 1.0) / PN) * ldexp(1.0, BFP_S));
}

static void set_num(int num) {
    if (num == 16) { DF = 12; DB = 18; MF = 14; MB = 18; }
    else { DF = 4; DB = 8; MF = 4; MB = 8; }
    INV_C = (float)(sqrt((double)D * (D - 1)) * ldexp(1.0, DF));
}

static inline i64 exp_q24(i64 d) {                       // exp(−d)，d ≥ 0 Q.24 → Q0.24
    if (d >= EXP_CUT) return 0;
    const i64 u = d * LOG2E_Q24;
    const int i = (int)(u >> 48);
    const int f = (int)((u >> 32) & 0xFFFF);
    return ((T_HI[f >> 8] * T_LO[f & 255] + (1LL << 23)) >> 24) >> i;
}

// ---------------------------------------------------------------- 权重包
struct Pkg {
    int ncls, num;
    std::vector<i64> emb;                 // D*N
    i64 hb[24]; int he[24];
    std::vector<i64> hw;                  // ncls*D
    std::vector<int16_t> proj;            // L*4*NF（int8 版符号扩展）
    std::vector<int> pe;                  // L*4*3，每个 M1/M2/M3 的小数位（int16 版全为 14，int8 版取包内指数表）
};

static std::vector<uint8_t> read_file(const std::string &p) {
    FILE *f = fopen(p.c_str(), "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", p.c_str()); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    std::vector<uint8_t> b(n);
    if (fread(b.data(), 1, n, f) != (size_t)n) exit(2);
    fclose(f);
    return b;
}

static Pkg load_pkg(const std::string &p) {
    std::vector<uint8_t> b = read_file(p);
    Pkg k;
    uint32_t h[4]; memcpy(h, b.data(), 16);
    const size_t want = h[3] == 16 ? TT_ENGINE_WPKG16_BYTES : TT_ENGINE_WPKG8_BYTES;
    if (h[0] != TT_ENGINE_WPKG_MAGIC || (h[3] != 16 && h[3] != 8) || b.size() != want) { fprintf(stderr, "bad pkg %s\n", p.c_str()); exit(2); }
    k.ncls = (int)h[2]; k.num = (int)h[3];
    for (int c = 0; c < 24; c++) { k.he[c] = (int8_t)b[32 + c]; int32_t v; memcpy(&v, &b[TT_ENGINE_WPKG_HBIAS + 4 * c], 4); k.hb[c] = v; }
    k.emb.resize(D * N);
    for (int i = 0; i < D * N; i++) { int32_t v; memcpy(&v, &b[TT_ENGINE_WPKG_EMB + 4 * i], 4); k.emb[i] = v; }
    k.hw.resize(k.ncls * D);
    for (int c = 0; c < k.ncls; c++)
        for (int p = 0; p < D; p++) { int16_t v; memcpy(&v, &b[TT_ENGINE_WPKG_HW + c * TT_ENGINE_WPKG_HW_ROW + 2 * p], 2); k.hw[c * D + p] = v; }
    k.proj.resize(L * 4 * NF);
    k.pe.assign(L * 4 * 3, 14);
    if (k.num == 16) memcpy(k.proj.data(), &b[TT_ENGINE_WPKG_PROJ], TT_ENGINE_WPROJ16_BYTES);
    else {                                // int8 因子 L*4*NF B，随后指数表 L*4*3 B（{e1, e2, e3}）
        for (int i = 0; i < L * 4 * NF; i++) k.proj[i] = (int8_t)b[TT_ENGINE_WPKG_PROJ + i];
        for (int i = 0; i < L * 4 * 3; i++) k.pe[i] = (int8_t)b[TT_ENGINE_WPKG_PROJ + L * 4 * NF + i];
    }
    return k;
}

// ---------------------------------------------------------------- 算子（块 x[p*N+n]）
static void normalize(const i64 *x, i64 *q, i64 *stats) {
    const int sh = 24 - DF;
    for (int n = 0; n < N; n++) {
        i64 s1 = 0, sxx = 0;
        for (int p = 0; p < D; p++) { const i64 v = x[p * N + n]; s1 += v; sxx += v * v; }
        const i64 var = (i64)D * sxx - s1 * s1;
        const i64 mean = (s1 * (1LL << sh)) / D;
        float inv = INV_C / sqrtf((float)var);
        if (!(inv <= 127.0f)) inv = 127.0f;
        const i64 inv_q24 = (i64)(inv * 16777216.0f);
        stats[2 * n] = mean; stats[2 * n + 1] = inv_q24;
        for (int p = 0; p < D; p++) q[p * N + n] = sat(rnd((x[p * N + n] * (1LL << sh) - mean) * inv_q24, 48 - DF), DB);
    }
}

static void project(const i64 *in, i64 *out, const int16_t *w, const int *e) {
    const int16_t *m1 = w, *m2 = w + W * W, *m3 = w + 2 * W * W;
    static i64 t1[W][W][J], t2[W][W][J];
    for (int n = 0; n < N; n++) {
        for (int a = 0; a < W; a++)
            for (int i2 = 0; i2 < W; i2++)
                for (int j = 0; j < J; j++) {
                    i64 acc = 0;
                    for (int i1 = 0; i1 < W; i1++) acc += (i64)m1[a * W + i1] * in[((i1 * W + i2) * J + j) * N + n];
                    t1[a][i2][j] = sat(rnd(acc, DF + e[0] - MF), MB);
                }
        for (int a = 0; a < W; a++)
            for (int b = 0; b < W; b++)
                for (int j = 0; j < J; j++) {
                    i64 acc = 0;
                    for (int i2 = 0; i2 < W; i2++) acc += (i64)m2[b * W + i2] * t1[a][i2][j];
                    t2[a][b][j] = sat(rnd(acc, e[1]), MB);
                }
        for (int a = 0; a < W; a++)
            for (int b = 0; b < W; b++)
                for (int c = 0; c < J; c++) {
                    i64 acc = 0;
                    for (int j = 0; j < J; j++) acc += (i64)m3[c * J + j] * t2[a][b][j];
                    out[((a * W + b) * J + c) * N + n] = sat(rnd(acc, MF + e[2] - DF), DB);
                }
    }
}

static void attention(const i64 *q, const i64 *k, const i64 *v, i64 *ctx, i64 *s, i64 *attn) {
    for (int n = 0; n < N; n++)
        for (int c = 0; c < N; c++) {
            i64 acc = 0;
            for (int p = 0; p < D; p++) acc += q[p * N + n] * k[p * N + c];
            s[n * N + c] = acc;
        }
    for (int n = 0; n < N; n++) {
        i64 m = s[n * N], e[N], S = 0;
        for (int c = 1; c < N; c++) if (s[n * N + c] > m) m = s[n * N + c];
        for (int c = 0; c < N; c++) { e[c] = exp_q24((m - s[n * N + c]) * (1LL << (24 - 2 * DF))); S += e[c]; }
        const i64 r = (1LL << 47) / S;
        for (int c = 0; c < N; c++) attn[n * N + c] = (e[c] * r + (1LL << 22)) >> 23;
    }
    // V 按内存序切块：ctx_flat[s*D + i] = Σ_c attn[s][c] · v_flat[c*D + i]
    for (int sgm = 0; sgm < N; sgm++)
        for (int i = 0; i < D; i++) {
            i64 acc = 0;
            for (int c = 0; c < N; c++) acc += attn[sgm * N + c] * v[c * D + i];
            ctx[sgm * D + i] = sat(rnd(acc, 24), DB);
        }
}

struct Out { i64 logits[24]; int label; int conf; };

static void head(const Pkg &k, const i64 *x, Out &o) {
    i64 best = 0;
    for (int c = 0; c < k.ncls; c++) {
        i64 acc = 0;
        for (int p = 0; p < D; p++) acc += k.hw[c * D + p] * x[p * N + 1];
        const int r = DF + k.he[c] - 16;
        if (r < 1) { fprintf(stderr, "head r < 1\n"); exit(3); }
        o.logits[c] = rnd(acc, r) + k.hb[c];
        if (c == 0 || o.logits[c] > best) { best = o.logits[c]; o.label = c; }
    }
    i64 S = 0;
    for (int c = 0; c < k.ncls; c++) S += exp_q24((best - o.logits[c]) * 256);
    const i64 conf = (1LL << 40) / S;
    o.conf = (int)(conf > 0xFFFF ? 0xFFFF : conf);
}

// 立方体窗 (7,7,272) → x_embed；fs = {S1, Sxx, V, g}，xn24 可为空
// bfp（契约 v3）：波段 270 为每条光谱的 2 幂指数，元素按 (e − min e) 右移舍入对齐（engine_ref.py entry_b 同义）；bfp = false 为 v2 整景 k 的对照
static void front(const Pkg &k, const int16_t *win, i64 *x, i64 *fs, i64 *xn24, bool bfp = true) {
    static i64 q[PN];
    i64 s1 = 0, sxx = 0, emin = 1 << 30;
    if (bfp) for (int i = 0; i < 49; i++) if (win[i * 272 + 270] < emin) emin = win[i * 272 + 270];
    for (int c = 0; c < 270; c++)
        for (int h = 0; h < W; h++)
            for (int w = 0; w < W; w++) {
                i64 v = win[(h * W + w) * 272 + c];
                if (bfp) { const int s = (int)(win[(h * W + w) * 272 + 270] - emin); if (s > 0) v = (v + (1LL << (s - 1))) >> s; }
                q[c * 49 + h * 7 + w] = v; s1 += v; sxx += v * v;
            }
    const i64 V = (i64)PN * sxx - s1 * s1;
    float gf = (bfp ? BFP_GC : GC) / sqrtf((float)V);
    if (!(gf <= (float)GMAX)) gf = (float)GMAX;
    const i64 g = (i64)gf;
    const int ft = bfp ? BFP_T : FRONT_T;
    if (fs) { fs[0] = s1; fs[1] = sxx; fs[2] = V; fs[3] = g; }
    const int sh = 24 - DF;
    for (int p = 0; p < D; p++) {
        x[p * N] = sat(rnd(k.emb[p * N], sh), DB);
        for (int n = 1; n < N; n++) {
            const int e = 5 * p + n - 1;
            const i64 xn = ((i64)PN * q[e] - s1) * g >> ft;
            if (xn24) xn24[e] = xn;
            x[p * N + n] = sat(rnd(xn + k.emb[p * N + n], sh), DB);
        }
    }
}

// ---------------------------------------------------------------- 比对
static int n_fail = 0, n_file = 0;
template <class T> static void cmp(const std::string &path, const i64 *v, size_t n) {
    std::vector<uint8_t> b = read_file(path);
    n_file++;
    if (b.size() != n * sizeof(T)) { printf("FAIL size %s\n", path.c_str()); n_fail++; return; }
    const T *g = (const T *)b.data();
    size_t bad = 0, first = 0;
    for (size_t i = 0; i < n; i++) if ((i64)g[i] != v[i]) { if (!bad) first = i; bad++; }
    if (bad) { printf("FAIL %s: %zu/%zu differ, first @%zu ref %lld c %lld\n", path.c_str(), bad, n, first, (i64)g[first], v[first]); n_fail++; }
}

static Out run(const Pkg &k, i64 *x, const std::string &dir) {
    static i64 xn[D * N], q[D * N], kk[D * N], v[D * N], ctx[D * N], xm[D * N], xn2[D * N], m[D * N];
    i64 st1[12], st2[12], s[36], at[36];
    for (int l = 0; l < L; l++) {
        const int16_t *w = &k.proj[l * 4 * NF];
        const int *e = &k.pe[l * 4 * 3];
        normalize(x, xn, st1);
        project(xn, q, w, e); project(xn, kk, w + NF, e + 3); project(xn, v, w + 2 * NF, e + 6);
        attention(q, kk, v, ctx, s, at);
        for (int i = 0; i < D * N; i++) xm[i] = sat(xn[i] + ctx[i], DB);
        normalize(xm, xn2, st2);
        project(xn2, m, w + 3 * NF, e + 9);
        for (int i = 0; i < D * N; i++) x[i] = sat(xn2[i] + m[i], DB);
        if (!dir.empty()) {
            const std::string p = dir + "/L" + std::to_string(l) + "_";
            cmp<int32_t>(p + "xn_q_i4.bin", xn, D * N); cmp<int32_t>(p + "stats_qkv_i4.bin", st1, 12);
            cmp<int32_t>(p + "q_i4.bin", q, D * N); cmp<int32_t>(p + "k_i4.bin", kk, D * N); cmp<int32_t>(p + "v_i4.bin", v, D * N);
            cmp<int64_t>(p + "s_i8.bin", s, 36); cmp<int32_t>(p + "attn_i4.bin", at, 36);
            cmp<int32_t>(p + "x_mid_i4.bin", xm, D * N); cmp<int32_t>(p + "xn2_q_i4.bin", xn2, D * N);
            cmp<int32_t>(p + "stats_mlp_i4.bin", st2, 12); cmp<int32_t>(p + "m_i4.bin", m, D * N); cmp<int32_t>(p + "x_out_i4.bin", x, D * N);
        }
    }
    Out o; memset(&o, 0, sizeof(o));
    head(k, x, o);
    return o;
}

static void check_out(const Pkg &k, const Out &o, const std::string &dir) {
    i64 lg[32] = {0}, cl = ((i64)o.conf << 16) | o.label;
    for (int c = 0; c < k.ncls; c++) lg[c] = o.logits[c];
    cmp<int32_t>(dir + "/logits_q16_i32.bin", lg, 32);
    cmp<uint32_t>(dir + "/class_u32.bin", &cl, 1);
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: engine_ref <golden_dir> [batch_dir...]\n"); return 1; }
    init_consts();
    const std::string g = argv[1];
    static i64 x[D * N];
    Pkg k = load_pkg(g + "/weights_engine.bin");
    set_num(k.num);
    {   // 入口 A：Q3.12 块装载到片上格式（int16 版原值，int8 版舍入到 Q3.4）
        std::vector<uint8_t> b = read_file(g + "/a/x_in_i16.bin");
        const int16_t *xi = (const int16_t *)b.data();
        for (int i = 0; i < D * N; i++) x[i] = sat(rnd(xi[i], 12 - DF), DB);
        cmp<int32_t>(g + "/a/x_embed_i32.bin", x, D * N);
        check_out(k, run(k, x, g + "/a"), g + "/a");
    }
    {   // 入口 B
        std::vector<uint8_t> b = read_file(g + "/cube_win_i16.bin");
        static i64 xn24[PN]; i64 fs[4];
        front(k, (const int16_t *)b.data(), x, fs, xn24);
        cmp<int64_t>(g + "/b/front_s1_sxx_v_g_i64.bin", fs, 4);
        cmp<int32_t>(g + "/b/front_xn24_i32.bin", xn24, PN);
        cmp<int32_t>(g + "/b/x_embed_i32.bin", x, D * N);
        check_out(k, run(k, x, g + "/b"), g + "/b");
    }
    printf("golden %s (num %d): %d files, %d FAIL\n", g.c_str(), k.num, n_file, n_fail);
    for (int a = 2; a < argc; a++) {   // 批：只比 logits 与类别字
        const std::string d = argv[a];
        Pkg kb = load_pkg(d + "/weights_engine.bin");
        set_num(kb.num);
        std::vector<uint8_t> w = read_file(d + "/wins_i16.bin");
        const int n = (int)(w.size() / (49 * 272 * 2));
        std::vector<uint8_t> el = read_file(d + "/expect_logits_i32.bin"), ec = read_file(d + "/expect_class_u32.bin");
        int bad = 0;
        for (int i = 0; i < n; i++) {
            front(kb, (const int16_t *)w.data() + (size_t)i * 49 * 272, x, 0, 0);
            Out o = run(kb, x, "");
            const int32_t *l = (const int32_t *)el.data() + i * 32;
            bool ok = ((const uint32_t *)ec.data())[i] == (((uint32_t)o.conf << 16) | (uint32_t)o.label);
            for (int c = 0; c < kb.ncls; c++) ok = ok && l[c] == o.logits[c];
            bad += !ok;
        }
        printf("batch %s: %d pixels, %d FAIL\n", d.c_str(), n, bad);
        n_fail += bad;
    }
    printf(n_fail ? "RESULT FAIL\n" : "RESULT PASS\n");
    return n_fail ? 1 : 0;
}
