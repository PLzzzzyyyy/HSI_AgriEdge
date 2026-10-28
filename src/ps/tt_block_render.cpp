#include "tt_block_render.h"
#include <string.h>

namespace {
struct Color { uint8_t r, g, b; };
// Exactly model/visualize.py::COLORS, including label 0 (unlabeled).
const Color palette[10] = {
    {0, 0, 0}, {255, 0, 0}, {238, 154, 0}, {255, 255, 0},
    {0, 255, 0}, {0, 255, 207}, {0, 160, 255}, {0, 0, 255},
    {176, 0, 255}, {255, 182, 193}
};
const Color paper = {246, 248, 250};
const Color ink = {28, 38, 52};
const Color border = {147, 157, 170};
const Color unknown[2] = {{196, 203, 211}, {223, 228, 234}};

// Five columns per glyph; low bit is the uppermost of seven rows.
const uint8_t letters[26][5] = {
    {0x7e,0x11,0x11,0x11,0x7e}, {0x7f,0x49,0x49,0x49,0x36},
    {0x3e,0x41,0x41,0x41,0x22}, {0x7f,0x41,0x41,0x22,0x1c},
    {0x7f,0x49,0x49,0x49,0x41}, {0x7f,0x09,0x09,0x09,0x01},
    {0x3e,0x41,0x49,0x49,0x7a}, {0x7f,0x08,0x08,0x08,0x7f},
    {0x00,0x41,0x7f,0x41,0x00}, {0x20,0x40,0x41,0x3f,0x01},
    {0x7f,0x08,0x14,0x22,0x41}, {0x7f,0x40,0x40,0x40,0x40},
    {0x7f,0x02,0x0c,0x02,0x7f}, {0x7f,0x04,0x08,0x10,0x7f},
    {0x3e,0x41,0x41,0x41,0x3e}, {0x7f,0x09,0x09,0x09,0x06},
    {0x3e,0x41,0x51,0x21,0x5e}, {0x7f,0x09,0x19,0x29,0x46},
    {0x46,0x49,0x49,0x49,0x31}, {0x01,0x01,0x7f,0x01,0x01},
    {0x3f,0x40,0x40,0x40,0x3f}, {0x1f,0x20,0x40,0x20,0x1f},
    {0x3f,0x40,0x38,0x40,0x3f}, {0x63,0x14,0x08,0x14,0x63},
    {0x07,0x08,0x70,0x08,0x07}, {0x61,0x51,0x49,0x45,0x43}
};
const uint8_t digits[10][5] = {
    {0x3e,0x51,0x49,0x45,0x3e}, {0x00,0x42,0x7f,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46}, {0x21,0x41,0x45,0x4b,0x31},
    {0x18,0x14,0x12,0x7f,0x10}, {0x27,0x45,0x45,0x45,0x39},
    {0x3c,0x4a,0x49,0x49,0x30}, {0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36}, {0x06,0x49,0x49,0x29,0x1e}
};

void le16(uint8_t *p, unsigned value) {
    p[0] = (uint8_t)value; p[1] = (uint8_t)(value >> 8);
}
void le32(uint8_t *p, uint32_t value) {
    for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8 * i));
}
void bmp_header(uint8_t *bmp, int width, int height, int stride) {
    memset(bmp, 0, 54);
    bmp[0] = 'B'; bmp[1] = 'M';
    le32(bmp + 2, 54 + stride * height);
    le32(bmp + 10, 54); le32(bmp + 14, 40);
    le32(bmp + 18, width); le32(bmp + 22, height);
    le16(bmp + 26, 1); le16(bmp + 28, 24);
    le32(bmp + 34, stride * height);
    le32(bmp + 38, 3780); le32(bmp + 42, 3780);
}
Color label_color(const uint8_t *labels, int row, int col) {
    const uint8_t label = labels ? labels[row * TT_BLOCK_SIDE + col] : (uint8_t)TT_BLOCK_UNKNOWN;
    return label < 10 ? palette[label] : unknown[((row / 2) + (col / 2)) & 1];
}
void pixel(uint8_t *bmp, int x, int y, Color c) {
    if (x < 0 || y < 0 || x >= TT_BLOCK_BMP_WIDTH || y >= TT_BLOCK_BMP_HEIGHT) return;
    uint8_t *p = bmp + 54 + (TT_BLOCK_BMP_HEIGHT - 1 - y) * TT_BLOCK_BMP_STRIDE + 3 * x;
    p[0] = c.b; p[1] = c.g; p[2] = c.r;
}
void rect(uint8_t *bmp, int x, int y, int w, int h, Color c) {
    for (int r = 0; r < h; ++r)
        for (int col = 0; col < w; ++col) pixel(bmp, x + col, y + r, c);
}
uint8_t glyph(char c, int col) {
    if (c >= 'A' && c <= 'Z') return letters[c - 'A'][col];
    if (c >= '0' && c <= '9') return digits[c - '0'][col];
    if (c == '-') return 0x08;
    if (c == '/') return (uint8_t)(1u << (5 - col));
    if (c == '.') return col == 2 ? 0x60 : 0;
    if (c == '(') return col == 2 ? 0x3e : col == 3 ? 0x41 : 0;
    if (c == ')') return col == 2 ? 0x3e : col == 1 ? 0x41 : 0;
    return 0;
}
void text(uint8_t *bmp, int x, int y, const char *str, int scale = 2) {
    for (; *str; ++str, x += 6 * scale)
        for (int c = 0; c < 5; ++c) {
            const uint8_t bits = glyph(*str, c);
            for (int r = 0; r < 7; ++r)
                if ((bits >> r) & 1) rect(bmp, x + c * scale, y + r * scale, scale, scale, ink);
        }
}
void map(uint8_t *bmp, int panel, const uint8_t *labels) {
    const int x = TT_BLOCK_BMP_MARGIN + panel * (TT_BLOCK_SIDE * TT_BLOCK_BMP_SCALE + TT_BLOCK_BMP_GAP);
    const int side = TT_BLOCK_SIDE * TT_BLOCK_BMP_SCALE;
    rect(bmp, x - 1, TT_BLOCK_BMP_MAP_Y - 1, side + 2, side + 2, border);
    for (int r = 0; r < TT_BLOCK_SIDE; ++r)
        for (int c = 0; c < TT_BLOCK_SIDE; ++c) {
            const Color color = label_color(labels, r, c);
            rect(bmp, x + c * TT_BLOCK_BMP_SCALE, TT_BLOCK_BMP_MAP_Y + r * TT_BLOCK_BMP_SCALE,
                 TT_BLOCK_BMP_SCALE, TT_BLOCK_BMP_SCALE, color);
        }
}
const char *board_title(const uint8_t *board) {
    if (!board) return "BOARD NOT RUN";
    int known = 0;
    for (int i = 0; i < TT_BLOCK_PIXELS; ++i) known += board[i] < 10;
    return known == 0 ? "BOARD NOT RUN" : known == TT_BLOCK_PIXELS ? "BOARD RESULT" : "BOARD PARTIAL";
}
} // namespace

