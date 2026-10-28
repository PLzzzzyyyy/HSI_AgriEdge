// v1.4 (TT_NORM_IN) testbench: un-normalized Q3.12 x in, on-chip token normalize + projection, stats out.
// Expected values come from src/ps/tt_ref_int.h (the same integer reference used by tt_hw_sim.cpp);
// the layer-0 stats are additionally checked against an independent Python replica (norm_stats_l0.bin).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <string>
#include "../../src/hls/tt_types.h"
#include "../../src/ps/tt_ref_int.h"

static const int CAP = TT_D * TT_NMAX / 4;
static void require(bool ok, const char *message) {
    if (!ok) { std::printf("FAIL: %s\n", message); std::exit(1); }
}
static std::string data_dir() {
    std::string f = __FILE__;
    for (size_t i = 0; i < f.size(); ++i) if (f[i] == '\\') f[i] = '/';
    const size_t pos = f.rfind("/sim/hls_tb/");
    if (pos != std::string::npos) return f.substr(0, pos) + "/model/data/golden/";
    return f.substr(0, f.rfind('/')) + "/../../model/data/golden/";
}
template <class T> static std::vector<T> load(const char *name, int count) {
    const std::string path = data_dir() + name;
    FILE *f = std::fopen(path.c_str(), "rb");
    require(f != 0, path.c_str());
    std::vector<T> result(count);
    require(std::fread(result.data(), sizeof(T), count, f) == (size_t)count, "short input");
    require(std::fgetc(f) == EOF, "unexpected extra input");
    std::fclose(f);
    return result;
}
static fm_t sentinel() { return fm_t("0x1234ABCD5678EF09"); }
static std::vector<fm_t> pack(const std::vector<short> &raw) {
    std::vector<fm_t> result(CAP + 1, sentinel());
    for (size_t i = 0; i < raw.size(); ++i)
        result[i / 4].range((i % 4) * 16 + 15, (i % 4) * 16) = (unsigned short)raw[i];
    return result;
}
static std::vector<wt_bus_t> weight(const std::vector<short> &raw) {
    std::vector<wt_bus_t> result(TT_NF / 2 + 1, wt_bus_t("0xDEADBEEF"));
    for (int i = 0; i < TT_NF; ++i)
        result[i / 2].range((i % 2) * 16 + 15, (i % 2) * 16) = (unsigned short)raw[i];
    return result;
}
static int check(const char *name, const std::vector<fm_t> &got, const std::vector<short> &ref) {
    int bad = 0;
    for (size_t i = 0; i < ref.size(); ++i) {
        const short value = (short)got[i / 4].range((i % 4) * 16 + 15, (i % 4) * 16);
        if (value != ref[i]) { if (bad < 4) std::printf("%s[%zu] got=%d ref=%d\n", name, i, value, ref[i]); ++bad; }
    }
    for (size_t i = ref.size() / 4; i < got.size(); ++i) require(got[i] == sentinel(), "write beyond active output");
    std::printf("%s: %zu values; mismatches=%d; tail guard intact\n", name, ref.size(), bad);
    return bad;
}
static void untouched(const std::vector<fm_t> &buffer) {
    for (size_t i = 0; i < buffer.size(); ++i) require(buffer[i] == sentinel(), "unused output was written");
}
static int check_stats(const char *name, const std::vector<fm_t> &got, const int32_t *ref, int n) {
    int bad = 0;
    for (int t = 0; t < n; ++t) {
        const int32_t mean = (int32_t)(uint32_t)got[t].range(31, 0), inv = (int32_t)(uint32_t)got[t].range(63, 32);
        if (mean != ref[2 * t] || inv != ref[2 * t + 1]) {
            std::printf("%s token %d: got mean=%d inv=%d ref mean=%d inv=%d\n", name, t, mean, inv, ref[2 * t], ref[2 * t + 1]);
            ++bad;
        }
    }
    for (size_t i = n; i < got.size(); ++i) require(got[i] == sentinel(), "stats written beyond n_tok");
    std::printf("%s: %d tokens; mismatches=%d\n", name, n, bad);
    return bad;
}

