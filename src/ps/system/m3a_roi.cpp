#include "m3a_roi.h"
#include "tt_net.h"
#include <cmath>
#include <climits>
#include <cstring>

namespace {
struct Span { const void *ptr; size_t bytes; };
bool mul(size_t a, size_t b, size_t &out) {
    if (b && a > SIZE_MAX / b) return false;
    out = a * b; return true;
}
bool valid(Span s, size_t alignment) {
    const uintptr_t a = reinterpret_cast<uintptr_t>(s.ptr);
    return a && s.bytes && a % alignment == 0 && s.bytes <= UINTPTR_MAX - a;
}
bool overlaps(Span a, Span b) {
    return reinterpret_cast<uintptr_t>(a.ptr) < reinterpret_cast<uintptr_t>(b.ptr) + b.bytes &&
           reinterpret_cast<uintptr_t>(b.ptr) < reinterpret_cast<uintptr_t>(a.ptr) + a.bytes;
}
bool dma(Span s) {
    const uint64_t a = reinterpret_cast<uintptr_t>(s.ptr);
    return valid(s, 64) && a < UINT64_C(0x100000000) &&
           s.bytes <= UINT64_C(0x100000000) - a;
}
int validate(const TTM3aRoiRequest &r, size_t &total, size_t &in, size_t &out) {
    if (!r.width || !r.height || r.width > INT_MAX - 6u || r.height > INT_MAX - 6u ||
        r.row_pixels < r.width + 6u || r.row_pixels > INT_MAX ||
        !r.roi_width || !r.roi_height || r.x >= r.width || r.y >= r.height ||
        r.roi_width > r.width - r.x || r.roi_height > r.height - r.y ||
        !r.batch_size || r.batch_size > TT_M3A_ROI_BATCH_MAX || !r.max_polls ||
        !mul(r.roi_width, r.roi_height, total)) return TT_M3A_ROI_ARGUMENT;
    const uint32_t n = total < r.batch_size ? static_cast<uint32_t>(total) : r.batch_size;
    size_t cube, result;
    if (!mul(r.height + 6u, r.row_pixels, cube) ||
        !mul(cube, TT_ENGINE_BANDS * sizeof(float), cube) ||
        !mul(total, sizeof(TTM3aRoiResult), result)) return TT_M3A_ROI_BUFFER;
    in = n * static_cast<size_t>(TT_ENGINE_IN_STRIDE);
    out = tt_m3a_output_bytes(n, 0, 11, TT_ENGINE_OUT_CLASS, false);
    const Span spans[] = {
        {r.cube, cube}, {r.cls_token, TT_D * sizeof(float)},
        {r.pos_embed, TT_ENGINE_BLK_ELEMS * sizeof(float)},
        {r.patch, TT_ENGINE_PATCH_ELEMS * sizeof(float)},
        {r.input, in}, {r.output, out}, {r.results, result}
    };
    if (r.cube_bytes < cube || r.cls_count < TT_D || r.pos_count < TT_ENGINE_BLK_ELEMS ||
        r.patch_bytes < spans[3].bytes || r.input_bytes < in || r.output_bytes < out ||
        r.result_count < total || !dma(spans[4]) || !dma(spans[5])) return TT_M3A_ROI_BUFFER;
    for (unsigned i = 0; i < 7; ++i) {
        if (!valid(spans[i], 4)) return TT_M3A_ROI_BUFFER;
        // The first three spans are read-only and may alias each other.
        for (unsigned j = 0; j < i; ++j)
            if (i >= 3 && overlaps(spans[i], spans[j])) return TT_M3A_ROI_BUFFER;
    }
    return TT_M3A_ROI_OK;
}
bool finite_params(const TTM3aRoiRequest &r) {
    for (unsigned i = 0; i < TT_D; ++i)
        if (!std::isfinite(r.cls_token[i])) return false;
    for (unsigned i = 0; i < TT_ENGINE_BLK_ELEMS; ++i)
        if (!std::isfinite(r.pos_embed[i])) return false;
    return true;
}
bool patch_ok(const TTM3aRoiRequest &r, uint32_t x, uint32_t y) {
    TTMeasureScope validation(TT_MEASURE_VALIDATE);
    // Constant raw windows need explicit rejection: float summation may make a
    // nonzero constant appear to have a tiny nonzero variance.
    const float first = r.cube[(static_cast<size_t>(y) * r.row_pixels + x) * 270];
    bool varied = false;
    for (unsigned h = 0; h < 7; ++h)
        for (unsigned w = 0; w < 7; ++w) {
            const float *p = r.cube + ((static_cast<size_t>(y) + h) * r.row_pixels + x + w) * 270;
            for (unsigned c = 0; c < 270; ++c) {
                if (!std::isfinite(p[c])) return false;
                varied |= p[c] != first;
            }
        }
    if (!varied) return false;
    validation.finish();
    tt_patch_extract(r.cube, static_cast<int>(r.row_pixels), static_cast<int>(y),
                     static_cast<int>(x), r.patch);
    TTMeasureScope checked_values(TT_MEASURE_VALIDATE);
    bool nonzero = false;
    for (unsigned i = 0; i < TT_ENGINE_PATCH_ELEMS; ++i) {
        if (!std::isfinite(r.patch[i])) return false;
        nonzero |= r.patch[i] != 0.0f;
    }
    // Reject finite-but-all-zero output caused by float variance overflow too.
    if (!nonzero) return false;
    for (unsigned p = 0; p < TT_D; ++p)
        for (unsigned n = 0; n < 6; ++n) {
            const float v = (n ? r.patch[p * 5 + n - 1] : r.cls_token[p]) + r.pos_embed[p * 6 + n];
            // Legacy magic quantizer requires |v*4096| < 2^22. Never pass NaN,
            // infinity or out-of-domain finite sums to its integer arithmetic.
            if (!std::isfinite(v) || std::fabs(v) >= 1024.0f) return false;
        }
    return true;
}
} // namespace