size_t tt_block_render_bmp(uint8_t *bmp, size_t capacity,
                           const uint8_t *gt, const uint8_t *pc_ref,
                           const uint8_t *board) {
    if (!bmp || capacity < TT_BLOCK_BMP_BYTES) return 0;
    memset(bmp, 0, TT_BLOCK_BMP_BYTES);
    bmp_header(bmp, TT_BLOCK_BMP_WIDTH, TT_BLOCK_BMP_HEIGHT, TT_BLOCK_BMP_STRIDE);
    rect(bmp, 0, 0, TT_BLOCK_BMP_WIDTH, TT_BLOCK_BMP_HEIGHT, paper);
    text(bmp, 16, 14, "LONGKOU - 64 X 64 CLASSIFICATION");
    text(bmp, 16, 39, "EACH SOURCE PIXEL IS 4 X 4 - TOP ROW FIRST - GRAY CHECKS MEAN NO RESULT", 1);
    text(bmp, 16, 59, "GROUND TRUTH");
    text(bmp, 288, 59, "PC REF (FIXED)");
    text(bmp, 560, 59, board_title(board));
    map(bmp, 0, gt); map(bmp, 1, pc_ref); map(bmp, 2, board);
    text(bmp, 16, 355, "CLASS LABELS");
    const char *names[11] = {
        "0 UNLABELED", "1 CORN", "2 COTTON", "3 SESAME", "4 BROAD-LEAF SOY.",
        "5 NARROW-LEAF SOY.", "6 RICE", "7 WATER", "8 ROAD / HOUSES", "9 MIXED WEED", "NO RESULT"
    };
    for (int i = 0; i < 11; ++i) {
        const int x = 16 + (i % 3) * 272, y = 382 + (i / 3) * 24;
        rect(bmp, x - 1, y - 1, 20, 18, border);
        if (i < 10) rect(bmp, x, y, 18, 16, palette[i]);
        else for (int r = 0; r < 16; ++r) for (int c = 0; c < 18; ++c)
            pixel(bmp, x + c, y + r, unknown[((r / 4) + (c / 4)) & 1]);
        text(bmp, x + 26, y + 1, names[i]);
    }
    return TT_BLOCK_BMP_BYTES;
}

size_t tt_prediction_render_bmp(uint8_t *bmp, size_t capacity,
                                const uint8_t *labels) {
    if (!bmp || capacity < TT_PRED_BMP_BYTES) return 0;
    bmp_header(bmp, TT_PRED_BMP_WIDTH, TT_PRED_BMP_HEIGHT, TT_PRED_BMP_STRIDE);
    for (int row = 0; row < TT_BLOCK_SIDE; ++row)
        for (int col = 0; col < TT_BLOCK_SIDE; ++col) {
            const Color color = label_color(labels, row, col);
            for (int dy = 0; dy < TT_PRED_BMP_SCALE; ++dy) {
                const int y = row * TT_PRED_BMP_SCALE + dy;
                uint8_t *p = bmp + 54 + (TT_PRED_BMP_HEIGHT - 1 - y) * TT_PRED_BMP_STRIDE
                             + col * TT_PRED_BMP_SCALE * 3;
                for (int dx = 0; dx < TT_PRED_BMP_SCALE; ++dx, p += 3) {
                    p[0] = color.b; p[1] = color.g; p[2] = color.r;
                }
            }
        }
    return TT_PRED_BMP_BYTES;
}
