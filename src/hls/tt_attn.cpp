// tt_attn —— 注意力（SCORES / SOFTMAX / CTX+RES）与分类头（HEAD）单元（docs/engine_arch.md §3.3、§3.4、§3.6、§4.2），
// 数值与 model/engine_ref.py 的 attention、exp_q24、head 及 Engine.forward 的残差逐位一致。宽度、布局见 tt_attn.h。
// 所有片上地址用跑动计数器（加法与移位，没有变量乘除），32 位无符号。
#include "tt_attn.h"

#define TA_LOG2E_Q24 24204406                   // round(log2(e)·2^24)
#define TA_EXP_CUT   (25ULL << 24)              // d ≥ 25（自然对数单位）时 e = 0

// engine_ref.py 的 T_HI / T_LO 原值（tb 逐项对 llround(pow) 核对）
const ap_uint<25> ta_thi[256] = {
    16777216, 16731851, 16686609, 16641490, 16596492, 16551616, 16506861, 16462228, 16417715, 16373322, 16329050, 16284897,
    16240863, 16196949, 16153153, 16109476, 16065917, 16022476, 15979152, 15935945, 15892855, 15849882, 15807025, 15764283,
    15721658, 15679147, 15636752, 15594471, 15552304, 15510252, 15468313, 15426487, 15384775, 15343175, 15301688, 15260313,
    15219050, 15177899, 15136859, 15095929, 15055111, 15014403, 14973805, 14933316, 14892937, 14852668, 14812507, 14772455,
    14732511, 14692675, 14652947, 14613326, 14573813, 14534406, 14495106, 14455912, 14416824, 14377841, 14338964, 14300193,
    14261526, 14222963, 14184505, 14146151, 14107901, 14069754, 14031710, 13993769, 13955931, 13918195, 13880561, 13843028,
    13805598, 13768268, 13731039, 13693911, 13656884, 13619956, 13583129, 13546401, 13509772, 13473242, 13436812, 13400479,
    13364245, 13328109, 13292070, 13256129, 13220286, 13184539, 13148888, 13113335, 13077877, 13042515, 13007249, 12972078,
    12937002, 12902021, 12867135, 12832343, 12797645, 12763041, 12728530, 12694113, 12659789, 12625557, 12591419, 12557372,
    12523418, 12489555, 12455784, 12422104, 12388516, 12355018, 12321610, 12288294, 12255067, 12221930, 12188882, 12155924,
    12123055, 12090275, 12057584, 12024981, 11992466, 11960039, 11927700, 11895448, 11863283, 11831206, 11799215, 11767310,
    11735492, 11703760, 11672114, 11640553, 11609078, 11577687, 11546382, 11515161, 11484025, 11452973, 11422004, 11391120,
    11360319, 11329601, 11298967, 11268415, 11237946, 11207559, 11177254, 11147032, 11116891, 11086831, 11056853, 11026956,
    10997140, 10967404, 10937749, 10908174, 10878679, 10849263, 10819928, 10790671, 10761494, 10732395, 10703375, 10674434,
    10645571, 10616786, 10588079, 10559449, 10530897, 10502422, 10474024, 10445703, 10417458, 10389290, 10361198, 10333182,
    10305242, 10277377, 10249587, 10221873, 10194234, 10166669, 10139179, 10111763, 10084422, 10057154, 10029960, 10002839,
    9975792, 9948818, 9921917, 9895089, 9868333, 9841650, 9815039, 9788499, 9762032, 9735636, 9709311, 9683058,
    9656875, 9630764, 9604722, 9578752, 9552851, 9527021, 9501261, 9475570, 9449948, 9424396, 9398913, 9373499,
    9348154, 9322877, 9297668, 9272528, 9247455, 9222451, 9197514, 9172644, 9147842, 9123107, 9098438, 9073837,
    9049301, 9024833, 9000430, 8976093, 8951823, 8927617, 8903477, 8879403, 8855394, 8831449, 8807569, 8783754,
    8760003, 8736317, 8712694, 8689136, 8665641, 8642209, 8618841, 8595536, 8572295, 8549116, 8525999, 8502945,
    8479954, 8457025, 8434157, 8411352
};
const ap_uint<25> ta_tlo[256] = {
    16777216, 16777039, 16776861, 16776684, 16776506, 16776329, 16776151, 16775974, 16775796, 16775619, 16775442, 16775264,
    16775087, 16774909, 16774732, 16774555, 16774377, 16774200, 16774022, 16773845, 16773667, 16773490, 16773313, 16773135,
    16772958, 16772780, 16772603, 16772426, 16772248, 16772071, 16771893, 16771716, 16771539, 16771361, 16771184, 16771007,
    16770829, 16770652, 16770474, 16770297, 16770120, 16769942, 16769765, 16769588, 16769410, 16769233, 16769055, 16768878,
    16768701, 16768523, 16768346, 16768169, 16767991, 16767814, 16767637, 16767459, 16767282, 16767105, 16766927, 16766750,
    16766573, 16766395, 16766218, 16766041, 16765863, 16765686, 16765509, 16765331, 16765154, 16764977, 16764799, 16764622,
    16764445, 16764267, 16764090, 16763913, 16763736, 16763558, 16763381, 16763204, 16763026, 16762849, 16762672, 16762494,
    16762317, 16762140, 16761963, 16761785, 16761608, 16761431, 16761253, 16761076, 16760899, 16760722, 16760544, 16760367,
    16760190, 16760013, 16759835, 16759658, 16759481, 16759304, 16759126, 16758949, 16758772, 16758595, 16758417, 16758240,
    16758063, 16757886, 16757708, 16757531, 16757354, 16757177, 16756999, 16756822, 16756645, 16756468, 16756290, 16756113,
    16755936, 16755759, 16755582, 16755404, 16755227, 16755050, 16754873, 16754696, 16754518, 16754341, 16754164, 16753987,
    16753810, 16753632, 16753455, 16753278, 16753101, 16752924, 16752746, 16752569, 16752392, 16752215, 16752038, 16751860,
    16751683, 16751506, 16751329, 16751152, 16750975, 16750797, 16750620, 16750443, 16750266, 16750089, 16749912, 16749734,
    16749557, 16749380, 16749203, 16749026, 16748849, 16748672, 16748494, 16748317, 16748140, 16747963, 16747786, 16747609,
    16747432, 16747254, 16747077, 16746900, 16746723, 16746546, 16746369, 16746192, 16746015, 16745837, 16745660, 16745483,
    16745306, 16745129, 16744952, 16744775, 16744598, 16744421, 16744244, 16744066, 16743889, 16743712, 16743535, 16743358,
    16743181, 16743004, 16742827, 16742650, 16742473, 16742296, 16742119, 16741941, 16741764, 16741587, 16741410, 16741233,
    16741056, 16740879, 16740702, 16740525, 16740348, 16740171, 16739994, 16739817, 16739640, 16739463, 16739286, 16739109,
    16738931, 16738754, 16738577, 16738400, 16738223, 16738046, 16737869, 16737692, 16737515, 16737338, 16737161, 16736984,
    16736807, 16736630, 16736453, 16736276, 16736099, 16735922, 16735745, 16735568, 16735391, 16735214, 16735037, 16734860,
    16734683, 16734506, 16734329, 16734152, 16733975, 16733798, 16733621, 16733444, 16733267, 16733090, 16732913, 16732736,
    16732559, 16732382, 16732205, 16732028
};

