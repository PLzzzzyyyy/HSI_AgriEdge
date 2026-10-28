// 由 model/export_block.py 生成，勿手改
#ifndef TT_BLOCK_DATA_H
#define TT_BLOCK_DATA_H
#include <stdint.h>
#define TT_BLOCK_SIZE 64
#define TT_BLOCK_ROW0 112
#define TT_BLOCK_COL0 196
#define TT_BLOCK_PAD 3
#define TT_BLOCK_RW (TT_BLOCK_SIZE + 2 * TT_BLOCK_PAD)      // 图块边长 70
#define TT_BLOCK_BANDS 270
#define TT_BLOCK_MODEL "unoverlapping"
#define TT_BLOCK_N 6
extern const float tt_block_region[];      // [RW][RW][270] float32 HWC，预处理后、patch 归一化前
extern const uint8_t tt_block_gt[];        // [S][S] 0 = 无标签
extern const uint8_t tt_block_ref[];       // [S][S] PC 定点仿真 argmax+1
#endif
