// M2 板上驱动 src/ps/tt_hw_engine.cpp 的主机测试：驱动 + HLS C 模型（xil_stubs/xtt_engine_model.cpp）走与板上相同的
// 调用路径（tt_hw_switch → tt_pl_*，32 位寄存器地址），对 sim/golden/n6_real 逐位：12 层逐段（stats / q / k / v / x_mid /
// mlp / x_out）、tt_forward 的 logits、tt_forward_pair、PS ↔ PL 切换、单投影 K、拒绝非法调用。
// 编译与运行都在仓库根（黄金向量按 __FILE__ 定位，相对路径时相对当前目录）：
// D:/mingw64/bin/g++ -O2 -std=c++14 -ffp-contract=off -include array -DTT_HW_RUNTIME_SWITCH -DTT_DB=16 -DTT_K3=7
//     -I sim/host/xil_stubs -I src/ps -I src/hls -I D:/xilinx/Vitis_HLS/2020.2/include
//     sim/host/test_hw_engine.cpp sim/host/xil_stubs/xtt_engine_model.cpp src/ps/tt_hw_engine.cpp src/ps/tt_hw_sim.cpp
//     src/ps/tt_hw_switch.cpp src/ps/tt_net.cpp src/ps/tt_data.c src/hls/tt_engine.cpp
//     -Wl,--image-base=0x10000000 -Wl,--disable-dynamicbase -o build/host/test_hw_engine.exe
// 地址：IP 寄存器是 32 位，缓冲用静态数组、映像基址放到 4 GB 以下，与板上一样按 (u32) 传地址。
#include "tt_net.h"
#include "tt_hw.h"
#include "tt_hw_switch.h"
#include "tt_hw_engine.h"
#include "tt_data.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

bool xtt_model_busy();
static int flushes_all, flush_ranges, invalidates;
static void idle(const char *what) {
    if (xtt_model_busy()) { std::printf("DRIVER VIOLATION: %s while engine busy\n", what); std::abort(); }
}
void Xil_DCacheFlush() { idle("Xil_DCacheFlush"); flushes_all++; }
void Xil_DCacheFlushRange(INTPTR, u32) { idle("Xil_DCacheFlushRange"); flush_ranges++; }
void Xil_DCacheInvalidateRange(INTPTR, u32) { idle("Xil_DCacheInvalidateRange"); invalidates++; }
int xil_printf(const char *fmt, ...) { va_list a; va_start(a, fmt); int n = std::vprintf(fmt, a); va_end(a); return n; }

static const int N = 6, DN = TT_D * N;
enum { CAP = (DN + 31) & ~31 };
#define AL alignas(64)
AL static int16_t xa[CAP], qa[CAP], ka[CAP], va[CAP], xb[CAP], qb[CAP], kb[CAP], vb[CAP];
AL static int32_t sa[TT_STATS_CAP], sb[TT_STATS_CAP];
AL static int16_t w_file[TT_LAYERS * 4 * TT_NF];
AL static int16_t w_other[TT_NF];

static int failures = 0;
static void check(bool ok, const char *what) {
    std::printf("%-58s %s\n", what, ok ? "PASS" : "FAIL");
    if (!ok) failures++;
}
static std::string golden() {
    std::string f = __FILE__;
    for (char &c : f) if (c == '\\') c = '/';
    return f.substr(0, f.rfind("sim/host/")) + "sim/golden/n6_real/";
}
template <class T> static std::vector<T> load(const std::string &name, size_t count) {
    const std::string p = golden() + name;
    FILE *f = std::fopen(p.c_str(), "rb");
    if (!f) { std::printf("cannot open %s\n", p.c_str()); std::exit(1); }
    std::vector<T> v(count);
    if (std::fread(v.data(), sizeof(T), count, f) != count || std::fgetc(f) != EOF) { std::printf("%s: size mismatch\n", p.c_str()); std::exit(1); }
    std::fclose(f);
    return v;
}
template <class T> static int diff(const T *a, const std::vector<T> &b) {
    int d = 0;
    for (size_t i = 0; i < b.size(); i++) d += std::memcmp(&a[i], &b[i], sizeof(T)) != 0;
    return d;
}