// ---------------------------------------------------------------- 定点 exp 与串行除法器（SOFTMAX 与 HEAD 共用）
// exp(−d)：d ≥ 0 为 Q.24，返回 Q0.24（≤ 2^24）。d ≥ EXP_CUT 时 0；否则 u = d·LOG2E_Q24（Q.48，< 2^54），
// i = u >> 48（0..36，≥ 25 时结果必为 0），f = (u >> 32) & 0xFFFF，e = ((T_HI[f >> 8]·T_LO[f & 255] + 2^23) >> 24) >> i
ap_uint<25> ta_exp(ap_uint<56> d) {
#pragma HLS INLINE
    const ap_uint<29> dd = d.range(28, 0);
    const ap_uint<54> u = dd * ap_uint<25>(TA_LOG2E_Q24);
    const ap_uint<6> i = u.range(53, 48);
    const ap_uint<8> fa = u.range(47, 40), fb = u.range(39, 32);
    const ap_uint<49> t = ta_thi[fa] * ta_tlo[fb];
    const ap_uint<25> e = (t + ap_uint<49>(1 << 23)) >> 24;
    if (d >= TA_EXP_CUT || i >= 25) return 0;
    return e >> i;
}

// floor(2^K / den)，要求 2^(K − NB) < den < 2^29（商 < 2^NB）；一拍一位，NB 拍（SOFTMAX：K = 47，NB = 24；HEAD：K = 40，NB = 17）
template <int K, int NB> static ap_uint<NB> ta_div_pow2(ap_uint<30> den) {
    ap_uint<30> rem = ap_uint<30>(1) << (K - NB);
    ap_uint<NB> q = 0;
    for (int b = 0; b < NB; b++) {
#pragma HLS PIPELINE II=1
        rem = rem << 1;
        const bool ge = rem >= den;
        if (ge) rem -= den;
        q = (q << 1) | ap_uint<NB>(ge);
    }
    return q;
}

