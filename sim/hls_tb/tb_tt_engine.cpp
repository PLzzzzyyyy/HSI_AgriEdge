// tt_engine M2（PROJ 模式）testbench：回放 sim/golden/n6_real 12 层 × 2 次调用（QKV、MLP）逐位比对 q/k/v/mlp/stats；
// 另测批处理（n_patch = 3，按跨距寻址、不越界写）、单投影子集、错误码。期望值：黄金向量（板上路径）与 src/ps/tt_ref_int.h。
// 环境变量 TT_TB_LAYERS=<n> 只回放前 n 层（cosim 省时间），默认 12。
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <string>
#include "../../src/hls/tt_engine.h"
#include "../../src/ps/tt_ref_int.h"

static const int NBLK = 3;                                  // 缓冲按 3 个 patch 分配（= HLS depth）
static const int DN = TT_D * TT_N;
static const u64 SENT = u64("0x1234ABCD5678EF09");

static void require(bool ok, const char *msg) { if (!ok) { std::printf("FAIL: %s\n", msg); std::exit(1); } }
static std::string root() {
    std::string f = __FILE__;
    for (size_t i = 0; i < f.size(); ++i) if (f[i] == '\\') f[i] = '/';
    const size_t pos = f.rfind("/sim/hls_tb/");
    require(pos != std::string::npos, "cannot locate repo root from __FILE__");
    return f.substr(0, pos);
}
template <class T> static std::vector<T> load(const std::string &rel, size_t count) {
    const std::string path = root() + "/" + rel;
    FILE *f = std::fopen(path.c_str(), "rb");
    require(f != 0, path.c_str());
    std::vector<T> r(count);
    require(std::fread(r.data(), sizeof(T), count, f) == count, "short input");
    require(std::fgetc(f) == EOF, "unexpected extra input");
    std::fclose(f);
    return r;
}
static std::vector<short> gold(int l, const char *name, size_t count = DN) {
    return load<short>("sim/golden/n6_real/L" + std::to_string(l) + "_" + name, count);
}

struct Bufs {
    std::vector<u64> x, q, k, v, st, dummy_cube, dummy_out;
    Bufs() : x(NBLK * TT_IN_WORDS, SENT), q(x), k(x), v(x), st(NBLK * TT_ST_WORDS, SENT), dummy_cube(1, SENT), dummy_out(1, SENT) {}
    void put(int i, const std::vector<short> &blk) {
        for (int e = 0; e < DN; ++e) x[i * TT_IN_WORDS + e / 4].range((e % 4) * 16 + 15, (e % 4) * 16) = (unsigned short)blk[e];
    }
};
static unsigned int call(Bufs &b, const std::vector<u64> &w, unsigned int n_patch, unsigned int layer, unsigned int mask, unsigned int mode) {
    unsigned int cyc = 0xFFFFFFFFu;
    const unsigned int r = tt_engine(b.x.data(), b.dummy_cube.data(), b.dummy_out.data(), b.q.data(), b.k.data(), b.v.data(), b.st.data(),
                                     w.data(), 0, 0, 0, n_patch, layer, layer, mask, mode, &cyc);
    require(TT_ENGINE_RET_VERSION(r) == TT_ENGINE_VERSION && TT_ENGINE_RET_FRAC(r) == 12 && TT_ENGINE_RET_BITS(r) == 16, "return fields");
    require(b.dummy_cube[0] == SENT && b.dummy_out[0] == SENT, "cube/x_out touched in PROJ mode");
    return TT_ENGINE_RET_ERR(r);
}
// 块 i 与期望逐位比，块内补齐部分与未用块保持哨兵
static int check_blk(const char *tag, const std::vector<u64> &got, int i, const std::vector<short> &ref) {
    int bad = 0;
    for (int e = 0; e < DN; ++e) {
        const short v = (short)(unsigned short)got[i * TT_IN_WORDS + e / 4].range((e % 4) * 16 + 15, (e % 4) * 16);
        if (v != ref[e]) { if (bad < 3) std::printf("  %s[%d] got %d ref %d\n", tag, e, v, ref[e]); ++bad; }
    }
    for (int e = DN / 4; e < TT_IN_WORDS; ++e) require(got[i * TT_IN_WORDS + e] == SENT, "write into block padding");
    return bad;
}
static void untouched(const std::vector<u64> &buf, int from_blk, int words_per_blk) {
    for (size_t e = (size_t)from_blk * words_per_blk; e < buf.size(); ++e) require(buf[e] == SENT, "unused output written");
}
static int check_stats(const char *tag, const std::vector<u64> &st, int i, const int32_t *ref) {
    int bad = 0;
    for (int t = 0; t < TT_N; ++t) {
        const u64 w = st[i * TT_ST_WORDS + t];
        if ((int32_t)(uint32_t)w.range(31, 0) != ref[2 * t] || (int32_t)(uint32_t)w.range(63, 32) != ref[2 * t + 1]) {
            std::printf("  %s token %d mismatch\n", tag, t); ++bad;
        }
    }
    for (int t = TT_N; t < TT_ST_WORDS; ++t) require(st[i * TT_ST_WORDS + t] == SENT, "stats padding written");
    return bad;
}

