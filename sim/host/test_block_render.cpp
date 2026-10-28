// g++ -O2 -std=c++11 -o build/host/test_block_render.exe sim/host/test_block_render.cpp src/ps/tt_block_render.cpp
// Run from repository root; optional args: triptych BMP path, synthetic map BMP path.
#include "../../src/ps/tt_block_render.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t bmp[TT_BLOCK_BMP_BYTES + 1];
static uint8_t pred_bmp[TT_PRED_BMP_BYTES + 1];
static uint8_t gt[TT_BLOCK_PIXELS], ref[TT_BLOCK_PIXELS], board[TT_BLOCK_PIXELS];

static void read_labels(const char *path, uint8_t *dst) {
    FILE *f = fopen(path, "rb");
    assert(f);
    assert(fread(dst, 1, TT_BLOCK_PIXELS, f) == TT_BLOCK_PIXELS);
    assert(fgetc(f) == EOF);
    fclose(f);
}
static const uint8_t *at(int x, int y) {
    return bmp + 54 + (TT_BLOCK_BMP_HEIGHT - 1 - y) * TT_BLOCK_BMP_STRIDE + 3 * x;
}
static void rgb(int x, int y, int r, int g, int b) {
    const uint8_t *p = at(x, y);
    assert(p[0] == b && p[1] == g && p[2] == r);
}
static void pred_rgb(int x, int y, int r, int g, int b) {
    const uint8_t *p = pred_bmp + 54 + (TT_PRED_BMP_HEIGHT - 1 - y) * TT_PRED_BMP_STRIDE + 3 * x;
    assert(p[0] == b && p[1] == g && p[2] == r);
}
int main(int argc, char **argv) {
    memset(bmp, 0xa5, sizeof(bmp));
    assert(tt_block_render_bmp(0, TT_BLOCK_BMP_BYTES, 0, 0, 0) == 0);
    assert(tt_block_render_bmp(bmp, TT_BLOCK_BMP_BYTES - 1, 0, 0, 0) == 0);
    assert(bmp[0] == 0xa5 && bmp[TT_BLOCK_BMP_BYTES - 1] == 0xa5);
    memset(gt, 0, sizeof(gt));
    gt[0] = 1; gt[TT_BLOCK_PIXELS - 1] = 5;
    memset(board, TT_BLOCK_UNKNOWN, sizeof(board));
    assert(tt_block_render_bmp(bmp, TT_BLOCK_BMP_BYTES, gt, 0, board) == TT_BLOCK_BMP_BYTES);
    assert(bmp[TT_BLOCK_BMP_BYTES] == 0xa5);
    assert(bmp[0] == 'B' && bmp[1] == 'M');
    rgb(16, TT_BLOCK_BMP_MAP_Y, 255, 0, 0);
    rgb(19, TT_BLOCK_BMP_MAP_Y + 3, 255, 0, 0);
    rgb(20, TT_BLOCK_BMP_MAP_Y, 0, 0, 0);
    rgb(271, TT_BLOCK_BMP_MAP_Y + 255, 0, 255, 207);
    rgb(560, TT_BLOCK_BMP_MAP_Y, 196, 203, 211);
    rgb(568, TT_BLOCK_BMP_MAP_Y, 223, 228, 234);
    board[0] = 6;
    assert(tt_block_render_bmp(bmp, sizeof(bmp), gt, 0, board) == TT_BLOCK_BMP_BYTES);
    rgb(560, TT_BLOCK_BMP_MAP_Y, 0, 160, 255);

    read_labels("model/data/block/gt_u8.bin", gt);
    read_labels("model/data/block/ref_fixed_u8.bin", ref);
    // The example has no board inference: a null map is visibly NOT RUN.
    assert(tt_block_render_bmp(bmp, sizeof(bmp), gt, ref, 0) == TT_BLOCK_BMP_BYTES);
    const char *path = argc > 1 ? argv[1] : "build/host/block_preview_not_run.bmp";
    FILE *f = fopen(path, "wb"); assert(f);
    assert(fwrite(bmp, 1, TT_BLOCK_BMP_BYTES, f) == TT_BLOCK_BMP_BYTES);
    assert(fclose(f) == 0);
    printf("PASS: BMP bounds, BGR, orientation, 4x pixels and unknown labels; %s (%d bytes)\n",
           path, TT_BLOCK_BMP_BYTES);

    memset(pred_bmp, 0xa5, sizeof(pred_bmp));
    assert(tt_prediction_render_bmp(0, TT_PRED_BMP_BYTES, board) == 0);
    assert(tt_prediction_render_bmp(pred_bmp, TT_PRED_BMP_BYTES - 1, board) == 0);
    for (size_t i = 0; i < sizeof(pred_bmp); ++i) assert(pred_bmp[i] == 0xa5);
    assert(tt_prediction_render_bmp(pred_bmp, TT_PRED_BMP_BYTES, 0) == TT_PRED_BMP_BYTES);
    pred_rgb(0, 0, 196, 203, 211);
    pred_rgb(16, 0, 223, 228, 234);
    assert(pred_bmp[TT_PRED_BMP_BYTES] == 0xa5);

    // Synthetic labels exercise all ten colors. This is a test fixture, NOT
    // a board prediction; keep its filename explicit if saving the artifact.
    for (int i = 0; i < TT_BLOCK_PIXELS; ++i) board[i] = (uint8_t)(i % 10);
    board[0] = 1; board[TT_BLOCK_PIXELS - 1] = 5; board[2] = TT_BLOCK_UNKNOWN;
    assert(tt_prediction_render_bmp(pred_bmp, TT_PRED_BMP_BYTES, board) == TT_PRED_BMP_BYTES);
    assert(pred_bmp[TT_PRED_BMP_BYTES] == 0xa5);
    pred_rgb(0, 0, 255, 0, 0);
    pred_rgb(7, 7, 255, 0, 0);
    pred_rgb(16, 0, 223, 228, 234);
    pred_rgb(24, 0, 255, 255, 0);
    pred_rgb(511, 511, 0, 255, 207);
    const char *pred_path = argc > 2 ? argv[2] : "build/host/prediction_synthetic_test.bmp";
    f = fopen(pred_path, "wb"); assert(f);
    assert(fwrite(pred_bmp, 1, TT_PRED_BMP_BYTES, f) == TT_PRED_BMP_BYTES);
    assert(fclose(f) == 0);
    printf("PASS: prediction-only BMP bounds, colors, orientation, 8x pixels and unknown labels; %s (%d bytes)\n",
           pred_path, TT_PRED_BMP_BYTES);
    return 0;
}