// Reference: normalize + up to three projections with the shared integer model
struct Ref {
    std::vector<short> q[3]; std::vector<int32_t> stats;
    Ref(const std::vector<short> &x, const std::vector<short> *w, int n, int n_proj) : stats(2 * TT_NMAX, 0) {
        std::vector<short> xn(x.size());
        tt_ref::normalize(x.data(), xn.data(), stats.data(), n);
        for (int p = 0; p < n_proj; ++p) { q[p].resize(x.size()); tt_ref::project(xn.data(), q[p].data(), w[p].data(), n); }
    }
};

static int run_case(const char *tag, const std::vector<short> &x, const std::vector<short> *w, int n, int n_proj,
                    const int32_t *python_stats = 0) {
    Ref ref(x, w, n, n_proj);
    std::vector<fm_t> in = pack(x), saved = in;
    std::vector<fm_t> q(CAP + 1, sentinel()), k = q, v = q, st(TT_NMAX + 1, sentinel());
    std::vector<wt_bus_t> wq = weight(w[0]), wk = weight(w[n_proj > 1 ? 1 : 0]), wv = weight(w[n_proj > 2 ? 2 : 0]);
    tucker_proj(in.data(), q.data(), k.data(), v.data(), st.data(), wq.data(), wk.data(), wv.data(), n, n_proj);
    require(in == saved, "input modified");
    int bad = 0;
    bad += check_stats(tag, st, ref.stats.data(), n);
    if (python_stats) bad += check_stats("  vs Python replica", st, python_stats, n);
    bad += check(tag, q, ref.q[0]);
    if (n_proj >= 2) bad += check(tag, k, ref.q[1]); else untouched(k);
    if (n_proj >= 3) bad += check(tag, v, ref.q[2]); else untouched(v);
    return bad;
}

int main() {
    int bad = 0;
    // Layer-0 golden pixel: x = quant(embed), Q/K/V projections; stats also checked against the Python replica.
    const int count = TT_D * 6;
    std::vector<short> x = load<short>("x_qkv_l0.bin", count);
    std::vector<short> w3[3] = { load<short>("w_q.bin", TT_NF), load<short>("w_k.bin", TT_NF), load<short>("w_v.bin", TT_NF) };
    std::vector<int32_t> py = load<int32_t>("norm_stats_l0.bin", 12);
    {   // normalized block must also match the Python replica bit for bit
        std::vector<short> xn(count), pyq = load<short>("norm_q_l0.bin", count);
        std::vector<int32_t> s(2 * TT_NMAX);
        tt_ref::normalize(x.data(), xn.data(), s.data(), 6);
        int d = 0; for (int i = 0; i < count; ++i) d += xn[i] != pyq[i];
        std::printf("tt_ref::normalize vs Python replica: %d mismatches\n", d); bad += d;
    }
    bad += run_case("QKV golden-x N=6", x, w3, 6, 3, py.data());
    std::vector<short> wm[1] = { load<short>("w_mlp.bin", TT_NF) };
    bad += run_case("MLP golden-x N=6", x, wm, 6, 1);

    // N=10 adversarial: full-range signed values, a constant token (zero variance -> inv clamp), a tiny-variance token.
    std::vector<short> raw(TT_D * 10);
    for (size_t i = 0; i < raw.size(); ++i) raw[i] = (short)((i * 251 + 32768) & 65535);
    for (int p = 0; p < TT_D; ++p) { raw[p * 10 + 3] = 1234; raw[p * 10 + 7] = (short)(5000 + (p % 3)); }
    std::vector<short> perm(TT_NF, 0);
    for (int a = 0; a < TT_W; ++a) perm[a * TT_W + (a + 1) % TT_W] = 16384;
    for (int b = 0; b < TT_W; ++b) perm[49 + b * TT_W + (b + 2) % TT_W] = 16384;
    for (int c = 0; c < TT_J; ++c) perm[98 + c * TT_J + (c + 3) % TT_J] = 16384;
    std::vector<short> wp[3] = { perm, w3[1], w3[2] };
    bad += run_case("N=10 full-range + clamp", raw, wp, 10, 3);
    std::printf(bad ? "FAIL: %d mismatches\n" : "PASS NORM_IN: bit-exact stats + Q/K/V/MLP vs tt_ref, Python replica, N=10 clamp/saturation\n", bad);
    return bad ? 1 : 0;
}
