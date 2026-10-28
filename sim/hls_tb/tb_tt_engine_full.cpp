// tt_engine M3a 编译（TT_DB = 18）testbench：对 sim/golden/n6_engine（model/engine_ref.py 入口 A）逐位比对。
//   1. 错误码（不写任何输出）
//   2. FULL + DUMP + FEAT：入口 A 的 x_in，layer 0..L−1 每层 x_out 逐位
//   3. FULL + LOGITS / CLASS，n_patch = 3：{入口 A、入口 B 的 x_embed、入口 A}，logits 与类别字逐位；CLASS 奇数像素末字高半为 0
//   4. 从中间层开始：x_in = 入口 A 第 4 层 x_out，layer 5..11，FEAT 终块与 CLASS
//   5. PROJ（逐层调试口）：第 0 层 QKV 与 MLP，q/k/v/m 饱和到 int16、stats 逐位
// 所有输出区预置哨兵，核对写入范围。环境变量 TT_TB_LAYERS=<n>：第 2 项只跑前 n 层，并跳过 3、4 项（cosim 省时间），默认 12。
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdint.h>
#include <string>
#include <vector>
#include "../../src/hls/tt_engine.h"

#if TT_DB != 18
#error "tb_tt_engine_full needs the M3a build (-DTT_DB=18)"
#endif

typedef long long i64;
static const int DN = TT_D * TT_N;
static const int NBLK = 3;
static const int WPX = TT_ENGINE_OUT32_STRIDE / 8;
static const u64 SENT = u64("0x1234ABCD5678EF09");

static void require(bool ok, const std::string &msg) { if (!ok) { std::printf("FAIL: %s\n", msg.c_str()); std::exit(1); } }
static std::string root() {
    std::string f = __FILE__;
    for (size_t i = 0; i < f.size(); ++i) if (f[i] == '\\') f[i] = '/';
    const size_t pos = f.rfind("/sim/hls_tb/");
    require(pos != std::string::npos, "cannot locate repo root from __FILE__");
    return f.substr(0, pos);
}
template <class T> static std::vector<i64> load(const std::string &rel, size_t count) {
    const std::string path = root() + "/sim/golden/n6_engine/" + rel;
    FILE *f = std::fopen(path.c_str(), "rb");
    require(f != 0, path);
    std::vector<T> r(count);
    require(std::fread(r.data(), sizeof(T), count, f) == count, "short input " + rel);
    require(std::fgetc(f) == EOF, "unexpected extra input " + rel);
    std::fclose(f);
    return std::vector<i64>(r.begin(), r.end());
}
static std::vector<i64> gl(const char *ent, int l, const char *name) { return load<int32_t>(std::string(ent) + "/L" + std::to_string(l) + "_" + name, DN); }

struct Bufs {
    std::vector<u64> x, cube, xo, q, k, v, st;
    Bufs() : x(NBLK * TT_IN_WORDS, SENT), cube(1, SENT), xo(12 * WPX, SENT), q(NBLK * TT_IN_WORDS, SENT), k(q), v(q), st(NBLK * TT_ST_WORDS, SENT) {}
    void put(int i, const std::vector<i64> &blk) {
        for (int e = 0; e < DN; ++e) {
            require(blk[e] >= -32768 && blk[e] <= 32767, "input block does not fit int16");
            x[i * TT_IN_WORDS + e / 4].range((e % 4) * 16 + 15, (e % 4) * 16) = (unsigned short)(short)blk[e];
        }
    }
};
static unsigned int call(Bufs &b, const std::vector<u64> &w, unsigned int n_patch, unsigned int lo, unsigned int hi, unsigned int mask, unsigned int mode) {
    unsigned int cyc = 0xFFFFFFFFu;
    const unsigned int r = tt_engine(b.x.data(), b.cube.data(), b.xo.data(), b.q.data(), b.k.data(), b.v.data(), b.st.data(),
                                     w.data(), 0, 0, 0, n_patch, lo, hi, mask, mode, &cyc);
    require(TT_ENGINE_RET_VERSION(r) == TT_ENGINE_VERSION && TT_ENGINE_RET_FRAC(r) == 12 && TT_ENGINE_RET_BITS(r) == 18, "return fields");
    require(b.cube[0] == SENT, "cube touched in M3a build");
    return TT_ENGINE_RET_ERR(r);
}
static void untouched(const std::vector<u64> &buf, size_t from, const char *what) {
    for (size_t e = from; e < buf.size(); ++e) require(buf[e] == SENT, std::string("unexpected write: ") + what);
}
static i64 lane32(const std::vector<u64> &b, size_t e) { return (int32_t)(uint32_t)b[e / 2].range(32 * (e % 2) + 31, 32 * (e % 2)); }
static i64 lane16(const std::vector<u64> &b, size_t e) { return (short)(unsigned short)b[e / 4].range(16 * (e % 4) + 15, 16 * (e % 4)); }
static i64 sat16(i64 v) { return v > 32767 ? 32767 : (v < -32768 ? -32768 : v); }

