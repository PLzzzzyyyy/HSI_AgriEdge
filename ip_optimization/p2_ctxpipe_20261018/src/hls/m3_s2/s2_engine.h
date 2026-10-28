#ifndef M3_S2_ENGINE_H
#define M3_S2_ENGINE_H
#include <stdint.h>
#ifndef S2_NUM
#define S2_NUM 8
#endif
#ifndef S2_P
#define S2_P 2
#endif
#ifndef S2_PACK
#define S2_PACK 1
#endif
#ifndef S2_NATIVE
#define S2_NATIVE 0
#endif
static_assert(S2_NUM==8 || S2_NUM==16,"numeric mode");
static_assert(S2_P==1 || S2_P==2,"P1/P2 only");
enum { S2_D=2646, S2_N=6, S2_DN=15876, S2_H=4, S2_DEPTH=662,
       S2_DB=S2_NUM==8?8:18, S2_DF=S2_NUM==8?4:12,
       S2_MB=S2_NUM==8?8:18, S2_MF=S2_NUM==8?4:14,
       S2_WB=S2_NUM==8?8:16, S2_AB=S2_MB+S2_WB+5 };
// Independent candidate ABI, not a drop-in replacement for tt_engine/old App.
// Input default: packed int16 Q3.12. RAW input: packed int32 current-format
// activation, for continuation / verification only. Outputs: Q16 logits (32
// int32 slots/patch), class word, or raw int32 features. DUMP is layer-major.
// CLASS_ONLY suppresses all logits writes; class stride remains 4 bytes.
// Default retains the original candidate's LOGITS+CLASS behavior.
enum { S2_LOAD=1, S2_DUMP=2, S2_RAW=4, S2_FEAT=8, S2_CLASS_ONLY=16 };
enum { S2_OK=0, S2_BAD_CONFIG=1, S2_BAD_PACKAGE=2, S2_NO_WEIGHT=3, S2_TIMEOUT=4 };
enum { S2_META_WORDS=12, S2_FORMAT=(4u<<24)|(S2_DB<<16)|(S2_DF<<8) };
// meta: [0]format [1]scheduler iterations (NOT cycles), [2]retired patches,
// [3]projection completions [4]copy completions [5]peak concurrent units,
// [6]ob waits [7]xb waits [8]output stalls [9]layer completions
// [10]KV join waits [11]nonzero port-budget rejection count.
// stall_seed is a deterministic C/host-only backpressure hook. RTL AXI stalls
// are implicit in interfaces and are NOT validated by this hook.
unsigned s2_engine(const uint64_t *weights,const uint64_t *input,
                   uint64_t *logits,uint32_t *classes,uint64_t *features,
                   unsigned count,unsigned flags,unsigned lo,unsigned hi,
                   unsigned stall_seed,unsigned max_iterations,uint32_t meta[S2_META_WORDS]);
#endif
