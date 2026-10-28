// Host-only experiment for hardware round 4 (normalize+quant moved into the PL).
// normalize is computed with integer arithmetic exactly the way the PL would do it, and x can be stored as
// int16 Q3.12 between layers. Every other kernel is the production PS code (tt_net.cpp) and the bit-exact
// integer projection (tt_hw_sim.cpp). Driven by tools/exp_norm_fixed.py over the 4096-pixel block.
// Not part of the board build; never a board measurement.
//
// Integer normalize (per token n over p = 0..D-1), input xi[p*N+n] with F fractional bits:
//   S1 = Σ x, Sxx = Σ x² (exact)            var_num = D*Sxx - S1² = D*(D-1)*var_unbiased  (units 2^-2F)
//   mean_q24 = (S1 * 2^(24-F)) / D           C truncation toward zero (same as HLS ap_int '/')
//   inv = C / sqrt(var_num), C = sqrt(D*(D-1)) * 2^F     F=12: float32 (int64->float, sqrtf, fdiv), HLS-portable
//   d = x*2^(24-F) - mean_q24 (Q.24);  q = sat16((d * inv_q24 + 2^35) >> 36), inv_q24 = trunc(inv * 2^24)
//   stats for the PS residual: mean_f = (float)mean_q24 * 2^-24, inv_f = inv;  xn = (x - mean_f) * inv_f in float
#include "../../src/ps/tt_net.h"
#include "../../src/ps/tt_hw.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

typedef __int128 i128;

