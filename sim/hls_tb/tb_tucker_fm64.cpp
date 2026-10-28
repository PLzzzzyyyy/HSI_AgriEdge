// Explicit 64-bit AXI packing contract, golden N=6 and adversarial N=10 cases.
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <string>
#include "../../src/hls/tt_types.h"

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
static std::vector<short> load(const char *name, int count) {
    const std::string path = data_dir() + name;
    FILE *f = std::fopen(path.c_str(), "rb");
    require(f != 0, path.c_str());
    std::vector<short> result(count);
    require(std::fread(result.data(), sizeof(short), count, f) == (size_t)count, "short input");
    require(std::fgetc(f) == EOF, "unexpected extra input; golden must use N=6");
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
#ifdef TT_WT32
    // 1507 words hold exactly 3014 int16; one extra guard word must never be read.
    std::vector<wt_bus_t> result(TT_NF / 2 + 1, wt_bus_t("0xDEADBEEF"));
    for (int i = 0; i < TT_NF; ++i)
        result[i / 2].range((i % 2) * 16 + 15, (i % 2) * 16) = (unsigned short)raw[i];
#else
    std::vector<wt_bus_t> result(TT_NF);
    for (int i = 0; i < TT_NF; ++i) result[i].range(15, 0) = (unsigned short)raw[i];
#endif
    return result;
}
static void check(const char *name, const std::vector<fm_t> &got, const std::vector<short> &ref) {
    int bad = 0;
    for (size_t i = 0; i < ref.size(); ++i) {
        const short value = (short)got[i / 4].range((i % 4) * 16 + 15, (i % 4) * 16);
        if (value != ref[i]) {
            if (bad < 4) std::printf("%s[%zu] got=%d ref=%d\n", name, i, value, ref[i]);
            ++bad;
        }
    }
    for (size_t i = ref.size() / 4; i < got.size(); ++i) require(got[i] == sentinel(), "write beyond active output");
    std::printf("%s: %zu values; mismatches=%d; tail guard intact\n", name, ref.size(), bad);
    require(bad == 0, "output mismatch");
}
static void untouched(const std::vector<fm_t> &buffer) {
    for (size_t i = 0; i < buffer.size(); ++i) require(buffer[i] == sentinel(), "unused output was written");
}

int main() {
    const int count = TT_D * 6;
    std::vector<fm_t> in = pack(load("in_qkv.bin", count));
    std::vector<fm_t> saved = in;
    std::vector<fm_t> q(CAP + 1, sentinel()), k = q, v = q;
    std::vector<wt_bus_t> wq = weight(load("w_q.bin", TT_NF));
    std::vector<wt_bus_t> wk = weight(load("w_k.bin", TT_NF));
    std::vector<wt_bus_t> wv = weight(load("w_v.bin", TT_NF));
    tucker_proj(in.data(), q.data(), k.data(), v.data(), wq.data(), wk.data(), wv.data(), 6, 3);
    require(in == saved, "input modified");
    check("Q golden N=6", q, load("out_q.bin", count));
    check("K golden N=6", k, load("out_k.bin", count));
    check("V golden N=6", v, load("out_v.bin", count));

    in = pack(load("in_mlp.bin", count)); saved = in;
    q.assign(CAP + 1, sentinel()); k = q; v = q;
    std::vector<wt_bus_t> wm = weight(load("w_mlp.bin", TT_NF));
    tucker_proj(in.data(), q.data(), k.data(), v.data(), wm.data(), wk.data(), wv.data(), 6, 1);
    require(in == saved, "MLP input modified");
    check("MLP golden N=6", q, load("out_mlp.bin", count)); untouched(k); untouched(v);

    // N=10 signed full-range inputs and permutation factors. This exercises all
    // indices, 64-bit row crossings, the final odd spatial pair, and saturation.
    std::vector<short> raw(TT_D * 10), ref(raw.size());
    for (size_t i = 0; i < raw.size(); ++i) raw[i] = (short)((i * 251 + 32768) & 65535);
    std::vector<short> perm(TT_NF, 0);
    for (int a = 0; a < TT_W; ++a) perm[a * TT_W + (a + 1) % TT_W] = 16384;
    for (int b = 0; b < TT_W; ++b) perm[49 + b * TT_W + (b + 2) % TT_W] = 16384;
    for (int c = 0; c < TT_J; ++c) perm[98 + c * TT_J + (c + 3) % TT_J] = 16384;
    std::vector<wt_bus_t> wp = weight(perm);
    for (int a = 0; a < TT_W; ++a) for (int b = 0; b < TT_W; ++b)
        for (int c = 0; c < TT_J; ++c) for (int n = 0; n < 10; ++n) {
            const int dst = ((a * TT_W + b) * TT_J + c) * 10 + n;
            const int src = ((((a + 1) % TT_W) * TT_W + (b + 2) % TT_W) * TT_J + (c + 3) % TT_J) * 10 + n;
            ref[dst] = raw[src];
        }
    in = pack(raw); saved = in;
    q.assign(CAP + 1, sentinel()); k = q; v = q;
    tucker_proj(in.data(), q.data(), k.data(), v.data(), wp.data(), wp.data(), wp.data(), 10, 3);
    require(in == saved, "N=10 input modified");
    check("Q permutation N=10", q, ref); check("K permutation N=10", k, ref); check("V permutation N=10", v, ref);
    std::puts("PASS FM64: bit-exact golden + signed N=10 permutation, guards, unused outputs");
    return 0;
}
