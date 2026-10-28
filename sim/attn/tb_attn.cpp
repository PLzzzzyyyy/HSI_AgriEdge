// tt_attn testbench：注意力（SCORES / SOFTMAX / CTX+RES）与分类头（HEAD）HLS 单元逐位比对（PLAN §17 D3，docs/engine_arch.md §6 第 3、4 条）。
//   黄金 sim/golden/n6_engine 入口 A（a/）与入口 B（b/）每层：SCORES 对 L<l>_s，SOFTMAX 对 L<l>_attn，
//        CTX+RES 对 L<l>_x_mid 与由它算出的 S1/Sxx（再按 §3.2 算 mean_q24 / inv_q24 对 L<l>_stats_mlp），
//        HEAD 对终块 L11_x_out 的 token 1 → logits_q16 / class；另加 batch_hanchuan 32 像素（16 类）
//   边界 sim/attn/vectors/（gen_vectors.py 以 model/engine_ref.py 为 oracle 生成）
// 所有输入文件按字节数精确校验，每项打印比对个数与不一致数，结尾核对总比对数，防止读错文件或长度导致空跑 PASS。
// 编译宏 TT_ATTN_UNIT：0 全部（默认）/ 1 SCORES / 2 SOFTMAX / 3 CTX / 4 HEAD（csynth、cosim 只测所选顶层）。
// 环境变量 TT_TB_LAYERS=<n> 只回放前 n 层（cosim 省时间），默认 12。
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdint.h>
#include <string>
#include <vector>
#include "../../src/hls/tt_attn.h"

#ifndef TT_ATTN_UNIT
#define TT_ATTN_UNIT 0
#endif
#define RUN(u) (TT_ATTN_UNIT == 0 || TT_ATTN_UNIT == (u))

typedef long long i64;
static const int DN = TT_D * TT_N;
static const i64 GARB = 0x15A5A;                 // 补齐 lane 的内容（单元必须忽略）
static const i64 SENT = 0x2B6D3;                 // X 输出的哨兵（补齐位置必须保持不变）

static void require(bool ok, const std::string &msg) { if (!ok) { std::printf("FAIL: %s\n", msg.c_str()); std::exit(1); } }
static std::string root() {
    std::string f = __FILE__;
    for (size_t i = 0; i < f.size(); ++i) if (f[i] == '\\') f[i] = '/';
    const size_t pos = f.rfind("/sim/attn/");
    require(pos != std::string::npos, "cannot locate repo root from __FILE__");
    return f.substr(0, pos);
}
static std::vector<uint8_t> read_all(const std::string &rel) {
    const std::string path = root() + "/" + rel;
    FILE *f = std::fopen(path.c_str(), "rb");
    require(f != 0, "cannot open " + path);
    std::vector<uint8_t> b;
    uint8_t buf[65536];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) b.insert(b.end(), buf, buf + n);
    std::fclose(f);
    return b;
}
template <class T> static std::vector<i64> load(const std::string &rel, size_t count) {
    const std::vector<uint8_t> b = read_all(rel);
    require(b.size() == count * sizeof(T), rel + ": " + std::to_string(b.size()) + " bytes, expected " + std::to_string(count * sizeof(T)));
    std::vector<i64> r(count);
    for (size_t i = 0; i < count; ++i) { T v; std::memcpy(&v, &b[i * sizeof(T)], sizeof(T)); r[i] = (i64)v; }
    return r;
}
static i64 rd64(const uint8_t *p, size_t k) { i64 v; std::memcpy(&v, p + 8 * k, 8); return v; }
static i64 rd32(const uint8_t *p, size_t k) { int32_t v; std::memcpy(&v, p + 4 * k, 4); return v; }

