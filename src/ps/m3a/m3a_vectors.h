#ifndef M3A_VECTORS_H
#define M3A_VECTORS_H
#include <stdint.h>
#include "tt_engine_regs.h"
// Definitions generated from existing golden files, not a model run.
// Golden B is a pre-embedded block, NOT an on-board M3b/CUBE test.
#ifdef __cplusplus
extern "C" {
#endif
extern const uint32_t m3a_weights[TT_ENGINE_WPKG16_BYTES / 4];
extern const int16_t m3a_input_a[TT_ENGINE_BLK_ELEMS];
extern const int16_t m3a_input_b[TT_ENGINE_BLK_ELEMS];
extern const int32_t m3a_layers_a[TT_ENGINE_LAYERS * TT_ENGINE_BLK_ELEMS];
extern const int32_t m3a_logits[2 * 32];
extern const uint32_t m3a_classes[2];
#ifdef __cplusplus
}
#endif
#endif
