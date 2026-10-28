// 主机端整网测试：tt_net.cpp（float32，x86 上走标量 4 车道封装）+ tt_hw_sim.cpp，对 model/data/golden 的 PC double 定点参考。
// 编译（仓库根目录）：
//   D:\mingw64\bin\g++ -O2 -std=c++11 -o build/host/host_test.exe sim/host/host_test.cpp src/ps/tt_net.cpp src/ps/tt_hw_sim.cpp
// 运行：build\host\host_test.exe
#include "../../src/ps/tt_net.h"
#include "../../src/ps/tt_hw.h"
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>
#include <algorithm>
#include <chrono>

static std::string root() {
    std::string f = __FILE__;
    for (char &c : f) if (c == 92) c = '/';
    size_t p = f.rfind("/sim/host/");
    return p == std::string::npos ? "." : f.substr(0, p);
}

template <class T> static std::vector<T> load(const std::string &rel, size_t expect) {
    std::string path = root() + "/model/data/" + rel;
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) { printf("cannot open %s\n", path.c_str()); exit(1); }
    std::vector<T> v(expect);
    size_t got = fread(v.data(), sizeof(T), expect, f);
    fclose(f);
    if (got != expect) { printf("%s: expected %zu got %zu\n", rel.c_str(), expect, got); exit(1); }
    return v;
}

int main() {
    int N = 6;   // 非重叠模型；meta.txt 里有 N，这里简单起见读一下
    char model_name[64] = "unknown", pixel[64] = "unknown";
    {
        FILE *f = fopen((root() + "/model/data/golden/meta.txt").c_str(), "r");
        char line[512];
        while (f && fgets(line, sizeof line, f)) {
            sscanf(line, "N=%d", &N);
            sscanf(line, "model=%63s", model_name);
            sscanf(line, "pixel=%63s", pixel);
        }
        if (f) fclose(f);
    }
    if (N != 6 && N != 10) { printf("unsupported N=%d\n", N); return 1; }
    printf("model=%s pixel=%s N=%d; CPU software backend, float32 glue + PL-model normalize/projections, int16 x, tol=%g\n",
           model_name, pixel, N, (double)TT_LOGIT_TOL);
    const size_t DN = (size_t)TT_D * N;
    auto weights = load<int16_t>("weights_all.bin", (size_t)TT_LAYERS * 4 * TT_NF);
    auto cls = load<float>("cls_token.bin", TT_D);
    auto pos = load<float>("pos_embed.bin", DN);
    auto cw = load<float>("classifier_w.bin", (size_t)TT_CLASSES * TT_D);
    auto cb = load<float>("classifier_b.bin", TT_CLASSES);
    auto patch = load<float>("golden/patch_f32.bin", (size_t)270 * 49);
    auto ref_fixed = load<double>("golden/logits_fixed.bin", TT_CLASSES);
    auto ref_float = load<double>("golden/logits_float.bin", TT_CLASSES);
    auto layer_ref = load<double>("golden/layer_out_fixed.bin", (size_t)TT_LAYERS * DN);

    TTNet net = { N, N - 1, weights.data(), cls.data(), pos.data(), cw.data(), cb.data() };
    std::vector<int16_t> x(DN), oq(DN), ok(DN), ov(DN);
    std::vector<int32_t> stats(TT_STATS_CAP);
    TTWork wk = { x.data(), oq.data(), ok.data(), ov.data(), stats.data() };

    // 逐层对拍（layer_out_fixed 存的是每层输出 x，(N,7,7,54) 顺序 → 元素 (n,p) 在 n*D+p）
    // float32 vs double 的差逐层缓慢累积，量级 1e-4；不做逐位要求，只打印。
    tt_embed(net, patch.data(), wk.x);
    for (int l = 0; l < TT_LAYERS; l++) {
        tt_layer(net, wk, l);
        double md = 0, mx = 0;
        for (int n = 0; n < N; n++)
            for (int p = 0; p < TT_D; p++) {
                double r = layer_ref[(size_t)l * DN + (size_t)n * TT_D + p];
                double d = fabs((double)wk.x[p * N + n] / TT_SCALE - r);
                if (d > md) md = d;
                if (fabs(r) > mx) mx = fabs(r);
            }
        printf("layer %2d: max|x - ref| = %.3e   (max|ref| = %.2f)\n", l, md, mx);
    }
    tt_real logits[TT_CLASSES];
    // 完整前向预热一次；计时不包含读文件、逐层对照、打印或编译。
    tt_clock = 0;
    int best = tt_forward(net, wk, patch.data(), logits);
    double md = 0; int rb = 0;
    for (int c = 0; c < TT_CLASSES; c++) {
        double d = fabs(logits[c] - ref_fixed[c]); if (d > md) md = d;
        if (ref_fixed[c] > ref_fixed[rb]) rb = c;
        printf("class %d: PS %+9.5f  ref_fixed %+9.5f  ref_float %+9.5f\n", c, logits[c], ref_fixed[c], ref_float[c]);
    }
    printf("argmax PS=%d ref=%d, max|dlogit| vs ref_fixed = %.3e  -> %s\n", best, rb, md,
           (best == rb && md < TT_LOGIT_TOL) ? "PASS" : "FAIL");
    if (best != rb || md >= TT_LOGIT_TOL) return 1;

    const int runs = 10;
    double times[runs], sum = 0, max_error = 0;
    bool passed = true;
    for (int r = 0; r < runs; r++) {
        const auto start = std::chrono::steady_clock::now();
        best = tt_forward(net, wk, patch.data(), logits);
        const auto stop = std::chrono::steady_clock::now();
        times[r] = std::chrono::duration<double, std::milli>(stop - start).count();
        sum += times[r];
        bool run_pass = best == rb;
        for (int c = 0; c < TT_CLASSES; c++) {
            const double d = fabs(logits[c] - ref_fixed[c]);
            if (!std::isfinite(logits[c]) || !std::isfinite(ref_fixed[c]) || d >= TT_LOGIT_TOL) run_pass = false;
            if (d > max_error) max_error = d;
        }
        passed = passed && run_pass;
        printf("forward run %2d: %.3f ms, argmax=%d, %s\n", r + 1, times[r], best, run_pass ? "PASS" : "FAIL");
    }
    std::sort(times, times + runs);
    printf("CPU full forward: runs=%d, mean=%.3f ms, median=%.3f ms, min=%.3f ms, max=%.3f ms\n",
           runs, sum / runs, (times[runs / 2 - 1] + times[runs / 2]) / 2, times[0], times[runs - 1]);
    printf("Scope: embed + 12 layers + classifier; batch=1; one full warmup after layer checks; profiling off\n");
    printf("Excludes preprocessing, file I/O, validation, printing and compilation\n");
    printf("Timed forwards vs golden: max|dlogit|=%.3e -> %s\n", max_error, passed ? "PASS" : "FAIL");
    return passed ? 0 : 1;
}