// vectors/*.bin：8 字节用例数 + 定长记录
struct Cases {
    std::vector<uint8_t> b;
    size_t n, rec;
    const uint8_t *at(size_t i) const { return &b[8 + i * rec]; }
};
static Cases cases(const std::string &name, size_t rec) {
    Cases c;
    c.b = read_all("sim/attn/vectors/" + name);
    c.rec = rec;
    require(c.b.size() >= 8, name + ": shorter than the count header");
    const i64 n = rd64(&c.b[0], 0);
    require(n > 0 && c.b.size() == 8 + (size_t)n * rec, name + ": size does not match count * record");
    c.n = (size_t)n;
    return c;
}
// 生成描述 (mode, a, b, seed)：0 = 常数 a；1 = [a, b] 均匀，splitmix64（gen_vectors.py 同式）
static std::vector<i64> gen(const uint8_t *d, size_t n) {
    const i64 mode = rd64(d, 0), a = rd64(d, 1), b = rd64(d, 2);
    const uint64_t seed = (uint64_t)rd64(d, 3);
    require(mode == 0 || (mode == 1 && b >= a), "bad generator descriptor");
    std::vector<i64> r(n);
    for (size_t i = 0; i < n; ++i) {
        if (mode == 0) { r[i] = a; continue; }
        uint64_t z = seed + (uint64_t)(i + 1) * 0x9E3779B97F4A7C15ULL;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
        z ^= z >> 31;
        r[i] = a + (i64)(z % (uint64_t)(b - a + 1));
    }
    return r;
}
static void chk_range(const std::vector<i64> &v, i64 lo, i64 hi, const std::string &what) {
    for (size_t i = 0; i < v.size(); ++i) require(v[i] >= lo && v[i] <= hi, what + ": value out of range");
}

// ---------------------------------------------------------------- 计数
static i64 g_values = 0, g_bad = 0;
static int g_items = 0, g_fail = 0;
static i64 g_unit_values[5] = {0, 0, 0, 0, 0};
static int report(int unit, const std::string &tag, i64 values, i64 bad) {
    std::printf("%-44s %8lld values, %6lld mismatches  %s\n", tag.c_str(), values, bad, bad ? "FAIL" : "PASS");
    g_values += values; g_bad += bad; g_unit_values[unit] += values;
    ++g_items; if (bad) ++g_fail;
    return (int)bad;
}
static i64 diff(const i64 *got, const i64 *ref, size_t n, const std::string &tag) {
    i64 bad = 0;
    for (size_t i = 0; i < n; ++i)
        if (got[i] != ref[i]) { if (bad < 3) std::printf("  %s[%zu] got %lld ref %lld\n", tag.c_str(), i, got[i], ref[i]); ++bad; }
    return bad;
}

// ---------------------------------------------------------------- 单元调用（输入输出都用 (p, n) 内存序的 int64 块）
// 块 (p, n) 内存序 → 引擎块布局 blk[n][p % TA_H][p / TA_H]，补齐 lane 填 fill
static void to_blk(const std::vector<i64> &src, ta_blk_t dst, i64 fill) {
    for (int n = 0; n < TT_N; ++n)
        for (int p = 0; p < TA_BD * TA_H; ++p)
            dst[n][p % TA_H][p / TA_H] = ta_act_t(p < TT_D ? src[p * TT_N + n] : fill);
}

static void call_scores(const std::vector<i64> &q, const std::vector<i64> &k, i64 s_out[36]) {
    static ta_blk_t qb, kb;
    to_blk(q, qb, GARB);
    to_blk(k, kb, GARB);
    ta_s_t s[TT_N][TT_N];
    for (int n = 0; n < TT_N; ++n) for (int c = 0; c < TT_N; ++c) s[n][c] = ta_s_t(0x5A5A5A5A5A5LL);
    tt_attn_scores(qb, kb, s);
    for (int n = 0; n < TT_N; ++n) for (int c = 0; c < TT_N; ++c) s_out[n * TT_N + c] = s[n][c].to_int64();
}

static void call_softmax(const i64 s_in[36], i64 a_out[36]) {
    ta_s_t s[TT_N][TT_N];
    ta_attn_t a[TT_N][TT_N];
    for (int n = 0; n < TT_N; ++n)
        for (int c = 0; c < TT_N; ++c) { s[n][c] = ta_s_t(s_in[n * TT_N + c]); a[n][c] = 0x1FFFFFF; }
    tt_attn_softmax(s, a);
    for (int n = 0; n < TT_N; ++n) for (int c = 0; c < TT_N; ++c) a_out[n * TT_N + c] = (i64)a[n][c].to_uint64();
}