static int cmp(const std::string &tag, const i64 *got, const i64 *ref, size_t n) {
    int bad = 0;
    for (size_t i = 0; i < n; ++i)
        if (got[i] != ref[i]) { if (bad < 3) std::printf("  %s[%zu] got %lld ref %lld\n", tag.c_str(), i, got[i], ref[i]); ++bad; }
    return bad;
}
// FEAT 块（x_out 字偏移 off）对期望块
static int cmp_feat(const std::string &tag, const std::vector<u64> &xo, size_t off, const std::vector<i64> &ref) {
    std::vector<i64> g(DN);
    for (int e = 0; e < DN; ++e) g[e] = lane32(xo, 2 * off + e);
    for (int w = DN / 2; w < WPX; ++w) require(xo[off + w] == SENT, "write into FEAT padding");
    return cmp(tag, g.data(), ref.data(), DN);
}

int main() {
    const char *env = std::getenv("TT_TB_LAYERS");
    const int layers = env ? std::atoi(env) : TT_ENGINE_LAYERS;
    require(layers >= 1 && layers <= TT_ENGINE_LAYERS, "TT_TB_LAYERS");
    std::printf("tt_engine M3a tb: TT_K3=%d, layers=%d\n", TT_K3, layers);

    // 权重包 weights_engine.bin 原样
    const std::vector<i64> pb = load<uint8_t>("weights_engine.bin", TT_ENGINE_WPKG16_BYTES);
    std::vector<u64> pkg(TT_WPKG_WORDS, 0);
    for (int i = 0; i < TT_ENGINE_WPKG16_BYTES; ++i) pkg[i / 8].range(8 * (i % 8) + 7, 8 * (i % 8)) = (unsigned)pb[i];
    const int ncls = (int)pkg[1].range(31, 0);
    std::vector<u64> bad8 = pkg; bad8[1].range(63, 32) = 8;

    const std::vector<i64> xa = load<int16_t>("a/x_in_i16.bin", DN), xbv = load<int32_t>("b/x_embed_i32.bin", DN);
    const std::vector<i64> lga = load<int32_t>("a/logits_q16_i32.bin", 32), lgb = load<int32_t>("b/logits_q16_i32.bin", 32);
    const i64 cla = load<uint32_t>("a/class_u32.bin", 1)[0], clb = load<uint32_t>("b/class_u32.bin", 1)[0];
    const unsigned FEAT = TT_ENGINE_MODE_FULL | TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_FEAT);
    const unsigned LOGITS = TT_ENGINE_MODE_FULL | TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_LOGITS), CLASS = TT_ENGINE_MODE_FULL;
    int bad = 0;

    // 1. 错误码
    {
        Bufs b;
        b.put(0, xa);
        require(call(b, pkg, 1, 0, 11, 0, CLASS) == TT_ENGINE_ERR_NOWEIGHT, "NOWEIGHT before load");
        require(call(b, pkg, 1, 0, 11, 0, CLASS | TT_ENGINE_MODE_CUBE) == TT_ENGINE_ERR_MODE, "CUBE in M3a build");
        require(call(b, pkg, 1, 1, 11, 0, TT_ENGINE_MODE_FULL | TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_ATTENTION)) == TT_ENGINE_ERR_MODE, "partial attention");
        require(call(b, pkg, 1, 0, 11, 0, CLASS | TT_ENGINE_MODE_DUMP) == TT_ENGINE_ERR_MODE, "DUMP without FEAT");
        require(call(b, pkg, 1, 0, 10, 0, CLASS) == TT_ENGINE_ERR_MODE, "CLASS with layer_hi != 11");
        require(call(b, pkg, 1, 0, 0, TT_ENGINE_PROJ_QKV, TT_ENGINE_MODE_DUMP) == TT_ENGINE_ERR_MODE, "DUMP in PROJ");
        require(call(b, pkg, 1, 5, 4, 0, FEAT) == TT_ENGINE_ERR_LAYER, "layer_lo > layer_hi");
        require(call(b, pkg, 1, 0, 12, 0, FEAT) == TT_ENGINE_ERR_LAYER, "layer_hi 12");
        require(call(b, pkg, 1, 0, 0, 0, 0) == TT_ENGINE_ERR_PROJ, "PROJ mask 0");
        require(call(b, pkg, 0, 0, 0, 0, TT_ENGINE_MODE_LOAD_W | TT_ENGINE_MODE_USE_BANK) == TT_ENGINE_ERR_BANK, "bank 1");
        require(call(b, bad8, 0, 0, 0, 0, TT_ENGINE_MODE_LOAD_W) == TT_ENGINE_ERR_WPKG, "int8 package in int16 build");
        require(call(b, pkg, 1, 0, 11, 0, CLASS) == TT_ENGINE_ERR_NOWEIGHT, "bad package must not mark loaded");
        untouched(b.xo, 0, "x_out"); untouched(b.q, 0, "q"); untouched(b.k, 0, "k"); untouched(b.v, 0, "v"); untouched(b.st, 0, "stats");
        std::printf("error codes: PASS\n");
    }
    {
        Bufs b;
        require(call(b, pkg, 0, 0, 0, 0, TT_ENGINE_MODE_LOAD_W) == 0, "LOAD_W only");
    }

    // 2. FULL + DUMP：每层 x_out
    {
        Bufs b;
        b.put(0, xa);
        require(call(b, pkg, 1, 0, layers - 1, 0, FEAT | TT_ENGINE_MODE_DUMP) == 0, "DUMP call");
        for (int l = 0; l < layers; ++l) {
            const int d = cmp_feat("L" + std::to_string(l) + " x_out", b.xo, (size_t)l * WPX, gl("a", l, "x_out_i4.bin"));
            std::printf("layer %2d: x_out mismatches=%d\n", l, d);
            bad += d;
        }
        untouched(b.xo, (size_t)layers * WPX, "x_out after DUMP region");
        untouched(b.q, 0, "q in FULL"); untouched(b.st, 0, "stats in FULL");
    }

    if (layers == TT_ENGINE_LAYERS) {
        // 3. 批：LOGITS 与 CLASS
        Bufs b;
        b.put(0, xa); b.put(1, xbv); b.put(2, xa);
        require(call(b, pkg, 3, 0, 11, 0, LOGITS) == 0, "LOGITS batch");
        int d = 0;
        for (int i = 0; i < 3; ++i) {
            std::vector<i64> g(32);
            for (int c = 0; c < 32; ++c) g[c] = lane32(b.xo, 32 * i + c);
            d += cmp("logits px" + std::to_string(i), g.data(), (i == 1 ? lgb : lga).data(), 32);
        }
        untouched(b.xo, 3 * 16, "x_out after LOGITS");
        std::fill(b.xo.begin(), b.xo.end(), SENT);
        require(call(b, pkg, 3, 0, 11, 0, CLASS) == 0, "CLASS batch");
        const i64 got[4] = { lane32(b.xo, 0) & 0xFFFFFFFFLL, lane32(b.xo, 1) & 0xFFFFFFFFLL, lane32(b.xo, 2) & 0xFFFFFFFFLL, lane32(b.xo, 3) };
        const i64 ref[4] = { cla, clb, cla, 0 };
        d += cmp("class", got, ref, 4);
        untouched(b.xo, 2, "x_out after CLASS");
        std::printf("batch n_patch=3 (A, B embed, A): LOGITS + CLASS mismatches=%d (ncls %d)\n", d, ncls);
        bad += d;

        // 4. 从第 5 层开始
        Bufs m;
        m.put(0, gl("a", 4, "x_out_i4.bin"));
        require(call(m, pkg, 1, 5, 11, 0, FEAT) == 0, "FEAT lo=5");
        d = cmp_feat("lo5 final", m.xo, 0, gl("a", 11, "x_out_i4.bin"));
        untouched(m.xo, WPX, "x_out after FEAT");
        std::fill(m.xo.begin(), m.xo.end(), SENT);
        require(call(m, pkg, 1, 5, 11, 0, CLASS) == 0, "CLASS lo=5");
        const i64 c1[2] = { lane32(m.xo, 0) & 0xFFFFFFFFLL, lane32(m.xo, 1) }, r1[2] = { cla, 0 };
        d += cmp("lo5 class", c1, r1, 2);
        std::printf("layers 5..11 from L4 x_out: FEAT + CLASS mismatches=%d\n", d);
        bad += d;
    }

    // 5. PROJ：第 0 层 QKV（入口 A x_in）与 MLP（x_mid）
    {
        Bufs b;
        b.put(0, xa);
        require(call(b, pkg, 1, 0, 0, TT_ENGINE_PROJ_QKV, 0) == 0, "PROJ QKV");
        const char *nm[3] = { "q_i4.bin", "k_i4.bin", "v_i4.bin" };
        const std::vector<u64> *ob[3] = { &b.q, &b.k, &b.v };
        int d = 0;
        for (int j = 0; j < 3; ++j) {
            std::vector<i64> r = gl("a", 0, nm[j]), g(DN);
            for (int e = 0; e < DN; ++e) { r[e] = sat16(r[e]); g[e] = lane16(*ob[j], e); }
            d += cmp(nm[j], g.data(), r.data(), DN);
            untouched(*ob[j], TT_IN_WORDS, "PROJ output after block 0");
        }
        const std::vector<i64> sq = load<int32_t>("a/L0_stats_qkv_i4.bin", 12);
        std::vector<i64> gs(12);
        for (int t = 0; t < TT_N; ++t) { gs[2 * t] = lane32(b.st, 2 * t); gs[2 * t + 1] = lane32(b.st, 2 * t + 1); }
        d += cmp("stats_qkv", gs.data(), sq.data(), 12);
        untouched(b.xo, 0, "x_out in PROJ");

        Bufs m;
        m.put(0, gl("a", 0, "x_mid_i4.bin"));
        require(call(m, pkg, 1, 0, 0, TT_ENGINE_PROJ_MLP, 0) == 0, "PROJ MLP");
        std::vector<i64> r = gl("a", 0, "m_i4.bin"), g(DN);
        for (int e = 0; e < DN; ++e) { r[e] = sat16(r[e]); g[e] = lane16(m.q, e); }
        d += cmp("m", g.data(), r.data(), DN);
        const std::vector<i64> sm = load<int32_t>("a/L0_stats_mlp_i4.bin", 12);
        for (int t = 0; t < TT_N; ++t) { gs[2 * t] = lane32(m.st, 2 * t); gs[2 * t + 1] = lane32(m.st, 2 * t + 1); }
        d += cmp("stats_mlp", gs.data(), sm.data(), 12);
        untouched(m.k, 0, "k in MLP"); untouched(m.v, 0, "v in MLP");
        std::printf("PROJ layer 0 (QKV + MLP, int16 sat): mismatches=%d\n", d);
        bad += d;
    }
    std::printf(bad ? "FAIL: %d mismatches\n" : "PASS tt_engine M3a: bit-exact vs sim/golden/n6_engine (entry A), batch, layer range, PROJ, error codes\n", bad);
    return bad ? 1 : 0;
}
