#ifndef TT_ATTN_H
#define TT_ATTN_H
// 注意力（SCORES / SOFTMAX / CTX+RES）与分类头（HEAD）单元，int16 版（W16A18），docs/engine_arch.md §3.3、§3.4、§3.6、§4.2。
// 数值唯一来源 model/engine_ref.py（attention、exp_q24、head），C 版 sim/host/engine_ref.cpp；全部整数，逐位一致。
// 每个单元一个 HLS 顶层（单独 csim / csynth / cosim，build/hls/run_tt_attn.tcl）；核心函数 ta_* 给 D4a 放进 tt_engine 的 dataflow。
//
// 宽度随档位：TA_H = w/2 = 4·TT_K3/7（K3 = 7 为 4，14 为 8）。SCORES、CTX 每拍 6·TA_H 次乘加（= 3w）；SOFTMAX、HEAD 与 K3 无关。
// 片上块布局（Q、K、V、XN、X 都一样，D4a 起引擎直接用）：元素 (p, t) 在 blk[t][h][i]，h = p % TA_H，i = p / TA_H，
// 每个 token TA_BD 个字（末字补齐，补齐 lane 内容任意）。t、h 两维完全分区，6·TA_H 个 bank：
//   SCORES 一拍读 6 个 q 平面各 TA_H 个连续 p + k 的 token c 的 TA_H 个连续 p
//   CTX    一拍读写同一 token 的 TA_H 个连续 p；段起点 441c 不对齐，按 bank 各自取址、按 lane 旋转
//   引擎的归一化 / 拷贝 / RES2 一拍写 6 个 token 的同一 p，也落在 6 个不同 bank
// 不把 (t, h) 合成一维：bank 号写成 t·TA_H + h 时，HLS 在引擎里把它当变量，每个 store 都可能写任意 bank，II 等于 store 个数（09-26 D4a）。
// 单元顶层的接口数组上两条 ARRAY_PARTITION 只生效一条（09-25），所以单元单独综合的 II 不代表并入引擎后的 II。
// 激活是 Q5.12 的 18 位整数（ap_int<18> 原始值）。
#include "tt_engine.h"

#if TT_DF != 12
#error "tt_attn implements the int16 build (DF = 12) only"
#endif

#define TA_H      (4 * TT_K3 / 7)                         // w/2
#define TA_LGH    (TT_K3 == 7 ? 2 : 3)                    // log2(TA_H)
#define TA_BD     ((TT_D + TA_H - 1) / TA_H)              // 每 token 字数：662 / 331
#define TA_NB     (TT_N * TA_H)                           // 块的 bank 数
#define TA_DTAIL  (TT_D - (TA_BD - 1) * TA_H)             // token 末字的有效 lane 数：2 / 6
#define TA_SEG    (TT_D / TT_N)                           // 441：V 按内存序切块的段长（§3.4 末段）
#define TA_SEGW   ((TA_SEG + TA_H - 1) / TA_H)            // 每段组数：111 / 56
#define TA_STAIL  (TA_SEG - (TA_SEGW - 1) * TA_H)         // 段末组的有效 lane 数：1 / 1
#define TA_NCLS   TT_ENGINE_NCLS_MAX                      // 24
#define TA_HW     (TA_NCLS / 4)                           // W_HEAD 字阵列数：一个 64 位字装同一 p 的 4 个类别
#define TA_LOGITS (TT_ENGINE_LOGIT_STRIDE / 4)            // LOGITS 输出槽数 32

typedef ap_int<18>  ta_act_t;           // Q5.12
typedef ap_int<48>  ta_s_t;             // scores Q10.24，|s| < 2^46
typedef ap_uint<25> ta_attn_t;          // Q0.24，≤ 2^24
typedef ta_act_t    ta_blk_t[TT_N][TA_H][TA_BD];
typedef ap_int<30>  ta_s1_t;            // Σx：|x| ≤ 2^17，D = 2646 → < 2^29
typedef ap_uint<46> ta_sxx_t;           // Σx²：< 2^46
typedef ap_int<32>  ta_logit_t;         // Q.16

extern const ap_uint<25> ta_thi[256];   // T_HI[a] = round(2^(−a/256)·2^24)
extern const ap_uint<25> ta_tlo[256];   // T_LO[b] = round(2^(−b/65536)·2^24)

// 核心（SOFTMAX 与 HEAD 共用 ta_exp 与同一个串行除法器）
ap_uint<25> ta_exp(ap_uint<56> d);
void ta_scores(const ta_blk_t qb, const ta_blk_t kb, ta_s_t s[TT_N][TT_N]);
void ta_softmax(const ta_s_t s[TT_N][TT_N], ta_attn_t attn[TT_N][TT_N]);
void ta_ctx(const ta_attn_t attn[TT_N][TT_N], const ta_blk_t v, const ta_blk_t xn, ta_blk_t x, ta_s1_t s1[TT_N], ta_sxx_t sxx[TT_N]);
unsigned int ta_head(const ta_blk_t x, const ap_uint<64> wh[TA_HW][TT_D], const ap_int<8> eh[TA_NCLS],
                     const ap_int<32> hb[TA_NCLS], unsigned int ncls, ta_logit_t logits[TA_LOGITS]);

// HLS 顶层（每个单元一个）
void tt_attn_scores(const ta_blk_t qb, const ta_blk_t kb, ta_s_t s[TT_N][TT_N]);
void tt_attn_softmax(const ta_s_t s[TT_N][TT_N], ta_attn_t attn[TT_N][TT_N]);
void tt_attn_ctx(const ta_attn_t attn[TT_N][TT_N], const ta_blk_t v, const ta_blk_t xn, ta_blk_t x, ta_s1_t s1[TT_N], ta_sxx_t sxx[TT_N]);
unsigned int tt_attn_head(const ta_blk_t x, const ap_uint<64> wh[TA_HW][TT_D], const ap_int<8> eh[TA_NCLS],
                          const ap_int<32> hb[TA_NCLS], unsigned int ncls, ta_logit_t logits[TA_LOGITS]);

#endif
