// tucker_proj 的 C 测试平台：读 model/data/golden 的黄金向量，要求逐位一致。
// 用法：vitis_hls -f build/hls/run_variant.tcl（TT_HLS_STAGE=synth 先跑 csim 再 csynth）
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <string>
#include "../../src/hls/tt_types.h"

// csim 的运行目录在 tt_prj/<sol>/csim/build，相对路径不可靠；由本文件位置推出仓库根目录
static std::string golden_dir() {
    std::string f = __FILE__;                          // 绝对或相对（csim 里是相对 solution 目录的路径）
    for (char &c : f) if (c == 92) c = '/';            // 92 = 反斜杠
    size_t p = f.rfind("/sim/hls_tb/");
    if (p != std::string::npos) return f.substr(0, p) + "/model/data/golden/";
    size_t d = f.rfind('/');
    std::string dir = (d == std::string::npos) ? "." : f.substr(0, d);
    return dir + "/../../model/data/golden/";         // sim/hls_tb/ -> sim/ -> 仓库根
}
static const std::string GOLDEN = golden_dir();

static std::vector<short> read_i16(const std::string &name, size_t expect) {
    std::string path = GOLDEN + name;
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) { printf("cannot open %s\n", path.c_str()); exit(1); }
    std::vector<short> v(expect);
    size_t got = fread(v.data(), sizeof(short), expect, f);
    fclose(f);
    if (got != expect) { printf("%s: expected %zu got %zu\n", name.c_str(), expect, got); exit(1); }
    return v;
}

static int read_meta_N() {
    std::string path = GOLDEN + "meta.txt";
    FILE *f = fopen(path.c_str(), "r");
    if (!f) { printf("cannot open meta.txt\n"); exit(1); }
    char line[512]; int N = -1;
    while (fgets(line, sizeof line, f)) if (sscanf(line, "N=%d", &N) == 1) break;
    fclose(f);
    if (N <= 0) { printf("N not found in meta.txt\n"); exit(1); }
    return N;
}

// raw int16 <-> ap_fixed：同一段比特的两种解释，与 PS 端 short + SCALE 一致
static void to_fixed(const std::vector<short> &src, std::vector<data_t> &dst) {
    dst.resize(src.size());
    for (size_t i = 0; i < src.size(); i++) { data_t t; t.range(15, 0) = src[i]; dst[i] = t; }
}
static void to_wt(const std::vector<short> &src, std::vector<wt_t> &dst) {
    dst.resize(src.size());
    for (size_t i = 0; i < src.size(); i++) { wt_t t; t.range(15, 0) = src[i]; dst[i] = t; }
}

static int compare(const char *tag, const std::vector<data_t> &got, const std::vector<short> &exp) {
    int bad = 0, maxd = 0;
    for (size_t i = 0; i < exp.size(); i++) {
        short g = (short)got[i].range(15, 0);
        int d = abs((int)g - (int)exp[i]);
        if (d) { if (bad < 5) printf("  %s[%zu]: got %d expected %d\n", tag, i, g, exp[i]); bad++; }
        if (d > maxd) maxd = d;
    }
    printf("%s: %zu elements, mismatches %d, max |diff| %d LSB\n", tag, exp.size(), bad, maxd);
    return bad;
}

int main() {
    const int N = read_meta_N();
    const size_t DN = (size_t)TT_D * N;
    printf("N=%d, block=%zu elements\n", N, DN);

    // ★ 数组长度必须 >= m_axi 的 depth（26460），cosim 包装器按 depth 拷贝端口内容，短了会踩堆
    const size_t CAP = (size_t)TT_D * TT_NMAX;
    std::vector<data_t> in, oq(CAP), ok(CAP), ov(CAP), om(CAP), dk(CAP), dv(CAP);
    std::vector<wt_t> wq, wk, wv, wm;
    to_fixed(read_i16("in_qkv.bin", DN), in); in.resize(CAP);
    to_wt(read_i16("w_q.bin", TT_NF), wq);
    to_wt(read_i16("w_k.bin", TT_NF), wk);
    to_wt(read_i16("w_v.bin", TT_NF), wv);

    // 调用 1：QKV 三投影
    tucker_proj(in.data(), oq.data(), ok.data(), ov.data(), wq.data(), wk.data(), wv.data(), N, 3);
    int bad = 0;
    bad += compare("Q", oq, read_i16("out_q.bin", DN));
    bad += compare("K", ok, read_i16("out_k.bin", DN));
    bad += compare("V", ov, read_i16("out_v.bin", DN));

    // 调用 2：MLP 单投影（out_k/out_v 与 w_k/w_v 传占位，n_proj=1 时不访问）
    std::vector<data_t> in2;
    to_fixed(read_i16("in_mlp.bin", DN), in2); in2.resize(CAP);
    to_wt(read_i16("w_mlp.bin", TT_NF), wm);
    tucker_proj(in2.data(), om.data(), dk.data(), dv.data(), wm.data(), wk.data(), wv.data(), N, 1);
    bad += compare("MLP", om, read_i16("out_mlp.bin", DN));

    printf(bad ? "FAIL: %d mismatches\n" : "PASS: bit-exact\n", bad);
    return bad ? 1 : 0;
}