int main() {
    const char *env = std::getenv("TT_TB_LAYERS");
    const int layers = env ? std::atoi(env) : TT_ENGINE_LAYERS;
    std::printf("tt_engine PROJ tb: TT_K3=%d, layers=%d\n", TT_K3, layers);
    const std::vector<short> wall = load<short>("model/data/weights_all.bin", (size_t)TT_NPROJ * TT_NF);

    // 权重包：头 + EMB/分类头段（M2 不用，填非零垃圾验证被跳过）+ 投影段 = weights_all.bin 原样
    std::vector<u64> pkg(TT_WPKG_WORDS, u64("0x0BADF00D0BADF00D"));
    pkg[0] = (u64)TT_ENGINE_WPKG_MAGIC | ((u64)1 << 32);
    pkg[1] = (u64)9 | ((u64)16 << 32);
    for (size_t e = 0; e < wall.size(); ++e)
        pkg[TT_WPROJ_W0 + e / 4].range((e % 4) * 16 + 15, (e % 4) * 16) = (unsigned short)wall[e];
    std::vector<u64> badpkg = pkg; badpkg[0] = 0;

    int bad = 0;
    Bufs b;
    b.put(0, load<short>("sim/golden/n6_real/x_embed_i16.bin", DN));
    // 1. 装载前 / 非法参数的错误码，且不写任何输出
    require(call(b, pkg, 1, 0, TT_ENGINE_PROJ_QKV, 0) == TT_ENGINE_ERR_NOWEIGHT, "NOWEIGHT before load");
    require(call(b, pkg, 1, 0, TT_ENGINE_PROJ_QKV, TT_ENGINE_MODE_FULL) == TT_ENGINE_ERR_MODE, "FULL in M2 build");
    require(call(b, pkg, 1, 0, TT_ENGINE_PROJ_QKV, TT_ENGINE_MODE_OUT(3)) == TT_ENGINE_ERR_MODE, "OUT = 3");
    require(call(b, pkg, 0, 0, TT_ENGINE_PROJ_QKV, 0) == TT_ENGINE_ERR_NPATCH, "n_patch 0 without LOAD_W");
    require(call(b, pkg, 1, 12, TT_ENGINE_PROJ_QKV, 0) == TT_ENGINE_ERR_LAYER, "layer 12");
    require(call(b, pkg, 1, 0, 0, 0) == TT_ENGINE_ERR_PROJ, "mask 0");
    require(call(b, pkg, 1, 0, TT_ENGINE_PROJ_MLP | TT_ENGINE_PROJ_Q, 0) == TT_ENGINE_ERR_PROJ, "MLP mixed with Q");
    require(call(b, pkg, 0, 0, 0, TT_ENGINE_MODE_LOAD_W | TT_ENGINE_MODE_LOAD_BANK) == TT_ENGINE_ERR_BANK, "bank 1 in single-bank build");
    require(call(b, badpkg, 0, 0, 0, TT_ENGINE_MODE_LOAD_W) == TT_ENGINE_ERR_WPKG, "bad magic");
    require(call(b, pkg, 1, 0, TT_ENGINE_PROJ_QKV, 0) == TT_ENGINE_ERR_NOWEIGHT, "bad package must not mark loaded");
    untouched(b.q, 0, 0); untouched(b.k, 0, 0); untouched(b.v, 0, 0); untouched(b.st, 0, 0);
    std::printf("error codes: PASS\n");

    // 2. 只装载
    require(call(b, pkg, 0, 0, 0, TT_ENGINE_MODE_LOAD_W) == TT_ENGINE_ERR_OK, "LOAD_W only");

    // 3. 黄金回放：每层 QKV（输入 = 上层 x_out / x_embed）与 MLP（输入 = x_mid）
    for (int l = 0; l < layers; ++l) {
        Bufs g;
        g.put(0, l == 0 ? load<short>("sim/golden/n6_real/x_embed_i16.bin", DN) : gold(l - 1, "x_out_i16.bin"));
        require(call(g, pkg, 1, l, TT_ENGINE_PROJ_QKV, 0) == 0, "QKV call");
        const std::vector<int32_t> sq = load<int32_t>("sim/golden/n6_real/L" + std::to_string(l) + "_stats_qkv_i32.bin", 2 * TT_N);
        int d = check_stats("stats_qkv", g.st, 0, sq.data());
        d += check_blk("q", g.q, 0, gold(l, "q_i16.bin"));
        d += check_blk("k", g.k, 0, gold(l, "k_i16.bin"));
        d += check_blk("v", g.v, 0, gold(l, "v_i16.bin"));
        untouched(g.q, 1, TT_IN_WORDS); untouched(g.st, 1, TT_ST_WORDS);

        Bufs m;
        m.put(0, gold(l, "x_mid_i16.bin"));
        require(call(m, pkg, 1, l, TT_ENGINE_PROJ_MLP, 0) == 0, "MLP call");
        const std::vector<int32_t> sm = load<int32_t>("sim/golden/n6_real/L" + std::to_string(l) + "_stats_mlp_i32.bin", 2 * TT_N);
        d += check_stats("stats_mlp", m.st, 0, sm.data());
        d += check_blk("mlp", m.q, 0, gold(l, "mlp_i16.bin"));
        untouched(m.k, 0, 0); untouched(m.v, 0, 0); untouched(m.q, 1, TT_IN_WORDS);
        std::printf("layer %2d: QKV + MLP mismatches=%d\n", l, d);
        bad += d;
    }

    // 4. 批处理 n_patch = 3（不同输入、同一层），LOAD_W 与计算同一次调用，只选 K 与 V；期望值来自 tt_ref
    {
        const int L = 5;
        std::vector<short> in[3] = { load<short>("sim/golden/n6_real/x_embed_i16.bin", DN), gold(4, "x_out_i16.bin"), gold(10, "x_mid_i16.bin") };
        Bufs p;
        for (int i = 0; i < 3; ++i) p.put(i, in[i]);
        require(call(p, pkg, 3, L, TT_ENGINE_PROJ_K | TT_ENGINE_PROJ_V, TT_ENGINE_MODE_LOAD_W) == 0, "batch call");
        int d = 0;
        for (int i = 0; i < 3; ++i) {
            std::vector<short> xn(DN), rk(DN), rv(DN);
            std::vector<int32_t> st(2 * TT_N);
            tt_ref::normalize(in[i].data(), xn.data(), st.data(), TT_N);
            tt_ref::project(xn.data(), rk.data(), wall.data() + (size_t)(L * 4 + 1) * TT_NF, TT_N);
            tt_ref::project(xn.data(), rv.data(), wall.data() + (size_t)(L * 4 + 2) * TT_NF, TT_N);
            d += check_stats("batch stats", p.st, i, st.data());
            d += check_blk("batch k", p.k, i, rk);
            d += check_blk("batch v", p.v, i, rv);
        }
        untouched(p.q, 0, 0);
        std::printf("batch n_patch=3 (K+V, LOAD_W in same call): mismatches=%d\n", d);
        bad += d;
    }
    std::printf(bad ? "FAIL: %d mismatches\n" : "PASS tt_engine PROJ: bit-exact vs sim/golden/n6_real and tt_ref, batch, error codes\n", bad);
    return bad ? 1 : 0;
}
