#ifndef TT_TEST_XIL_CACHE_H
#define TT_TEST_XIL_CACHE_H
#include "xtucker_proj.h"
void Xil_DCacheFlush();
void Xil_DCacheFlushRange(INTPTR, u32);
void Xil_DCacheInvalidateRange(INTPTR, u32);
#endif
