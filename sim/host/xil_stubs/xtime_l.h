#ifndef TT_TEST_XTIME_L_H
#define TT_TEST_XTIME_L_H
#include <stdint.h>
typedef uint64_t XTime;
#define COUNTS_PER_SECOND 1000000ULL
void XTime_GetTime(XTime *ticks);
#endif
