// 生成整网引擎（D 阶段 HLS）对拍用的逐层黄金：走 tt_net.cpp（float32 胶水 + int16 层间）和 tt_hw_sim.cpp（整数投影）
// 这条与板上完全相同的数值路径。由 sim/gen_golden.py 编译并调用，不要手跑。
//
// 用法：dump_golden <root> <outdir> <N> <patch_f32.bin|synthetic>
//   N=6  ：patch 是预处理后的 (270,7,7) float32；pos_embed 用 model/data/pos_embed.bin
//   N=10 ：现网没有 N=10 的权重，token 与 pos_embed 用 sim/host/test_block_pipeline.cpp 同款合成数据
// 输出（全部小端，布局同 DDR：激活 [p*N+n]）：
//   patch_f32.bin  pos_embed_f32.bin  x_embed_i16.bin
//   L{l}_stats_qkv_i32.bin [2N]   L{l}_{q,k,v}_i16.bin [D*N]   L{l}_attn_f32.bin [N*N]（attn[n][c] 行主序）
//   L{l}_x_mid_i16.bin [D*N]（ctx 残差后）   L{l}_stats_mlp_i32.bin   L{l}_mlp_i16.bin   L{l}_x_out_i16.bin
//   logits_f32.bin [9]   meta.txt
#include "../../src/ps/tt_net.h"
#include "../../src/ps/tt_hw.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

template <class T> static std::vector<T> load(const std::string &path, size_t count) {
    FILE *f = std::fopen(path.c_str(), "rb");
    if (!f) { std::fprintf(stderr, "cannot open %s\n", path.c_str()); std::exit(1); }
    std::vector<T> v(count);
    if (std::fread(v.data(), sizeof(T), count, f) != count || std::fgetc(f) != EOF) {
        std::fprintf(stderr, "%s: size mismatch\n", path.c_str()); std::exit(1);
    }
    std::fclose(f);
    return v;
}

template <class T> static void save(const std::string &path, const T *data, size_t count) {
    FILE *f = std::fopen(path.c_str(), "wb");
    if (!f || std::fwrite(data, sizeof(T), count, f) != count) { std::fprintf(stderr, "cannot write %s\n", path.c_str()); std::exit(1); }
    std::fclose(f);
}

int main(int argc, char **argv) {
    if (argc != 5) { std::fprintf(stderr, "usage: dump_golden <root> <outdir> <N> <patch|synthetic>\n"); return 2; }
    const std::string root = argv[1], out = std::string(argv[2]) + "/";
    const int N = std::atoi(argv[3]);
    if (N != 6 && N != 10) { std::fprintf(stderr, "N must be 6 or 10\n"); return 2; }
    const size_t DN = (size_t)TT_D * N;
    const std::string data = root + "/model/data/";
    auto weights = load<int16_t>(data + "weights_all.bin", (size_t)TT_LAYERS * 4 * TT_NF);
    auto cls = load<float>(data + "cls_token.bin", TT_D);
    auto cw = load<float>(data + "classifier_w.bin", (size_t)TT_CLASSES * TT_D);
    auto cb = load<float>(data + "classifier_b.bin", TT_CLASSES);
    std::vector<float> pos, patch;
    if (std::strcmp(argv[4], "synthetic") == 0) {
        auto pos6 = load<float>(data + "pos_embed.bin", (size_t)TT_D * 6);
        pos.resize(DN); patch.resize((size_t)TT_D * (N - 1));
        for (size_t i = 0; i < pos.size(); ++i) pos[i] = pos6[i % pos6.size()] * 0.5f;
        for (size_t i = 0; i < patch.size(); ++i) patch[i] = std::sin((float)i * 0.017f);
    } else {
        if (N != 6) { std::fprintf(stderr, "real patch only for N=6\n"); return 2; }
        pos = load<float>(data + "pos_embed.bin", DN);
        patch = load<float>(argv[4], (size_t)270 * 49);
    }
    save(out + "patch_f32.bin", patch.data(), patch.size());
    save(out + "pos_embed_f32.bin", pos.data(), pos.size());

    TTNet net = { N, N - 1, weights.data(), cls.data(), pos.data(), cw.data(), cb.data() };
    std::vector<int16_t> x(DN), oq(DN), ok(DN), ov(DN);
    std::vector<int32_t> stats(TT_STATS_CAP);
    tt_embed(net, patch.data(), x.data());
    save(out + "x_embed_i16.bin", x.data(), DN);

    for (int l = 0; l < TT_LAYERS; l++) {
        const std::string L = out + "L" + std::to_string(l) + "_";
        const int16_t *w = weights.data() + (size_t)l * 4 * TT_NF;
        tt_hw_proj(x.data(), oq.data(), ok.data(), ov.data(), stats.data(), w, w + TT_NF, w + 2 * TT_NF, N, 3);
        save(L + "stats_qkv_i32.bin", stats.data(), (size_t)2 * N);
        save(L + "q_i16.bin", oq.data(), DN); save(L + "k_i16.bin", ok.data(), DN); save(L + "v_i16.bin", ov.data(), DN);
        tt_real attn[TT_NMAX][TT_NMAX];
        tt_scores(oq.data(), ok.data(), N, attn);
        std::vector<float> a((size_t)N * N);
        for (int n = 0; n < N; n++) for (int c = 0; c < N; c++) a[(size_t)n * N + c] = attn[n][c];
        save(L + "attn_f32.bin", a.data(), a.size());
        tt_ctx_residual(x.data(), attn, ov.data(), stats.data(), N);
        save(L + "x_mid_i16.bin", x.data(), DN);
        const int16_t *wm = w + 3 * TT_NF;
        tt_hw_proj(x.data(), oq.data(), ok.data(), ov.data(), stats.data(), wm, wm, wm, N, 1);
        save(L + "stats_mlp_i32.bin", stats.data(), (size_t)2 * N);
        save(L + "mlp_i16.bin", oq.data(), DN);
        tt_mlp_residual(x.data(), oq.data(), stats.data(), N);
        save(L + "x_out_i16.bin", x.data(), DN);
    }

    // 整体前向必须与逐段调用逐位相同，否则黄金不代表 tt_forward
    std::vector<int16_t> x2(DN), q2(DN), k2(DN), v2(DN);
    std::vector<int32_t> st2(TT_STATS_CAP);
    TTWork wk = { x2.data(), q2.data(), k2.data(), v2.data(), st2.data() };
    tt_real logits[TT_CLASSES];
    const int best = tt_forward(net, wk, patch.data(), logits);
    if (std::memcmp(x.data(), x2.data(), DN * sizeof(int16_t)) != 0) { std::fprintf(stderr, "stepwise x != tt_forward x\n"); return 1; }
    save(out + "logits_f32.bin", logits, TT_CLASSES);
    FILE *m = std::fopen((out + "meta.txt").c_str(), "w");
    std::fprintf(m, "N=%d\nD=%d\nlayers=%d\nclasses=%d\nDF=%d\nsource=%s\nargmax=%d\nbackend=%s\n",
                 N, TT_D, TT_LAYERS, TT_CLASSES, TT_DF, argv[4], best, tt_net_backend_name());
    std::fclose(m);
    std::printf("N=%d argmax=%d stepwise == tt_forward bitwise\n", N, best);
    return 0;
}
