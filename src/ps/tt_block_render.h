#ifndef TT_BLOCK_RENDER_H
#define TT_BLOCK_RENDER_H

#include <stddef.h>
#include <stdint.h>

// Fixed 64 x 64 triptych, enlarged 4 x with nearest-neighbor pixels.
// All arrays use row-major labels (0=unlabeled, 1..9=classes).
enum {
    TT_BLOCK_SIDE = 64,
    TT_BLOCK_PIXELS = TT_BLOCK_SIDE * TT_BLOCK_SIDE,
    TT_BLOCK_UNKNOWN = 255,
    TT_BLOCK_BMP_SCALE = 4,
    TT_BLOCK_BMP_MARGIN = 16,
    TT_BLOCK_BMP_GAP = 16,
    TT_BLOCK_BMP_MAP_Y = 80,
    TT_BLOCK_BMP_WIDTH = 832,
    TT_BLOCK_BMP_HEIGHT = 488,
    TT_BLOCK_BMP_STRIDE = (TT_BLOCK_BMP_WIDTH * 3 + 3) & ~3,
    TT_BLOCK_BMP_BYTES = 54 + TT_BLOCK_BMP_STRIDE * TT_BLOCK_BMP_HEIGHT,
    TT_PRED_BMP_SCALE = 8,
    TT_PRED_BMP_WIDTH = TT_BLOCK_SIDE * TT_PRED_BMP_SCALE,
    TT_PRED_BMP_HEIGHT = TT_BLOCK_SIDE * TT_PRED_BMP_SCALE,
    TT_PRED_BMP_STRIDE = (TT_PRED_BMP_WIDTH * 3 + 3) & ~3,
    TT_PRED_BMP_BYTES = 54 + TT_PRED_BMP_STRIDE * TT_PRED_BMP_HEIGHT
};

// Writes a complete little-endian, bottom-up, uncompressed 24-bit BMP.
// Returns bytes written, or 0 for a null/short output buffer (no writes).
// Null maps and labels >9 render as gray checks. The board title explicitly
// distinguishes NOT RUN, PARTIAL and RESULT. No dynamic allocation or I/O.
// The caller must flush this buffer's D-cache range before a JTAG/XSCT dump.
size_t tt_block_render_bmp(uint8_t *bmp, size_t capacity,
                           const uint8_t *gt, const uint8_t *pc_ref,
                           const uint8_t *board);

// Independent 512 x 512 prediction-only BMP (64 x 64 labels, enlarged 8 x).
// Same palette, row order, unknown-label behavior and capacity checks as above.
// No titles/borders; every pixel belongs to the classification map. Pass actual
// board labels for an inference result, then flush the buffer before JTAG dump.
size_t tt_prediction_render_bmp(uint8_t *bmp, size_t capacity,
                                const uint8_t *labels);

#endif
