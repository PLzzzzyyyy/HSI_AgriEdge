// Offline reference: exactly the 2026-10-09 ROI, no driver/MMIO or golden replay.
#define main unused_engine_golden_main
#include "engine_ref.cpp"
#undef main
#include "../../src/ps/tt_net.h"
#include "../../src/ps/tt_hw.h"
#include <limits>
static void need(bool ok, const char *why) {
    if (!ok) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(1); }
}
// Link-only traps for unused routines in the unchanged tt_net.cpp.
void tt_hw_proj_start(const int16_t *, int16_t *, int16_t *, int16_t *, int32_t *,
                      const int16_t *, const int16_t *, const int16_t *, int, int) {
    need(false, "forbidden legacy driver");
}
void tt_hw_proj_wait() { need(false, "forbidden legacy wait"); }
template<class T> static void save(const std::string &p, const std::vector<T> &v) {
    FILE *f = std::fopen(p.c_str(), "wb"); need(f != nullptr, "open output");
    need(std::fwrite(v.data(), sizeof(T), v.size(), f) == v.size(), "write output");
    need(std::fclose(f) == 0, "close output");
}
static std::vector<float> floats(const std::string &p, size_t n) {
    auto b = read_file(p); need(b.size() == n * 4, "float file size");
    std::vector<float> v(n); std::memcpy(v.data(), b.data(), b.size()); return v;
}
int main(int argc, char **argv) {
    need(argc == 3, "usage: reference scene_dir output_dir");
    const std::string scene = argv[1], out = argv[2], weights = scene + "/weights/v2/";
    auto cls = floats(weights + "cls_token.bin", D);
    auto pos = floats(weights + "pos_embed.bin", D * N);
    // Read only the union of 15 windows, retaining the actual row stride 406.
    std::vector<float> cube(9 * 406 * 270, std::numeric_limits<float>::quiet_NaN());
    FILE *f = std::fopen((scene + "/cube_f32.bin").c_str(), "rb");
    need(f != nullptr, "open cube");
    for (int row = 0; row < 9; ++row) {
        need(std::fseek(f, row * 406 * 270 * 4, SEEK_SET) == 0, "seek cube row");
        need(std::fread(cube.data() + row * 406 * 270, 4, 11 * 270, f) == 11 * 270, "read ROI union");
    }
    need(std::fclose(f) == 0, "close cube");
    init_consts(); const Pkg pkg = load_pkg(weights + "weights_engine.bin");
    need(pkg.num == 16 && pkg.ncls == 9, "LongKou W16A18 only"); set_num(pkg.num);
    const TTNet net = {6, 5, nullptr, cls.data(), pos.data(), nullptr, nullptr};
    std::vector<float> patches(15 * PN);
    std::vector<int16_t> inputs(15 * TT_ENGINE_IN_STRIDE / 2, 0);
    std::vector<int32_t> logits(15 * 32, 0);
    std::vector<uint32_t> words(15); std::vector<i64> x(D * N);
    for (int i = 0; i < 15; ++i) {
        float *patch = patches.data() + i * PN;
        int16_t *input = inputs.data() + i * (TT_ENGINE_IN_STRIDE / 2);
        tt_patch_extract(cube.data(), 406, i / 5, i % 5, patch);
        for (int j = 0; j < PN; ++j) need(std::isfinite(patch[j]), "finite patch");
        tt_embed(net, patch, input);
        // Entry A: sign extend int16 Q3.12. Never call front() or the old main.
        for (int j = 0; j < D * N; ++j) x[j] = input[j];
        const Out r = run(pkg, x.data(), "");
        for (int c = 0; c < pkg.ncls; ++c) logits[i * 32 + c] = (int32_t)r.logits[c];
        words[i] = ((uint32_t)r.conf << 16) | (uint32_t)r.label;
        std::printf("REF x=%d y=%d class_word=%08X\n", i % 5, i / 5, words[i]);
    }
    save(out + "/patches_f32.bin", patches); save(out + "/inputs_q312_stride31808.bin", inputs);
    save(out + "/logits_q16_i32.bin", logits); save(out + "/class_u32.bin", words);
    std::puts("REFERENCE_15_DONE (offline C++, not a board run)"); return 0;
}
