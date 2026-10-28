#include "tt_measure.h"
#include <cassert>
#include <cstdio>
static uint64_t now=0;static uint64_t clock_us(){return now;}
int main(){
    TTMeasureRecord r;
    {TTMeasureUse use(r,clock_us);{TTMeasureScope p(TT_MEASURE_EXTRACT);now+=7;}
      {TTMeasureScope p(TT_MEASURE_NORMALIZE);now+=11;}tt_measure_pl(2000,4);}
    assert(r.valid&&r.us[1]==7&&r.us[2]==11&&r.pl_cycles==2000&&r.pixels==4);
    {TTMeasureUse use(r,clock_us);TTMeasureScope p(TT_MEASURE_EMBED);now=0;}
    assert(!r.valid);
    TTMeasureRecord overlap;{TTMeasureUse use(overlap,clock_us);TTMeasureScope a(TT_MEASURE_EMBED);TTMeasureScope b(TT_MEASURE_EXTRACT);}
    assert(!overlap.valid);
    TTMeasureRecord overflow;overflow.pl_cycles=UINT64_MAX;
    {TTMeasureUse use(overflow,clock_us);tt_measure_pl(1,1);}assert(!overflow.valid);
    std::puts("MEASURE_PASS synthetic disjoint/clock-backward/overlap/overflow; no board times");
}