// 返回 X 的补齐位置被改写的个数；x_out、s1、sxx 为输出
static i64 call_ctx(const i64 at_in[36], const std::vector<i64> &v, const std::vector<i64> &xn, std::vector<i64> &x_out, i64 s1[6], i64 sxx[6]) {
    static ta_blk_t vb, xb, ob;
    ta_attn_t at[TT_N][TT_N];
    ta_s1_t o1[TT_N];
    ta_sxx_t o2[TT_N];
    for (int s = 0; s < TT_N; ++s) for (int c = 0; c < TT_N; ++c) at[s][c] = ta_attn_t((unsigned long long)at_in[s * TT_N + c]);
    to_blk(v, vb, GARB);
    to_blk(xn, xb, GARB);
    to_blk(std::vector<i64>(DN, SENT), ob, SENT);
    for (int t = 0; t < TT_N; ++t) { o1[t] = 0x1234567; o2[t] = 0x123456789ALL; }
    tt_attn_ctx(at, vb, xb, ob, o1, o2);
    i64 pad = 0;
    x_out.assign(DN, 0);
    for (int t = 0; t < TT_N; ++t)
        for (int p = 0; p < TA_BD * TA_H; ++p) {
            const i64 val = ob[t][p % TA_H][p / TA_H].to_int64();
            if (p < TT_D) x_out[p * TT_N + t] = val;
            else if (val != ta_act_t(SENT).to_int64()) ++pad;
        }
    for (int t = 0; t < TT_N; ++t) { s1[t] = o1[t].to_int64(); sxx[t] = (i64)o2[t].to_uint64(); }
    return pad;
}

// W 为 24 行 × 2646（ncls 之后的行为 0），eh / hb 各 24 项；返回类别字
static unsigned int call_head(const std::vector<i64> &x1, const std::vector<i64> &w, const i64 eh_in[24], const i64 hb_in[24],
                              unsigned int ncls, i64 lg_out[32]) {
    static ap_uint<64> wh[TA_HW][TT_D];
    ap_int<8> eh[TA_NCLS];
    ap_int<32> hb[TA_NCLS];
    ta_logit_t lg[TA_LOGITS];
    for (int g = 0; g < TA_HW; ++g)
        for (int p = 0; p < TT_D; ++p) {
            ap_uint<64> word = 0;
            for (int q = 0; q < 4; ++q) word.range(16 * q + 15, 16 * q) = ap_int<16>(w[(4 * g + q) * TT_D + p]).range(15, 0);
            wh[g][p] = word;
        }
    for (int c = 0; c < TA_NCLS; ++c) { eh[c] = (int)eh_in[c]; hb[c] = (int)hb_in[c]; }
    for (int c = 0; c < TA_LOGITS; ++c) lg[c] = 0x7EADBEEF;
    static ta_blk_t xb;                                     // 只填 token 1，其余 token 填垃圾，验证 HEAD 只读 token 1
    to_blk(std::vector<i64>(DN, GARB), xb, GARB);
    for (int p = 0; p < TT_D; ++p) xb[1][p % TA_H][p / TA_H] = ta_act_t(x1[p]);
    const unsigned int cls = tt_attn_head(xb, wh, eh, hb, ncls, lg);
    for (int c = 0; c < TA_LOGITS; ++c) lg_out[c] = lg[c].to_int64();
    return cls;
}

// ---------------------------------------------------------------- 黄金
static std::string gdir(const char *ent) { return std::string("sim/golden/n6_engine/") + ent + "/"; }
static std::vector<i64> gblk(const char *ent, int l, const char *name) {
    std::vector<i64> v = load<int32_t>(gdir(ent) + "L" + std::to_string(l) + "_" + name, DN);
    chk_range(v, -131072, 131071, std::string(ent) + " L" + std::to_string(l) + " " + name);
    return v;
}

struct Pkg { unsigned int ncls; i64 eh[24], hb[24]; std::vector<i64> w; };
static Pkg load_pkg(const std::string &rel) {
    const std::vector<uint8_t> b = read_all(rel);
    require(b.size() == TT_ENGINE_WPKG16_BYTES, rel + ": not an int16 weights_engine.bin");
    Pkg k;
    uint32_t h[4];
    std::memcpy(h, &b[0], 16);
    require(h[0] == TT_ENGINE_WPKG_MAGIC && h[3] == 16 && h[2] >= 1 && h[2] <= 24, rel + ": bad header");
    k.ncls = h[2];
    k.w.assign(24 * TT_D, 0);
    for (int c = 0; c < 24; ++c) {
        k.eh[c] = (int8_t)b[32 + c];
        k.hb[c] = rd32(&b[TT_ENGINE_WPKG_HBIAS], c);
        for (int p = 0; p < TT_D; ++p) { int16_t v; std::memcpy(&v, &b[TT_ENGINE_WPKG_HW + c * TT_ENGINE_WPKG_HW_ROW + 2 * p], 2); k.w[c * TT_D + p] = v; }
    }
    return k;
}