static void require(bool ok, const char *msg) {
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", msg); std::exit(1); }
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

struct NormStats { float mean[TT_NMAX], inv[TT_NMAX]; };

struct Stats {
    double max_abs_x[2 * TT_LAYERS + 1];         // after embed, then after each ctx residual / mlp residual
    double max_abs_s1, max_var_num, max_abs_mean_q24, max_abs_d, max_inv, min_inv;
    long long saturated, calls, elements, flips1, flips_gt1;
    Stats() { std::memset(this, 0, sizeof(*this)); min_inv = 1e30; }
};

static double dmax(double a, double b) { return a > b ? a : b; }

static void norm_int(const int64_t *xi, int F, int N, int16_t *q, NormStats &st, Stats &S) {
    const int64_t up = (int64_t)1 << (24 - F);
    for (int n = 0; n < N; n++) {
        int64_t s1 = 0; i128 sxx = 0;
        for (int p = 0; p < TT_D; p++) { const int64_t v = xi[p * N + n]; s1 += v; sxx += (i128)v * v; }
        const i128 var_num = (i128)TT_D * sxx - (i128)s1 * s1;
        require(var_num > 0, "zero-variance token");
        const int64_t mean_q24 = (s1 * up) / TT_D;
        float inv;
        if (F == 12) {
            require(var_num < ((i128)1 << 62), "var_num exceeds int64");
            const int64_t vn = (int64_t)var_num;
            static const float C = (float)(std::sqrt((double)TT_D * (double)(TT_D - 1)) * 4096.0);
            const float vf = (float)vn;
            inv = C / std::sqrt(vf);                                   // sqrtf + fdiv, IEEE single
        } else {
            inv = (float)(std::sqrt((double)TT_D * (double)(TT_D - 1)) * 16777216.0 / std::sqrt((double)var_num));
        }
        const int64_t inv_q24 = (int64_t)(inv * 16777216.0f);
        require(mean_q24 < ((int64_t)1 << 31) && mean_q24 >= -((int64_t)1 << 31), "mean_q24 exceeds int32");
        st.mean[n] = (float)(int32_t)mean_q24 * (1.0f / 16777216.0f);
        st.inv[n] = inv;
        S.max_abs_s1 = dmax(S.max_abs_s1, std::fabs((double)s1) * (double)up);   // in Q.24 units for both F
        S.max_var_num = dmax(S.max_var_num, (double)var_num * (double)up * (double)up);
        S.max_abs_mean_q24 = dmax(S.max_abs_mean_q24, std::fabs((double)mean_q24));
        S.max_inv = dmax(S.max_inv, inv); if (inv < S.min_inv) S.min_inv = inv;
        for (int p = 0; p < TT_D; p++) {
            const int64_t d = xi[p * N + n] * up - mean_q24;
            S.max_abs_d = dmax(S.max_abs_d, std::fabs((double)d));
            const int64_t prod = d * inv_q24;
            int64_t r = (prod + ((int64_t)1 << 35)) >> 36;                 // arithmetic shift = floor
            if (r > 32767) r = 32767;
            if (r < -32768) r = -32768;
            q[p * N + n] = (int16_t)r;
        }
    }
    S.calls++;
}

// Store x between layers. F=12: int16 Q3.12 with production tt_quant rounding, x keeps the dequantized value.
// F=24: x stays float; the PL model sees round-half-up Q8.24.
static void store_x(float *x, int16_t *xq, int64_t *xi, int count, int F, Stats &S, double &max_abs) {
    for (int i = 0; i < count; i++) max_abs = dmax(max_abs, std::fabs((double)x[i]));
    if (F == 12) {
        tt_quant(x, xq, count);
        for (int i = 0; i < count; i++) {
            if (xq[i] == 32767 || xq[i] == -32768) S.saturated++;
            x[i] = (float)xq[i] * (1.0f / TT_SCALE);
            xi[i] = xq[i];
        }
    } else {
        for (int i = 0; i < count; i++) {
            const double t = std::floor((double)x[i] * 16777216.0 + 0.5);
            require(std::fabs(t) < 2147483648.0, "x exceeds Q8.24");
            xi[i] = (int64_t)t;
        }
    }
}

struct Work {
    std::vector<float> x, xn, xn_ref;
    std::vector<int16_t> iq, iq_ref, oq, ok, ov, xq;
    std::vector<int64_t> xi;
    explicit Work(int n) : x(TT_D * n), xn(x.size()), xn_ref(x.size()), iq(x.size()), iq_ref(x.size()),
                           oq(x.size()), ok(x.size()), ov(x.size()), xq(x.size()), xi(x.size()) {}
};

// Same x through the production float32 normalize: count Q3.12 output differences against the integer version.
static void count_flips(Work &w, int N, Stats &S) {
    tt_normalize_quant(w.x.data(), w.xn_ref.data(), w.iq_ref.data(), N);
    for (size_t i = 0; i < w.iq.size(); i++) {
        const int d = std::abs((int)w.iq[i] - (int)w.iq_ref[i]);
        if (d == 1) S.flips1++; else if (d > 1) S.flips_gt1++;
    }
    S.elements += (long long)w.iq.size();
}

static int head(const TTNet &net, const float *x, int N, float *logits) {   // copy of tt_net.cpp::head
    int best = 0;
    for (int c = 0; c < TT_CLASSES; c++) {
        float s = net.cls_b[c];
        for (int p = 0; p < TT_D; p++) { float t = net.cls_w[c * TT_D + p] * x[p * N + 1]; s += t; }
        logits[c] = s;
        if (s > logits[best]) best = c;
    }
    return best;
}

static int forward_exp(const TTNet &net, Work &w, const float *patch, float *logits, int F, Stats &S) {
    const int N = net.N, DN = TT_D * N;
    NormStats st;
    tt_embed(net, patch, w.x.data());
    store_x(w.x.data(), w.xq.data(), w.xi.data(), DN, F, S, S.max_abs_x[0]);
    for (int l = 0; l < TT_LAYERS; l++) {
        const int16_t *wl = net.weights + (size_t)l * 4 * TT_NF;
        norm_int(w.xi.data(), F, N, w.iq.data(), st, S);
        count_flips(w, N, S);
        for (int i = 0; i < DN; i++) w.xn[i] = (w.x[i] - st.mean[i % N]) * st.inv[i % N];
        tt_hw_proj(w.iq.data(), w.oq.data(), w.ok.data(), w.ov.data(), wl, wl + TT_NF, wl + 2 * TT_NF, N, 3);
        tt_real attn[TT_NMAX][TT_NMAX];
        tt_scores(w.oq.data(), w.ok.data(), N, attn);
        tt_ctx_residual(w.xn.data(), attn, w.ov.data(), w.x.data(), N);
        store_x(w.x.data(), w.xq.data(), w.xi.data(), DN, F, S, S.max_abs_x[2 * l + 1]);

        norm_int(w.xi.data(), F, N, w.iq.data(), st, S);
        count_flips(w, N, S);
        for (int i = 0; i < DN; i++) w.xn[i] = (w.x[i] - st.mean[i % N]) * st.inv[i % N];
        const int16_t *wm = wl + 3 * TT_NF;
        tt_hw_proj(w.iq.data(), w.oq.data(), w.ok.data(), w.ov.data(), wm, wm, wm, N, 1);
        tt_mlp_residual(w.xn.data(), w.oq.data(), w.x.data(), DN);
        store_x(w.x.data(), w.xq.data(), w.xi.data(), DN, F, S, S.max_abs_x[2 * l + 2]);
    }
    return head(net, w.x.data(), N, logits);
}

int main(int argc, char **argv) {
    require(argc == 7, "usage: exp_norm_fixed ROOT PREFIX F FIRST COUNT SIDE");
    const std::string root = argv[1], prefix = argv[2];
    const int F = std::atoi(argv[3]), first = std::atoi(argv[4]), count = std::atoi(argv[5]), side = std::atoi(argv[6]);
    require(F == 12 || F == 24, "F must be 12 or 24");
    require(first >= 0 && count > 0 && side > 0 && first + count <= side * side, "pixel range");
    Model model(root);
    tt_clock = 0;
    const int rw = side + 6, pw = 270 * 49, N = model.net.N, DN = TT_D * N;
    const auto region = load<float>(root + "/model/data/block/region_f32.bin", (size_t)rw * rw * 270);
    Work w(N);
    std::vector<float> patch(pw), logits_exp((size_t)count * TT_CLASSES), logits_ref((size_t)count * TT_CLASSES);
    std::vector<float> rx(DN), rxn(DN);
    std::vector<int16_t> riq(DN), roq(DN), rok(DN), rov(DN);
    TTWork ref = { rx.data(), rxn.data(), riq.data(), roq.data(), rok.data(), rov.data() };
    Stats S;
    for (int i = 0; i < count; i++) {
        const int pixel = first + i;
        tt_patch_extract(region.data(), rw, pixel / side, pixel % side, patch.data());
        tt_forward(model.net, ref, patch.data(), logits_ref.data() + (size_t)i * TT_CLASSES);
        forward_exp(model.net, w, patch.data(), logits_exp.data() + (size_t)i * TT_CLASSES, F, S);
    }
    save(prefix + "_exp_logits_f32.bin", logits_exp);
    save(prefix + "_ref_logits_f32.bin", logits_ref);
    FILE *f = std::fopen((prefix + "_stats.txt").c_str(), "w");
    require(f != 0, "cannot create stats file");
    for (int s = 0; s < 2 * TT_LAYERS + 1; s++) std::fprintf(f, "max_abs_x_%d=%.9g\n", s, S.max_abs_x[s]);
    std::fprintf(f, "max_abs_s1_q24=%.17g\nmax_var_num_q48=%.17g\nmax_abs_mean_q24=%.17g\nmax_abs_d_q24=%.17g\n",
                 S.max_abs_s1, S.max_var_num, S.max_abs_mean_q24, S.max_abs_d);
    std::fprintf(f, "max_inv=%.9g\nmin_inv=%.9g\nsaturated=%lld\ncalls=%lld\nelements=%lld\nflips1=%lld\nflips_gt1=%lld\n",
                 S.max_inv, S.min_inv, S.saturated, S.calls, S.elements, S.flips1, S.flips_gt1);
    std::fclose(f);
    std::printf("done F=%d pixels %d..%d\n", F, first, first + count - 1);
    return 0;
}
