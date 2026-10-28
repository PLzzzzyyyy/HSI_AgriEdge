// 由 model/export_c_arrays.py 生成，勿手改
#ifndef TT_DATA_H
#define TT_DATA_H
#include <stdint.h>
#define TT_DATA_N 6
#define TT_DATA_MODEL "unoverlapping"
#define TT_DATA_PIXEL "20,20"
#define TT_DATA_GT 1
#define TT_DATA_REF_ARGMAX 0
extern const int16_t tt_weights[];      // [12][4][3014] Q1.14
extern const float tt_cls_token[];      // [2646]
extern const float tt_pos_embed[];      // [2646*6]
extern const float tt_classifier_w[];   // [9][2646]
extern const float tt_classifier_b[];   // [9]
extern const float tt_patch[];          // [270*7*7] 预处理完成的黄金 patch
extern const double tt_ref_logits[];    // [9] PC 定点仿真的参考 logits
#endif
