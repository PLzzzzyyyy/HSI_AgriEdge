// Host-only regression: defer the real integer projection until wait().
// Built/run by tools/test_block_pipeline.py; no board timing is measured here.
#include "../../src/ps/tt_net.h"
#include "../../src/ps/tt_hw.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

void tt_ps_proj(const int16_t *, int16_t *, int16_t *, int16_t *, int32_t *,
                const int16_t *, const int16_t *, const int16_t *, int, int);

static void require(bool value, const char *message) {
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}

template <class T> static std::vector<T> load(const std::string &path, size_t count) {
    FILE *f = std::fopen(path.c_str(), "rb");
    if (!f) { std::fprintf(stderr, "cannot open %s\n", path.c_str()); std::exit(1); }
    std::vector<T> result(count);
    require(std::fread(result.data(), sizeof(T), count, f) == count, "short input file");
    require(std::fgetc(f) == EOF, "unexpected trailing input data");
    std::fclose(f);
    return result;
}

template <class T> static void save(const std::string &path, const std::vector<T> &data) {
    FILE *f = std::fopen(path.c_str(), "wb");
    require(f != 0, "cannot create output file");
    require(std::fwrite(data.data(), sizeof(T), data.size(), f) == data.size(), "short output write");
    require(std::fclose(f) == 0, "output close failed");
}

struct Pending {
    bool busy;
    int n, projections;
    const int16_t *in, *w[3];
    int16_t *out[3]; int32_t *st;
    std::vector<int16_t> saved_in, saved_w[3], saved_out[3];
} pending = {};
static int starts = 0, waits = 0, qkv_starts = 0, mlp_starts = 0;

int tt_hw_init() { return 0; }
void tt_hw_proj_start(const int16_t *in, int16_t *oq, int16_t *ok, int16_t *ov, int32_t *st,
                      const int16_t *wq, const int16_t *wk, const int16_t *wv,
                      int n, int projections) {
    require(!pending.busy, "second start while projection is pending");
    require(n == 6 || n == 10, "unsupported token count");
    require(projections == 1 || projections == 3, "unexpected projection count");
    pending.busy = true; pending.n = n; pending.projections = projections;
    pending.in = in; pending.st = st; pending.saved_in.assign(in, in + TT_D * n);
    pending.w[0] = wq; pending.w[1] = wk; pending.w[2] = wv;
    pending.out[0] = oq; pending.out[1] = ok; pending.out[2] = ov;
    for (int p = 0; p < projections; ++p) {
        pending.saved_w[p].assign(pending.w[p], pending.w[p] + TT_NF);
        pending.saved_out[p].assign(pending.out[p], pending.out[p] + TT_D * n);
    }
    ++starts;
    if (projections == 3) ++qkv_starts; else ++mlp_starts;
}

void tt_hw_proj_wait() {
    require(pending.busy, "wait without a pending projection");
    require(std::memcmp(pending.in, pending.saved_in.data(), TT_D * pending.n * sizeof(int16_t)) == 0,
            "pending projection input modified before wait");
    for (int p = 0; p < pending.projections; ++p) {
        require(std::memcmp(pending.w[p], pending.saved_w[p].data(), TT_NF * sizeof(int16_t)) == 0,
                "pending projection weights modified before wait");
        require(std::memcmp(pending.out[p], pending.saved_out[p].data(), TT_D * pending.n * sizeof(int16_t)) == 0,
                "pending projection output modified before wait");
    }
    tt_ps_proj(pending.in, pending.out[0], pending.out[1], pending.out[2], pending.st,
               pending.w[0], pending.w[1], pending.w[2], pending.n, pending.projections);
    pending.busy = false;
    ++waits;
}

void tt_hw_proj(const int16_t *in, int16_t *oq, int16_t *ok, int16_t *ov, int32_t *st,
                const int16_t *wq, const int16_t *wk, const int16_t *wv, int n, int projections) {
    tt_hw_proj_start(in, oq, ok, ov, st, wq, wk, wv, n, projections);
    tt_hw_proj_wait();
}

struct Work {
    std::vector<int16_t> x, oq, ok, ov;
    std::vector<int32_t> st;
    TTWork work;
    explicit Work(int n) : x(TT_D * n), oq(x.size()), ok(x.size()), ov(x.size()), st(TT_STATS_CAP),
                          work{x.data(), oq.data(), ok.data(), ov.data(), st.data()} {}
};

struct Model {
    std::vector<int16_t> weights;
    std::vector<float> cls, pos, cw, cb;
    TTNet net;
    explicit Model(const std::string &root) :
        weights(load<int16_t>(root + "/model/data/weights_all.bin", TT_LAYERS * 4 * TT_NF)),
        cls(load<float>(root + "/model/data/cls_token.bin", TT_D)),
        pos(load<float>(root + "/model/data/pos_embed.bin", TT_D * 6)),
        cw(load<float>(root + "/model/data/classifier_w.bin", TT_CLASSES * TT_D)),
        cb(load<float>(root + "/model/data/classifier_b.bin", TT_CLASSES)),
        net{6, 5, weights.data(), cls.data(), pos.data(), cw.data(), cb.data()} {}
};

