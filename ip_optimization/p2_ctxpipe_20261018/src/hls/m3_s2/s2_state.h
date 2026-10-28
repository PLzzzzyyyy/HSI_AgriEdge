#ifndef M3_S2_STATE_H
#define M3_S2_STATE_H
#include "s2_engine.h"
#if !S2_NATIVE
#include <ap_int.h>
#endif
namespace s2 {
// State only: retain signed C expression semantics; report/m3_state_t2.md.
// Native is the wide reference. Hardware always uses the proven signed widths.
#if S2_NATIVE
template<int W> using State = int;
#else
template<int W> using State = ap_int<W>;
#endif
}
#endif
