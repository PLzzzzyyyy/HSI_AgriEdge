#ifndef TT_NET_H
#define TT_NET_H
// PS 端整网调度：预处理后的 patch → 12 层 TEL → 9 类 logits。
// 数值约定与 model/fixed_point_sim.py 一致；PL 算子由 tt_hw.h 抽象（板上驱动 / 主机端逐位仿真二选一）。
//
// 内存布局（全部与 DDR 块一致，PS 不做任何转置）：
//   激活块 x[D*N]     int16 Q3.12（v1.4：层间激活定点存储），元素 (p, n) 在 p*N + n，p = (i1*7+i2)*54 + j，n = token（0 是 cls）
//   权重   w[3014]    M1[7][7] M2[7][7] M3[54][54] 行主序，int16 Q1.14
//   patch  [270*7*7]  float32，ToTensor 之后的 CHW 内存序，已做 token 级归一化（preprocess.py::patch_tensor）
//   stats  [2*N]      int32：PL 归一化每个 token 的 mean_q24、inv_q24（tt_ref_int.h），PS 残差用它复原 xn
//
// 一层：PL(normalize+qkv) → PS scores/softmax → PS x = quant(xn + attn·v)（原地）→ PL(normalize+mlp) → PS x = quant(xn + mlp)
// 浮点精度：PS 部分用 float32（A9 的 NEON 只有单精度）；层间 x 多一次 Q3.12 舍入。参考 logits 是 PC double 定点仿真，
// 主机 4096 像素实验 max|dlogit| 0.0086（阈值 TT_LOGIT_TOL），标签 4096/4096；分类结果以 argmax 一致为准。
#include <stdint.h>

#define TT_W 7
#define TT_J 54
#define TT_D (TT_W * TT_W * TT_J)     // 2646
#define TT_NF (2 * TT_W * TT_W + TT_J * TT_J)   // 3014
#define TT_LAYERS 12
#define TT_CLASSES 9
#define TT_NMAX 10
#define TT_DF 12
#define TT_SCALE (1 << TT_DF)         // 4096：int16 ↔ float 的定标，与 src/hls/tt_types.h 的 data_t 一致
#define TT_LOGIT_TOL 1e-2             // board/host float32 vs PC double 参考的 |dlogit| 上限

typedef float tt_real;

struct TTNet {
    int N;                            // token 数含 cls：非重叠 6，重叠 10
    int seq;                          // 光谱子张量数：N-1
    const int16_t *weights;           // weights_all.bin：[layer][query,key,value,mlp][3014]
    const float *cls_token;           // [D]
    const float *pos_embed;           // [D*N]
    const float *cls_w;               // [9][D]
    const float *cls_b;               // [9]
};

// 工作缓冲：由调用者分配（板上放 DDR，全部 32 字节对齐、容量按 32 字节取整，PL 直接读写）
struct TTWork {
    int16_t *x;                       // [D*N]  当前层激活：PL 输入，PS 原地写残差
    int16_t *out_q, *out_k, *out_v;   // [D*N]  PL 输出
    int32_t *stats;                   // [TT_STATS_CAP] PL 归一化统计量
};

// ---- 分段计时（可选）：main 挂上时钟回调后，tt_layer 把各段耗时累加进 tt_prof[]；不挂则零开销 ----
enum { TT_PROF_PL_QKV = 0, TT_PROF_SCORES, TT_PROF_CTX, TT_PROF_PL_MLP, TT_PROF_RESID, TT_PROF_N };
typedef unsigned long long (*tt_clock_fn)();
extern tt_clock_fn tt_clock;                 // 默认 0
extern unsigned long long tt_prof[TT_PROF_N];
extern unsigned long long tt_layer_prof[TT_LAYERS][TT_PROF_N];
extern unsigned long long tt_layer_ticks[TT_LAYERS];
extern const char *tt_prof_name[TT_PROF_N];
void tt_profile_reset();  // 每次诊断前清零；不影响 tt_clock 或网络数据
const char *tt_net_backend_name();   // "NEON" 或 "scalar"：PS 浮点内核实际编译成了哪种

// patch: [270*7*7] float32（预处理完成）→ logits[9]。返回 argmax（0..8，标签 = argmax+1）
int tt_forward(const TTNet &net, TTWork &wk, const float *patch, tt_real *logits);

// 双 patch 流水：PL 算一个 patch 的投影时 PS 处理另一个，需要两套工作缓冲。两个结果与各自单独 tt_forward 逐位相同。
// 分段计时里 PL 两栏为启动/cache + 未被 PS 掩盖的等待时间，不是完整硬件运行时间。
void tt_forward_pair(const TTNet &net, TTWork &wa, TTWork &wb, const float *pa, const float *pb,
                     tt_real *la, tt_real *lb, int *best_a, int *best_b);

// 从预处理后的 (rw, rw, 270) float32 HWC 图块取以 (i, j) 为左上角的 7×7 窗 → (270,7,7) CHW，并做 patch 级归一化
// （无偏 std，float32），复刻 preprocess.patch_tensor。输出可直接送 tt_forward。
void tt_patch_extract(const float *region, int rw, int i, int j, float *patch);

// 单层，暴露出来便于逐层对拍。x 原地更新。
void tt_layer(const TTNet &net, TTWork &wk, int layer);

// 以下为纯 PS 的数值步骤（也在 tt_net.cpp 里）。N 只支持 6 和 10。
void tt_embed(const TTNet &net, const float *patch, int16_t *x);          // embed 后量化到 Q3.12
void tt_quant(const tt_real *x, int16_t *q, int count);                    // AP_RND + AP_SAT 到 Q3.12
// attn[n][c] = softmax_c( Σ_p q[p,n] k[p,c] )，q/k 是 PL 输出的 Q3.12 块
void tt_scores(const int16_t *q, const int16_t *k, int N, tt_real attn[TT_NMAX][TT_NMAX]);
// 原地 x = quant(xn + ctx)，xn = ((float)x/4096 − mean[i%N])·inv[i%N]，ctx_flat[n*D + j] = Σ_c attn[n][c] · v_flat[c*D + j] / 4096
void tt_ctx_residual(int16_t *x, const tt_real attn[TT_NMAX][TT_NMAX], const int16_t *v, const int32_t *stats, int N);
void tt_mlp_residual(int16_t *x, const int16_t *mlp, const int32_t *stats, int N);   // 原地 x = quant(xn + mlp / 4096)

#endif