static inline ta_act_t ta_sat18(ap_int<25> v) {
#pragma HLS INLINE
    if (v > 131071) return 131071;
    if (v < -131072) return -131072;
    return (ta_act_t)v;
}

// ---------------------------------------------------------------- SCORES
// s[n][c] = Σ_p q[p][n]·k[p][c]，精确（|s| < 2^46）。一拍读 k 的 token c 一个字（TA_H 个 p）× 6 个 q 平面 = 6·TA_H 次乘加，
// TT_N·TA_BD 拍（K3 = 7：3,972，14：1,986）；token 末字只有 TA_DTAIL 个 lane 有效，其余按 0 算（补齐 lane 的 q、k 内容任意）。
void ta_scores(const ta_blk_t qb, const ta_blk_t kb, ta_s_t s[TT_N][TT_N]) {
    ta_s_t acc[TT_N];
#pragma HLS ARRAY_PARTITION variable=acc complete
    unsigned int i = 0, c = 0;
    for (unsigned int it = 0; it < TT_N * TA_BD; it++) {
#pragma HLS PIPELINE II=1
        const bool last = i == TA_BD - 1;
        for (int n = 0; n < TT_N; n++) {
            ta_s_t sum = 0;
            for (int h = 0; h < TA_H; h++) {
                const ta_act_t kv = kb[c][h][i];
                if (!last || h < TA_DTAIL) sum += qb[n][h][i] * kv;
            }
            const ta_s_t a = (i == 0 ? ta_s_t(0) : acc[n]) + sum;
            acc[n] = a;
            if (last) s[n][c] = a;
        }
        if (last) { i = 0; c++; } else i++;
    }
}

// ---------------------------------------------------------------- SOFTMAX
// 每行 m = max_c s，e = exp(m − s)，S = Σe（2^24 ≤ S ≤ 6·2^24），r = floor(2^47 / S)（24 拍串行除法），attn = (e·r + 2^22) >> 23
void ta_softmax(const ta_s_t s[TT_N][TT_N], ta_attn_t attn[TT_N][TT_N]) {
    for (unsigned int n = 0; n < TT_N; n++) {
        ta_s_t sr[TT_N], m = 0;
        ap_uint<25> e[TT_N];
#pragma HLS ARRAY_PARTITION variable=sr complete
#pragma HLS ARRAY_PARTITION variable=e complete
        for (unsigned int c = 0; c < TT_N; c++) {
#pragma HLS PIPELINE II=1
            const ta_s_t v = s[n][c];
            sr[c] = v;
            if (c == 0 || v > m) m = v;
        }
        ap_uint<27> sum = 0;
        for (unsigned int c = 0; c < TT_N; c++) {
#pragma HLS PIPELINE II=1
            const ap_uint<25> ev = ta_exp(ap_uint<56>(m - sr[c]));
            e[c] = ev;
            sum += ev;
        }
        const ap_uint<24> r = ta_div_pow2<47, 24>(sum);
        for (unsigned int c = 0; c < TT_N; c++) {
#pragma HLS PIPELINE II=1
            attn[n][c] = (e[c] * r + ap_uint<48>(1 << 22)) >> 23;
        }
    }
}