// §3.2 的 token 统计量（与 engine_ref.cpp::normalize 同式），用来核对 S1/Sxx 正是下一次归一化要的量
static void stats_from(const i64 s1[6], const i64 sxx[6], i64 st[12]) {
    const float INV_C = (float)(std::sqrt((double)TT_D * (TT_D - 1)) * std::ldexp(1.0, TT_DF));
    for (int n = 0; n < TT_N; ++n) {
        const i64 var = (i64)TT_D * sxx[n] - s1[n] * s1[n];
        const i64 mean = (s1[n] * (1LL << (24 - TT_DF))) / TT_D;
        float inv = INV_C / std::sqrt((float)var);
        if (!(inv <= 127.0f)) inv = 127.0f;
        st[2 * n] = mean;
        st[2 * n + 1] = (i64)(inv * 16777216.0f);
    }
}

int main() {
    const char *env = std::getenv("TT_TB_LAYERS");
    const int layers = env ? std::atoi(env) : TT_ENGINE_LAYERS;
    require(layers >= 1 && layers <= TT_ENGINE_LAYERS, "TT_TB_LAYERS must be 1..12");
    std::printf("tt_attn tb: TT_K3=%d (TA_H=%d), unit=%d, layers=%d\n", TT_K3, TA_H, TT_ATTN_UNIT, layers);
    const char *ents[2] = {"a", "b"};

    // ---- SCORES
    if (RUN(1)) {
        for (int e = 0; e < 2; ++e)
            for (int l = 0; l < layers; ++l) {
                const std::vector<i64> ref = load<int64_t>(gdir(ents[e]) + "L" + std::to_string(l) + "_s_i8.bin", 36);
                i64 s[36];
                call_scores(gblk(ents[e], l, "q_i4.bin"), gblk(ents[e], l, "k_i4.bin"), s);
                report(1, std::string("SCORES ") + ents[e] + " L" + std::to_string(l), 36, diff(s, ref.data(), 36, "s"));
            }
        const Cases cs = cases("scores_cases.bin", 44 * 8);
        i64 bad = 0;
        for (size_t i = 0; i < cs.n; ++i) {
            const uint8_t *r = cs.at(i);
            const std::vector<i64> q = gen(r, DN), k = gen(r + 32, DN);
            chk_range(q, -131072, 131071, "scores q"); chk_range(k, -131072, 131071, "scores k");
            i64 s[36], ref[36];
            for (int j = 0; j < 36; ++j) ref[j] = rd64(r + 64, j);
            call_scores(q, k, s);
            bad += diff(s, ref, 36, "scores case " + std::to_string(i));
        }
        report(1, "SCORES boundary (" + std::to_string(cs.n) + " cases)", 36 * (i64)cs.n, bad);
    }

    // ---- SOFTMAX（另测 exp 表与 ta_exp 本身）
    if (RUN(2)) {
        i64 bad = 0;
        for (int a = 0; a < 256; ++a) {
            bad += ta_thi[a].to_int64() != (i64)std::llround(std::pow(2.0, -a / 256.0) * 16777216.0);
            bad += ta_tlo[a].to_int64() != (i64)std::llround(std::pow(2.0, -a / 65536.0) * 16777216.0);
        }
        report(2, "exp tables T_HI / T_LO", 512, bad);
        const Cases ce = cases("exp_cases.bin", 16);
        bad = 0;
        for (size_t i = 0; i < ce.n; ++i) {
            const i64 d = rd64(ce.at(i), 0), ref = rd64(ce.at(i), 1);
            const i64 got = ta_exp(ap_uint<56>((unsigned long long)d)).to_int64();
            if (got != ref) { if (bad < 3) std::printf("  exp d=%lld got %lld ref %lld\n", d, got, ref); ++bad; }
        }
        report(2, "ta_exp (" + std::to_string(ce.n) + " d values)", (i64)ce.n, bad);
        for (int e = 0; e < 2; ++e)
            for (int l = 0; l < layers; ++l) {
                const std::string p = gdir(ents[e]) + "L" + std::to_string(l);
                const std::vector<i64> s = load<int64_t>(p + "_s_i8.bin", 36), ref = load<int32_t>(p + "_attn_i4.bin", 36);
                i64 a[36];
                call_softmax(s.data(), a);
                report(2, std::string("SOFTMAX ") + ents[e] + " L" + std::to_string(l), 36, diff(a, ref.data(), 36, "attn"));
            }
        const Cases cs = cases("softmax_cases.bin", 36 * 8 + 36 * 4);
        bad = 0;
        for (size_t i = 0; i < cs.n; ++i) {
            i64 s[36], ref[36], a[36];
            for (int j = 0; j < 36; ++j) { s[j] = rd64(cs.at(i), j); ref[j] = rd32(cs.at(i) + 288, j); }
            call_softmax(s, a);
            bad += diff(a, ref, 36, "softmax case " + std::to_string(i));
        }
        report(2, "SOFTMAX boundary (" + std::to_string(cs.n) + " cases)", 36 * (i64)cs.n, bad);
    }

    // ---- CTX+RES
    if (RUN(3)) {
        for (int e = 0; e < 2; ++e)
            for (int l = 0; l < layers; ++l) {
                const std::string p = gdir(ents[e]) + "L" + std::to_string(l);
                const std::vector<i64> at = load<int32_t>(p + "_attn_i4.bin", 36), xm = gblk(ents[e], l, "x_mid_i4.bin");
                const std::vector<i64> st = load<int32_t>(p + "_stats_mlp_i4.bin", 12);
                std::vector<i64> x;
                i64 s1[6], sxx[6], r1[6] = {0}, r2[6] = {0}, s_st[12];
                const i64 pad = call_ctx(at.data(), gblk(ents[e], l, "v_i4.bin"), gblk(ents[e], l, "xn_q_i4.bin"), x, s1, sxx);
                for (int q = 0; q < DN; ++q) { r1[q % TT_N] += xm[q]; r2[q % TT_N] += xm[q] * xm[q]; }
                stats_from(s1, sxx, s_st);
                i64 bad = diff(x.data(), xm.data(), DN, "x_mid") + pad;
                bad += diff(s1, r1, 6, "S1") + diff(sxx, r2, 6, "Sxx") + diff(s_st, st.data(), 12, "stats_mlp");
                report(3, std::string("CTX+RES ") + ents[e] + " L" + std::to_string(l) + " (x_mid, S1/Sxx, stats)", DN + 24, bad);
            }
        const Cases cs = cases("ctx_cases.bin", (36 + 4 + 4 + 6 + 6) * 8 + DN * 4);
        i64 bad = 0;
        for (size_t i = 0; i < cs.n; ++i) {
            const uint8_t *r = cs.at(i);
            i64 at[36], s1[6], sxx[6], r1[6], r2[6];
            for (int j = 0; j < 36; ++j) at[j] = rd64(r, j);
            const std::vector<i64> v = gen(r + 288, DN), xn = gen(r + 320, DN);
            chk_range(v, -131072, 131071, "ctx v"); chk_range(xn, -131072, 131071, "ctx xn");
            for (int j = 0; j < 36; ++j) require(at[j] >= 0 && at[j] < (1 << 25), "ctx attn out of 25-bit range");
            for (int t = 0; t < 6; ++t) { r1[t] = rd64(r + 352, t); r2[t] = rd64(r + 400, t); }
            std::vector<i64> ref(DN), x;
            for (int q = 0; q < DN; ++q) ref[q] = rd32(r + 448, q);
            const i64 pad = call_ctx(at, v, xn, x, s1, sxx);
            bad += diff(x.data(), ref.data(), DN, "ctx case " + std::to_string(i)) + pad;
            bad += diff(s1, r1, 6, "ctx S1") + diff(sxx, r2, 6, "ctx Sxx");
        }
        report(3, "CTX+RES boundary (" + std::to_string(cs.n) + " cases)", (DN + 12) * (i64)cs.n, bad);
    }

    // ---- HEAD
    if (RUN(4)) {
        const Pkg k = load_pkg("sim/golden/n6_engine/weights_engine.bin");
        for (int e = 0; e < 2; ++e) {
            const std::vector<i64> xo = gblk(ents[e], TT_ENGINE_LAYERS - 1, "x_out_i4.bin");
            const std::vector<i64> lref = load<int32_t>(gdir(ents[e]) + "logits_q16_i32.bin", 32);
            const std::vector<i64> cref = load<uint32_t>(gdir(ents[e]) + "class_u32.bin", 1);
            std::vector<i64> x1(TT_D);
            for (int p = 0; p < TT_D; ++p) x1[p] = xo[p * TT_N + 1];
            i64 lg[32];
            const i64 cls = call_head(x1, k.w, k.eh, k.hb, k.ncls, lg);
            report(4, std::string("HEAD ") + ents[e] + " (" + std::to_string(k.ncls) + " classes, logits + class)", 33,
                   diff(lg, lref.data(), 32, "logits") + diff(&cls, cref.data(), 1, "class"));
        }
        {
            const std::string bd = "sim/golden/n6_engine/batch_hanchuan/";
            const Pkg kb = load_pkg(bd + "weights_engine.bin");
            const Cases cx = cases("head_hanchuan_x1.bin", TT_D * 4);
            const std::vector<i64> lref = load<int32_t>(bd + "expect_logits_i32.bin", cx.n * 32);
            const std::vector<i64> cref = load<uint32_t>(bd + "expect_class_u32.bin", cx.n);
            i64 bad = 0;
            for (size_t i = 0; i < cx.n; ++i) {
                std::vector<i64> x1(TT_D);
                for (int p = 0; p < TT_D; ++p) x1[p] = rd32(cx.at(i), p);
                chk_range(x1, -131072, 131071, "hanchuan x1");
                i64 lg[32];
                const i64 cls = call_head(x1, kb.w, kb.eh, kb.hb, kb.ncls, lg);
                bad += diff(lg, &lref[i * 32], 32, "hanchuan logits " + std::to_string(i)) + diff(&cls, &cref[i], 1, "hanchuan class");
            }
            report(4, "HEAD batch_hanchuan (" + std::to_string(cx.n) + " px, " + std::to_string(kb.ncls) + " classes)", 33 * (i64)cx.n, bad);
        }
        const Cases cs = cases("head_cases.bin", 8 + 32 + 24 * 48 + 128 + 8);
        i64 bad = 0;
        for (size_t i = 0; i < cs.n; ++i) {
            const uint8_t *r = cs.at(i);
            const unsigned int ncls = (unsigned int)rd64(r, 0);
            require(ncls >= 1 && ncls <= 24, "head case ncls");
            const std::vector<i64> x1 = gen(r + 8, TT_D);
            chk_range(x1, -131072, 131071, "head x1");
            std::vector<i64> w(24 * TT_D);
            i64 eh[24], hb[24], lref[32], lg[32];
            for (int c = 0; c < 24; ++c) {
                const uint8_t *cr = r + 40 + 48 * c;
                const std::vector<i64> row = gen(cr, TT_D);
                chk_range(row, -32768, 32767, "head W");
                for (int p = 0; p < TT_D; ++p) w[c * TT_D + p] = row[p];
                eh[c] = rd64(cr, 4); hb[c] = rd64(cr, 5);
            }
            for (int c = 0; c < 32; ++c) lref[c] = rd32(r + 40 + 24 * 48, c);
            const i64 cref = (i64)(uint32_t)rd32(r + 40 + 24 * 48 + 128, 0);
            const i64 cls = call_head(x1, w, eh, hb, ncls, lg);
            bad += diff(lg, lref, 32, "head case " + std::to_string(i) + " logits") + diff(&cls, &cref, 1, "head case " + std::to_string(i) + " class");
        }
        report(4, "HEAD boundary (" + std::to_string(cs.n) + " cases)", 33 * (i64)cs.n, bad);
    }

    // 空跑保护：所选单元必须真的比对过数据
    for (int u = 1; u <= 4; ++u) if (RUN(u)) require(g_unit_values[u] > 0, "unit " + std::to_string(u) + " compared nothing");
    std::printf("%s: %d items, %lld values compared, %lld mismatches, %d items failed\n",
                g_bad ? "RESULT FAIL" : "RESULT PASS", g_items, g_values, g_bad, g_fail);
    return g_bad ? 1 : 0;
}
