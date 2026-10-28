#ifndef TT_MEASURE_H
#define TT_MEASURE_H
// Optional, single foreground owner. CPU wall-clock microseconds, NOT PL cycles.
// No numeric changes/allocations/MMIO here; caller selects task or PROBE scope.
#include <stdint.h>
#include "tt_engine_regs.h"
enum TTMeasurePart { TT_MEASURE_VALIDATE,TT_MEASURE_EXTRACT,TT_MEASURE_NORMALIZE,
    TT_MEASURE_EMBED,TT_MEASURE_CACHE_PREPARE,TT_MEASURE_SUBMIT,TT_MEASURE_WAIT,
    TT_MEASURE_CACHE_COMPLETE,TT_MEASURE_PARTS };
struct TTMeasureRecord {
    uint64_t us[TT_MEASURE_PARTS]={},calls[TT_MEASURE_PARTS]={};
    uint64_t wait_service_us=0,wait_service_calls=0,pl_cycles=0,pl_calls=0,pixels=0;
    bool valid=true;
    void add(uint64_t &dst,uint64_t n){if(UINT64_MAX-dst<n)valid=false;else dst+=n;}
};
typedef uint64_t (*TTMeasureClock)();
struct TTMeasureContext {TTMeasureRecord *record=nullptr;TTMeasureClock clock=nullptr;int part=-1;};
inline TTMeasureContext &tt_measure_context(){static TTMeasureContext value;return value;}
class TTMeasureUse {
    TTMeasureContext saved_;
public:
    TTMeasureUse(TTMeasureRecord &r,TTMeasureClock c):saved_(tt_measure_context()) {
        if(saved_.record||!c){r.valid=false;return;}
        tt_measure_context().record=&r;tt_measure_context().clock=c;
    }
    ~TTMeasureUse(){tt_measure_context()=saved_;}
};
class TTMeasureScope {
    TTMeasureRecord *r_;TTMeasureClock clock_;int part_;uint64_t start_=0;bool open_=false;
public:
    explicit TTMeasureScope(TTMeasurePart part):r_(tt_measure_context().record),clock_(tt_measure_context().clock),part_(part) {
        if(!r_)return;
        if(tt_measure_context().part!=-1||!clock_){r_->valid=false;return;}
        tt_measure_context().part=part_;open_=true;start_=clock_();
    }
    void finish(){if(!open_)return;open_=false;const uint64_t end=clock_();
        if(end<start_)r_->valid=false;else r_->add(r_->us[part_],end-start_);
        r_->add(r_->calls[part_],1);tt_measure_context().part=-1;}
    ~TTMeasureScope(){finish();}
};
inline void tt_measure_pl(uint32_t cycles,uint32_t pixels){
    TTMeasureRecord *r=tt_measure_context().record;if(!r)return;
    if(!cycles||cycles==TT_ENGINE_CYCLES_INVALID){r->valid=false;return;}
    r->add(r->pl_cycles,cycles);r->add(r->pl_calls,1);r->add(r->pixels,pixels);
}
#endif