int tt_m3a_roi_run(TTM3aRoiSession &s, const TTM3aRoiRequest &r) {
    if (s.halted) return TT_M3A_ROI_HALTED; // BEFORE buffer preparation/access
    s.completed = 0; s.driver_status = 0;
    size_t total = 0, input_span = 0, output_span = 0;
    TTMeasureScope arguments(TT_MEASURE_VALIDATE);
    const int rc = validate(r, total, input_span, output_span);
    if (rc) return rc;
    if (!finite_params(r)) return TT_M3A_ROI_NUMERIC;
    arguments.finish();
    const TTNet net = {6, 5, nullptr, r.cls_token, r.pos_embed, nullptr, nullptr};
    while (s.completed < total) {
        const uint32_t n = static_cast<uint32_t>(total - s.completed < r.batch_size ?
                                               total - s.completed : r.batch_size);
        for (uint32_t i = 0; i < n; ++i) {
            const size_t idx = s.completed + i;
            const uint32_t x = r.x + static_cast<uint32_t>(idx % r.roi_width);
            const uint32_t y = r.y + static_cast<uint32_t>(idx / r.roi_width);
            if (!patch_ok(r, x, y)) return TT_M3A_ROI_NUMERIC;
            int16_t *dst = r.input + i * (TT_ENGINE_IN_STRIDE / sizeof(int16_t));
            std::memset(dst, 0, TT_ENGINE_IN_STRIDE);
            tt_embed(net, r.patch, dst);
        }
        const TTM3aJob job = {r.input, input_span, r.output, output_span,
                             n, 0, 11, TT_ENGINE_OUT_CLASS, false};
        s.driver_status = tt_m3a_run(job, r.max_polls);
        if (s.driver_status != TT_M3A_OK) {
            s.halted = true;
            return TT_M3A_ROI_DRIVER; // No output/guard reads; no further batches.
        }
        for (uint32_t i = 0; i < n; ++i) {
            const size_t idx = s.completed + i;
            uint32_t packed;
            std::memcpy(&packed, static_cast<const unsigned char *>(r.output) + i * 4, 4);
            r.results[idx] = {r.x + static_cast<uint32_t>(idx % r.roi_width),
                             r.y + static_cast<uint32_t>(idx / r.roi_width), packed};
        }
        s.completed += n;
    }
    return TT_M3A_ROI_OK;
}