// ---------------------------------------------------------------- CTX+RES
// ctx(441s + m, t) = Σ_c attn[s][c]·v(441c + m, t)，ctx_q = sat18((ctx + 2^23) >> 24)，x_mid = sat18(xn_q + ctx_q)，
// 顺带累计每个 token 的 S1 = Σx_mid、Sxx = Σx_mid²（下一次归一化用，同 tt_engine load_stats 的约定）。
// 按 (token t, 组 g, 段 c) 扫：一组 = 同一 token 的 TA_H 个连续 m；6 拍（c = 0..5）各读一个 V 字，累加 6 段 × TA_H 个 ctx
// （6·TA_H 次乘加 / 拍，舍入常数 2^23 在 c = 0 时预置）；组末 acc >> 24 进 pend，在下一组的 6 拍里按段 s = c 倒出：
// 读 XN、写 X 各 TA_H 个，舍入与饱和只在倒出时做。共 6·(6·TA_SEGW + 1) 拍（K3 = 7：4,002，14：2,022）。
// 段起点 441c 不按 TA_H 对齐：lane h 的 p = p0 + h，token t 的 bank [t][b] 取字 (p0 >> lg) + (b < ρ)，lane h 取 bank (h + ρ) % TA_H，ρ = p0 % TA_H。
// 段末组只有 TA_STAIL 个 lane 有效，无效 lane 不写 X、不计统计量（最后一段末组的无效 lane 字地址越界，夹到 TA_BD − 1）。
void ta_ctx(const ta_attn_t attn[TT_N][TT_N], const ta_blk_t v, const ta_blk_t xn, ta_blk_t x, ta_s1_t s1[TT_N], ta_sxx_t sxx[TT_N]) {
    ap_int<48> acc[TT_N][TA_H];
    ap_int<24> pend[TT_N][TA_H];
#pragma HLS ARRAY_PARTITION variable=acc complete dim=0
#pragma HLS ARRAY_PARTITION variable=pend complete dim=0
    unsigned int c = 0, g = 0, t = 0, go = 0, p0 = 0;           // 乘加侧：go = TA_H·g，p0 = 441c + go
    unsigned int dg = 0, dt = 0, dp0 = 0;                       // 倒出侧（上一组）：dp0 = 441s + TA_H·dg，s = c
    bool have = false;
    ta_s1_t r1 = 0;
    ta_sxx_t r2 = 0;
    for (unsigned int it = 0; it < TT_N * (TT_N * TA_SEGW + 1); it++) {
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=x inter false
        if (t < TT_N) {
            const unsigned int rh = p0 & (TA_H - 1), a0 = p0 >> TA_LGH;
            ta_act_t vb[TA_H], vl[TA_H];
#pragma HLS ARRAY_PARTITION variable=vb complete
#pragma HLS ARRAY_PARTITION variable=vl complete
            for (int b = 0; b < TA_H; b++) {
                unsigned int a = a0 + (b < (int)rh ? 1u : 0u);
                if (a > TA_BD - 1) a = TA_BD - 1;
                vb[b] = v[t][b][a];
            }
            for (int h = 0; h < TA_H; h++) vl[h] = vb[(h + rh) & (TA_H - 1)];
            for (int s = 0; s < TT_N; s++) {
                const ap_int<26> w = attn[s][c];
                for (int h = 0; h < TA_H; h++)
                    acc[s][h] = (c == 0 ? ap_int<48>(1 << 23) : acc[s][h]) + w * vl[h];
            }
        }
        if (have) {
            const unsigned int rh = dp0 & (TA_H - 1), a0 = dp0 >> TA_LGH;
            unsigned int ab[TA_H];
            ta_act_t xb[TA_H], xm[TA_H];
            bool val[TA_H];
#pragma HLS ARRAY_PARTITION variable=ab complete
#pragma HLS ARRAY_PARTITION variable=xb complete
#pragma HLS ARRAY_PARTITION variable=xm complete
#pragma HLS ARRAY_PARTITION variable=val complete
            for (int b = 0; b < TA_H; b++) {
                unsigned int a = a0 + (b < (int)rh ? 1u : 0u);
                if (a > TA_BD - 1) a = TA_BD - 1;
                ab[b] = a;
                xb[b] = xn[dt][b][a];
            }
            ta_s1_t d1 = 0;
            ta_sxx_t d2 = 0;
            for (int h = 0; h < TA_H; h++) {
                const ta_act_t cq = ta_sat18(pend[c][h]);
                xm[h] = ta_sat18(xb[(h + rh) & (TA_H - 1)] + cq);
                val[h] = dg != TA_SEGW - 1 || h < TA_STAIL;
                if (val[h]) {
                    d1 += xm[h];
                    d2 += (ap_uint<35>)(xm[h] * xm[h]);
                }
            }
            for (int b = 0; b < TA_H; b++) {
                const unsigned int h = (b - rh) & (TA_H - 1);
                if (val[h]) x[dt][b][ab[b]] = xm[h];
            }
            const bool first = dg == 0 && c == 0;
            r1 = (first ? ta_s1_t(0) : r1) + d1;
            r2 = (first ? ta_sxx_t(0) : r2) + d2;
            if (dg == TA_SEGW - 1 && c == TT_N - 1) { s1[dt] = r1; sxx[dt] = r2; }
        }
        if (c == TT_N - 1) {
            for (int s = 0; s < TT_N; s++)
                for (int h = 0; h < TA_H; h++) pend[s][h] = acc[s][h] >> 24;
            have = t < TT_N;
            dg = g; dt = t; dp0 = go;
            if (g == TA_SEGW - 1) { g = 0; go = 0; t++; } else { g++; go += TA_H; }
            p0 = go;
            c = 0;
        } else {
            c++;
            p0 += TA_SEG;
            dp0 += TA_SEG;
        }
    }
}

