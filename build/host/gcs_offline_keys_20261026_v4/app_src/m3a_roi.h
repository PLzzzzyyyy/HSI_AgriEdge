#ifndef TT_M3A_ROI_H
#define TT_M3A_ROI_H
#include "tt_m3a.h"

// S1a: synchronous single owner; no allocation, I/O, LOAD_W, M2 owner or timer.
// Caller initializes serial int16 M3a and loads matching weights first.
enum { TT_M3A_ROI_BATCH_MAX = 16 };
enum TTM3aRoiStatus {
    TT_M3A_ROI_OK = 0,
    TT_M3A_ROI_ARGUMENT = -100,
    TT_M3A_ROI_BUFFER = -101,
    TT_M3A_ROI_NUMERIC = -102,
    TT_M3A_ROI_DRIVER = -103,
    TT_M3A_ROI_HALTED = -104
};
struct TTM3aRoiResult {
    uint32_t x, y;             // Original UNPADDED coordinates, zero-based.
    uint32_t packed_class;     // Exact CLASS: [7:0] zero-based class index,
                              // [15:8] reserved, [31:16] softmax Q0.16 (FFFF cap).
};
struct TTM3aRoiRequest {
    // Already Gaussian/global-normalized float32 HWC, 270 bands, 3 zero pixels
    // on each side. NOT raw sensor data or M3b BFP. Full padded rows allocated:
    // (height+6)*row_pixels*270 floats; row_pixels >= width+6.
    const float *cube;
    size_t cube_bytes;
    uint32_t width, height, row_pixels;
    uint32_t x, y, roi_width, roi_height;
    const float *cls_token; size_t cls_count; // >=2646, matches resident weights
    const float *pos_embed; size_t pos_count; // >=15876; fixed N6/seq5 only
    uint32_t batch_size, max_polls;           // 1..16; polls are NOT milliseconds
    float *patch; size_t patch_bytes;        // >=13230 floats, reused serially
    int16_t *input; size_t input_bytes;      // 64B aligned, low-4GiB DMA span
    void *output; size_t output_bytes;       // 64B aligned, rounded CLASS span
    TTM3aRoiResult *results; size_t result_count; // compact ROI row-major
};
struct TTM3aRoiSession {
    // Zero-initialize ONCE per App lifetime, outside all request buffers.
    // After ANY driver error: no retry, buffer read/reuse/free, alternate owner,
    // or clearing this latch; external PL reset + application restart required.
    bool halted;
    size_t completed;          // Committed prefix of current request, not attempts
    int driver_status;         // Original driver error; 0 for PS-only failures
};
// Exclusive ownership throughout call. Metadata/session must be outside all
// buffers; writable spans cannot alias cube/parameters or each other.
// Results saved in caller RAM only after each successful FULL batch; failure
// leaves that batch and suffix untouched. Not an atomic whole-ROI transaction.
// Invalid numeric patch stops BEFORE submitting its batch; completed identifies
// the previous successful prefix. No performance claim.
int tt_m3a_roi_run(TTM3aRoiSession &session, const TTM3aRoiRequest &request);
#endif