static void compare_pair(const TTNet &net, const float *pa, const float *pb,
                         Work &a, Work &b, std::vector<float> &logits, size_t offset) {
    tt_real sa[TT_CLASSES], sb[TT_CLASSES], la[TT_CLASSES], lb[TT_CLASSES];
    int ba = tt_forward(net, a.work, pa, sa), bb = tt_forward(net, b.work, pb, sb);
    require(!pending.busy, "sequential forward left a pending projection");
    const auto xa = a.x, xb = b.x;
    const int before = starts, q_before = qkv_starts, m_before = mlp_starts, wait_before = waits;
    int actual_a = -1, actual_b = -1;
    tt_forward_pair(net, a.work, b.work, pa, pb, la, lb, &actual_a, &actual_b);
    require(!pending.busy && starts - before == 48 && waits - wait_before == 48,
            "pair must finish all 48 projections");
    require(qkv_starts - q_before == 24 && mlp_starts - m_before == 24, "pair projection routing");
    require(actual_a == ba && actual_b == bb, "pair argmax differs from sequential");
    require(std::memcmp(sa, la, sizeof(sa)) == 0 && std::memcmp(sb, lb, sizeof(sb)) == 0,
            "pair logits differ bitwise from sequential");
    require(std::memcmp(a.x.data(), xa.data(), xa.size() * sizeof(int16_t)) == 0 &&
            std::memcmp(b.x.data(), xb.data(), xb.size() * sizeof(int16_t)) == 0,
            "pair final activations differ bitwise from sequential");
    for (int c = 0; c < TT_CLASSES; ++c) {
        require(std::isfinite(la[c]) && std::isfinite(lb[c]), "non-finite logits");
        logits[offset * TT_CLASSES + c] = la[c];
        logits[(offset + 1) * TT_CLASSES + c] = lb[c];
    }
}

int main(int argc, char **argv) {
    require(argc == 4 || argc == 7, "usage: test_block_pipeline --smoke ROOT PREFIX | --block ROOT PREFIX FIRST COUNT SIDE");
    const std::string mode = argv[1], root = argv[2], prefix = argv[3];
    Model model(root);
    tt_clock = 0;
    if (mode == "--smoke") {
        require(argc == 4, "smoke arguments");
        const int side = 64, rw = side + 6, pw = 270 * 49;
        const auto region = load<float>(root + "/model/data/block/region_f32.bin", rw * rw * 270);
        const int coords[][2] = {{0, 0}, {0, 63}, {63, 0}, {63, 63}, {32, 32}, {5, 7}, {17, 51}, {47, 9}, {31, 32}};
        std::vector<float> patches(9 * pw), logits(2 * TT_CLASSES);
        for (int i = 0; i < 9; ++i)
            tt_patch_extract(region.data(), rw, coords[i][0], coords[i][1], patches.data() + i * pw);
        save(prefix + "_patches_f32.bin", patches);
        Work a(6), b(6);
        compare_pair(model.net, patches.data(), patches.data() + pw, a, b, logits, 0);
        std::printf("PASS host N=6 real model: two different patches, pair == sequential bitwise, 48 deferred projections\n");
        // Exercise the N=10 schedule with explicitly synthetic, sufficiently long token inputs.
        std::vector<float> pos10(TT_D * 10), pa(TT_D * 9), pb(pa.size());
        for (size_t i = 0; i < pos10.size(); ++i) pos10[i] = model.pos[i % model.pos.size()] * 0.5f;
        for (size_t i = 0; i < pa.size(); ++i) {
            pa[i] = std::sin(static_cast<float>(i) * 0.017f);
            pb[i] = std::cos(static_cast<float>(i) * 0.023f) + 0.2f;
        }
        TTNet net10 = model.net; net10.N = 10; net10.seq = 9; net10.pos_embed = pos10.data();
        Work c(10), d(10);
        compare_pair(net10, pa.data(), pb.data(), c, d, logits, 0);
        std::printf("PASS host N=10 synthetic tokens: pair == sequential bitwise, 48 deferred projections\n");
        std::printf("PASS pending inputs/weights/outputs unchanged until wait; no pending operation remains\n");
        return 0;
    }
    require(mode == "--block" && argc == 7, "block arguments");
    const int first = std::atoi(argv[4]), count = std::atoi(argv[5]), side = std::atoi(argv[6]);
    require(first >= 0 && count > 0 && count % 2 == 0 && side > 0 && first + count <= side * side, "block range");
    const int rw = side + 6, pw = 270 * 49;
    const auto region = load<float>(root + "/model/data/block/region_f32.bin", rw * rw * 270);
    Work a(6), b(6);
    std::vector<float> pa(pw), pb(pw), logits(count * TT_CLASSES);
    for (int i = 0; i < count; i += 2) {
        const int pixel = first + i;
        tt_patch_extract(region.data(), rw, pixel / side, pixel % side, pa.data());
        tt_patch_extract(region.data(), rw, (pixel + 1) / side, (pixel + 1) % side, pb.data());
        compare_pair(model.net, pa.data(), pb.data(), a, b, logits, i);
    }
    save(prefix + "_host_logits_f32.bin", logits);
    std::printf("PASS host pixels %d..%d: sequential == pair bitwise; deferred projection ownership checks\n", first, first + count - 1);
    return 0;
}