// ---------------------------------------------------------------- HEAD
// acc_c = Σ_p W_c[p]·x(p, 1)（24 类并行，一拍一个 p，2,646 拍），l_c = ((acc_c + 2^(r−1)) >> r) + b_c，r = DF + e_c − 16（1..63，
// 权重包保证），label = argmax（并列取小下标），conf = min(0xFFFF, floor(2^40 / Σ_c E((l_max − l_c) << 8)))，E 即 ta_exp。
// wh[g][p] 的 16 位 lane q 是类别 4g + q 的 W[p]（W_HEAD 驻留布局，§4.3）。logits 写 TA_LOGITS 个槽（低 32 位），ncls 之后写 0。
// 返回 {conf[31:16], 0, label[7:0]}（tt_engine_regs.h 的 CLASS 字）。x 是终块，只读 token 1。
unsigned int ta_head(const ta_blk_t x, const ap_uint<64> wh[TA_HW][TT_D], const ap_int<8> eh[TA_NCLS],
                     const ap_int<32> hb[TA_NCLS], unsigned int ncls, ta_logit_t logits[TA_LOGITS]) {
    ap_int<48> acc[TA_NCLS];
    ap_int<46> l[TA_NCLS];
#pragma HLS ARRAY_PARTITION variable=acc complete
#pragma HLS ARRAY_PARTITION variable=l complete
    for (unsigned int p = 0; p < TT_D; p++) {
#pragma HLS PIPELINE II=1
        const ta_act_t xv = x[1][p & (TA_H - 1)][p >> TA_LGH];
        for (int g = 0; g < TA_HW; g++) {
            const ap_uint<64> w = wh[g][p];
            for (int q = 0; q < 4; q++) {
                ap_int<16> wv;
                wv.range(15, 0) = w.range(16 * q + 15, 16 * q);
                acc[4 * g + q] = (p == 0 ? ap_int<48>(0) : acc[4 * g + q]) + wv * xv;
            }
        }
        if (p >= ncls && p < TA_LOGITS) logits[p] = 0;
    }
    ap_int<46> lmax = 0;
    unsigned int label = 0;
    for (unsigned int c = 0; c < ncls; c++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=24
        const unsigned int r = (unsigned int)(TT_DF - 16 + eh[c]);
        const ap_int<64> a = ((ap_int<64>)acc[c] + ((ap_int<64>)1 << (r - 1))) >> r;
        const ap_int<46> lc = a + hb[c];
        l[c] = lc;
        logits[c] = lc;
        if (c == 0 || lc > lmax) { lmax = lc; label = c; }
    }
    ap_uint<29> sum = 0;
    for (unsigned int c = 0; c < ncls; c++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=24
        sum += ta_exp(ap_uint<56>(lmax - l[c]) << 8);
    }
    const ap_uint<17> q = ta_div_pow2<40, 17>(sum);
    const unsigned int conf = q > 0xFFFF ? 0xFFFFu : (unsigned int)q;
    return (conf << 16) | label;
}