int main() {
    // 0. 地址都在低 4 GB（否则 32 位寄存器截断，测试无意义）
    const unsigned long long hi = ((uintptr_t)xa | (uintptr_t)xb | (uintptr_t)w_file | (uintptr_t)tt_weights) >> 32;
    if (hi) { std::printf("buffers above 4 GB: link with -Wl,--image-base=0x10000000 -Wl,--disable-dynamicbase\n"); return 1; }

    // 1. 网络参数全部取黄金向量用的那一份（weights 由 model/data/weights_all.bin 生成 tt_data.c，核对一致）
    const std::string root = golden() + "../../../model/data/";
    {
        FILE *f = std::fopen((root + "weights_all.bin").c_str(), "rb");
        if (!f || std::fread(w_file, sizeof(int16_t), TT_LAYERS * 4 * TT_NF, f) != (size_t)TT_LAYERS * 4 * TT_NF) { std::printf("cannot read weights_all.bin\n"); return 1; }
        std::fclose(f);
    }
    check(std::memcmp(w_file, tt_weights, sizeof(w_file)) == 0, "tt_data.c tt_weights == model/data/weights_all.bin");
    auto patch = load<float>("patch_f32.bin", 270 * 49);
    auto pos = load<float>("pos_embed_f32.bin", DN);
    auto logits_ref = load<float>("logits_f32.bin", TT_CLASSES);
    auto cls = load<float>("../../../model/data/cls_token.bin", TT_D);
    auto cw = load<float>("../../../model/data/classifier_w.bin", (size_t)TT_CLASSES * TT_D);
    auto cb = load<float>("../../../model/data/classifier_b.bin", TT_CLASSES);
    TTNet net = { N, N - 1, w_file, cls.data(), pos.data(), cw.data(), cb.data() };

    // 2. 选 PL：tt_pl_init 装载 tt_weights，版本核对；再显式换成 w_file（驱动此后按 w_file 的偏移算层号）
    check(tt_hw_select(TT_BACKEND_PL) == 0, "select PL (init + LOAD_W tt_weights)");
    const unsigned r0 = tt_eng_last_ret();
    check((r0 & 0xFF) == 0 && ((r0 >> 8) & 0xFF) == 3 && ((r0 >> 24) & 0xFF) == 16, "LOAD_W return: err 0, contract v3, 16-bit");
    check(tt_eng_load_weights(w_file, TT_CLASSES) == 0, "tt_eng_load_weights(weights_all.bin)");

    // 3. 12 层逐段，对黄金逐位
    tt_embed(net, patch.data(), xa);
    int bad = diff(xa, load<int16_t>("x_embed_i16.bin", DN));
    for (int l = 0; l < TT_LAYERS; l++) {
        const std::string L = "L" + std::to_string(l) + "_";
        const int16_t *w = w_file + (size_t)l * 4 * TT_NF;
        tt_hw_proj(xa, qa, ka, va, sa, w, w + TT_NF, w + 2 * TT_NF, N, 3);
        int b = diff(sa, load<int32_t>(L + "stats_qkv_i32.bin", 2 * N)) + diff(qa, load<int16_t>(L + "q_i16.bin", DN)) +
                diff(ka, load<int16_t>(L + "k_i16.bin", DN)) + diff(va, load<int16_t>(L + "v_i16.bin", DN));
        tt_real attn[TT_NMAX][TT_NMAX];
        tt_scores(qa, ka, N, attn);
        tt_ctx_residual(xa, attn, va, sa, N);
        b += diff(xa, load<int16_t>(L + "x_mid_i16.bin", DN));
        const int16_t *wm = w + 3 * TT_NF;
        tt_hw_proj(xa, qa, ka, va, sa, wm, wm, wm, N, 1);
        b += diff(sa, load<int32_t>(L + "stats_mlp_i32.bin", 2 * N)) + diff(qa, load<int16_t>(L + "mlp_i16.bin", DN));
        tt_mlp_residual(xa, qa, sa, N);
        b += diff(xa, load<int16_t>(L + "x_out_i16.bin", DN));
        if (b) std::printf("  layer %d: %d mismatching values\n", l, b);
        bad += b;
    }
    check(bad == 0, "12 layers stepwise (stats/q/k/v/x_mid/mlp/x_out) bit-exact");

    // 4. tt_forward 的 logits 逐位
    TTWork wa = { xa, qa, ka, va, sa }, wb = { xb, qb, kb, vb, sb };
    tt_real la[TT_CLASSES], lb[TT_CLASSES];
    int best = tt_forward(net, wa, patch.data(), la);
    check(diff(la, logits_ref) == 0 && best == 0, "tt_forward logits bit-exact, argmax 0");

    // 5. 双 patch 流水（PL 算一个时 PS 算另一个）
    int ba = -1, bb = -1;
    tt_forward_pair(net, wa, wb, patch.data(), patch.data(), la, lb, &ba, &bb);
    check(diff(la, logits_ref) == 0 && diff(lb, logits_ref) == 0 && ba == 0 && bb == 0, "tt_forward_pair both logits bit-exact");

    // 6. 切到纯 PS 再切回 PL（PS 用 CPU 写过输出缓冲，切回时整体 flush）
    const int fl0 = flushes_all;
    check(tt_hw_select(TT_BACKEND_PS) == 0 && tt_forward(net, wa, patch.data(), la) == 0 && diff(la, logits_ref) == 0, "PS-only backend logits bit-exact");
    check(tt_hw_select(TT_BACKEND_PL) == 0 && flushes_all == fl0 + 1, "switch back to PL flushes all once");
    check(tt_forward(net, wa, patch.data(), la) == 0 && diff(la, logits_ref) == 0, "PL after switch logits bit-exact");

    // 7. 单投影 K（n_proj = 1，输出写 out_q）：第 0 层输入是 x_embed
    tt_embed(net, patch.data(), xa);
    std::memset(qa, 0x5A, sizeof(qa));
    tt_hw_proj(xa, qa, ka, va, sa, w_file + TT_NF, 0, 0, N, 1);
    check(diff(qa, load<int16_t>("L0_k_i16.bin", DN)) == 0, "n_proj=1 with K weights -> out_q == L0 k");

    // 8. 非法调用被拒绝，不启动引擎，不计引擎错误
    std::memset(qa, 0x5A, sizeof(qa));
    tt_hw_proj(xa, qa, ka, va, sa, w_other, w_other, w_other, N, 1);
    tt_hw_proj(xa, qa, ka, va, sa, w_file, w_file + TT_NF, w_file + 2 * TT_NF, 10, 3);
    tt_hw_proj(xa, qa, ka, va, sa, w_file + TT_NF, w_file + 2 * TT_NF, w_file + 3 * TT_NF, N, 3);
    check(tt_eng_rejected() == 3 && qa[0] == 0x5A5A, "3 illegal calls rejected, outputs untouched");
    check(tt_eng_errors() == 0, "engine returned no error code");
    std::printf("cache ops: flush_all %d, flush_range %d, invalidate %d\n", flushes_all, flush_ranges, invalidates);

    std::printf(failures ? "FAIL test_hw_engine: %d check(s)\n" : "PASS test_hw_engine: M2 driver + HLS model bit-exact vs sim/golden/n6_real\n", failures);
    return failures ? 1 : 0;
}
