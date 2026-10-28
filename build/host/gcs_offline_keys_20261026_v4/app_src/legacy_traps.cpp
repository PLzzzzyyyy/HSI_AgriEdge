// Link-only definitions for unused legacy functions in unchanged tt_net.cpp.
// Not a driver/emulator; absolutely no second IP owner or numerical fallback.
#include "tt_hw.h"
#include <cstdio>
namespace { [[noreturn]] void forbidden() {
    std::puts("FATAL forbidden legacy projection; external reset + restart required");
    for (;;) {}
} }
void tt_hw_proj_start(const int16_t *,int16_t *,int16_t *,int16_t *,int32_t *,
                      const int16_t *,const int16_t *,const int16_t *,int,int) { forbidden(); }
void tt_hw_proj_wait() { forbidden(); }
