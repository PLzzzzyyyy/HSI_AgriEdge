// Private App bookkeeping only; synthetic clock, never board timing.
#include "roi_timing.h"
#include <cassert>
#include <cstdio>
#include <limits>
using namespace s2c;
static uint64_t now=0;
static uint64_t clock_us(){return now;}
int main() {
    TaskTiming timing;TimingSnapshot out{};
    assert(!timing.snapshot(10,out)); // no task is not a zero-duration measurement
    timing.begin(100);
    assert(timing.add(TimingPhase::setup,100,130));
    assert(timing.add(TimingPhase::pump,140,145));
    assert(timing.add(TimingPhase::step,150,250));
    assert(timing.add_wait(155,159)); // nested service is not added to measured total
    assert(timing.add_wait(210,212));
    assert(timing.add(TimingPhase::display,251,260));
    assert(timing.add(TimingPhase::results,260,270));
    assert(timing.add(TimingPhase::rows,275,280));
    assert(timing.snapshot(300,out));
    assert(out.elapsed_us==200&&out.accounted_us==159&&out.other_us==41);
    assert(out.wait_us==6&&out.wait_calls==2&&out.calls[unsigned(TimingPhase::step)]==1);
    assert(out.us[unsigned(TimingPhase::step)]==100);
    assert(!timing.add(TimingPhase::probe,265,285)); // overlap cannot produce a plausible sum
    assert(!timing.snapshot(300,out)&&!out.valid);
    timing.begin(500);assert(timing.add(TimingPhase::setup,500,500));
    assert(timing.snapshot(500,out)&&out.valid&&out.elapsed_us==0&&out.calls[0]==1);
    assert(!timing.add(TimingPhase::step,600,599));assert(!timing.snapshot(700,out));
    timing.begin(0);assert(timing.add(TimingPhase::step,0,10));assert(!timing.snapshot(9,out));
    timing.begin(0);assert(timing.add_wait(0,std::numeric_limits<uint64_t>::max()));
    assert(!timing.add_wait(0,1));assert(!timing.snapshot(10,out));
    // A clean new task resets private accounting only, never an engine lock.
    timing.begin(1000);assert(timing.snapshot(1001,out)&&out.other_us==1&&out.wait_calls==0);
    timing.begin(0);now=0;
    {TimingScope setup(timing,TimingPhase::setup,clock_us);now=2;
        {TimingScope nested_sd_service(timing,TimingPhase::pump,clock_us);now=5;}
        now=10;assert(setup.finish()==10);
    }
    now=11;
    {TimingScope pump(timing,TimingPhase::pump,clock_us);now=12;}
    now=13;
    {TimingScope step(timing,TimingPhase::step,clock_us);now=16;
        {TimingScope nested_wait(timing,TimingPhase::pump,clock_us);assert(timing.add_wait(16,18));now=18;}
        now=23;assert(step.finish()==10);assert(step.finish()==0);
    }
    timing.finish(30);assert(timing.snapshot(999,out));
    assert(out.elapsed_us==30&&out.accounted_us==21&&out.wait_us==2&&out.other_us==9);
    assert(out.calls[unsigned(TimingPhase::pump)]==1); // nested SD/wait pumps count only in their parent
    {TimingScope after_terminal(timing,TimingPhase::probe,clock_us);now=40;}
    assert(timing.snapshot(1000,out)&&out.elapsed_us==30&&out.calls[unsigned(TimingPhase::probe)]==0);
    std::puts("private phase timing PASS: synthetic durations, non-overlap, nested service, fail-closed clock errors, no hardware claim");
}
