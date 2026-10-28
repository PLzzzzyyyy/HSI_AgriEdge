#ifndef TT_HW_ENGINE_H
#define TT_HW_ENGINE_H
// M2 板上 PL 后端（tt_hw_engine.cpp）的附加接口。投影调用仍走 tt_hw.h；这里只有权重装载与诊断。
#include <stdint.h>

// 把 weights_all.bin 布局的投影因子（[12][4][3014] int16 Q1.14）拼成权重包装进引擎（LOAD_W，n_patch = 0）。
// 之后 tt_hw_proj* 的权重指针必须指向这份数组内部（驱动按偏移算层号与投影号）。返回 0 成功，否则为引擎返回值或 -1。
// tt_pl_init 默认装载 tt_data.h 的 tt_weights；换权重的应用在第一次投影前自己调用。
int tt_eng_load_weights(const int16_t *weights_all, unsigned int ncls);

// 最近一次引擎返回值（[7:0] 错误码，[15:8] 契约版本，见 src/hls/tt_engine_regs.h）
unsigned int tt_eng_last_ret();
// 驱动拒绝执行的调用数（权重指针不在已装载的数组内、n_tok ≠ 6、n_proj 与指针不配）与引擎报错的调用数
unsigned int tt_eng_rejected();
unsigned int tt_eng_errors();

#endif