// ---------------------------------------------------------------- HLS 顶层（单独 csynth / cosim；接口 ap_memory）
void tt_attn_scores(const ta_blk_t qb, const ta_blk_t kb, ta_s_t s[TT_N][TT_N]) {
#pragma HLS ARRAY_PARTITION variable=qb complete dim=1
#pragma HLS ARRAY_PARTITION variable=qb complete dim=2
#pragma HLS ARRAY_PARTITION variable=kb complete dim=1
#pragma HLS ARRAY_PARTITION variable=kb complete dim=2
#pragma HLS ARRAY_PARTITION variable=s complete dim=1
    ta_scores(qb, kb, s);
}

void tt_attn_softmax(const ta_s_t s[TT_N][TT_N], ta_attn_t attn[TT_N][TT_N]) {
#pragma HLS ARRAY_PARTITION variable=s complete dim=1
#pragma HLS ARRAY_PARTITION variable=attn complete dim=1
    ta_softmax(s, attn);
}

void tt_attn_ctx(const ta_attn_t attn[TT_N][TT_N], const ta_blk_t v, const ta_blk_t xn, ta_blk_t x, ta_s1_t s1[TT_N], ta_sxx_t sxx[TT_N]) {
#pragma HLS ARRAY_PARTITION variable=attn complete dim=1
#pragma HLS ARRAY_PARTITION variable=v complete dim=1
#pragma HLS ARRAY_PARTITION variable=v complete dim=2
#pragma HLS ARRAY_PARTITION variable=xn complete dim=1
#pragma HLS ARRAY_PARTITION variable=xn complete dim=2
#pragma HLS ARRAY_PARTITION variable=x complete dim=1
#pragma HLS ARRAY_PARTITION variable=x complete dim=2
    ta_ctx(attn, v, xn, x, s1, sxx);
}

unsigned int tt_attn_head(const ta_blk_t x, const ap_uint<64> wh[TA_HW][TT_D], const ap_int<8> eh[TA_NCLS],
                          const ap_int<32> hb[TA_NCLS], unsigned int ncls, ta_logit_t logits[TA_LOGITS]) {
#pragma HLS ARRAY_PARTITION variable=x complete dim=1
#pragma HLS ARRAY_PARTITION variable=x complete dim=2
#pragma HLS ARRAY_PARTITION variable=wh complete dim=1
    return ta_head(x, wh, eh, hb, ncls, logits);
}
