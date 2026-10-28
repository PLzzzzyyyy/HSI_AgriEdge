#ifndef S2C_ROI_TIMING_H
#define S2C_ROI_TIMING_H
#include <cstdint>
#include <limits>
namespace s2c {
// Private App wall-clock phases only. step includes PS preparation and engine
// wait/cache/service; no field claims to isolate PS numeric work or pure PL.
enum class TimingPhase:unsigned {setup,step,probe,results,display,rows,pump,model,control,count};
constexpr unsigned TIMING_PHASES=unsigned(TimingPhase::count);
inline const char *timing_phase_name(unsigned phase) {
    static const char *const names[]={"setup","step","probe","results","display","rows","pump","model","control"};
    return phase<TIMING_PHASES?names[phase]:"invalid";
}
struct TimingSnapshot {
    bool valid=false;
    uint64_t elapsed_us=0,accounted_us=0,other_us=0,wait_us=0,wait_calls=0;
    uint64_t us[TIMING_PHASES]={},calls[TIMING_PHASES]={};
};
class TimingScope;
class TaskTiming {
    friend class TimingScope;
    uint64_t start_=0,last_=0,end_=0,total_=0,wait_=0,wait_calls_=0;
    uint64_t us_[TIMING_PHASES]={},calls_[TIMING_PHASES]={};
    bool begun_=false,finished_=false,valid_=true,in_scope_=false;
    bool add_to(uint64_t &dst,uint64_t value) {
        if(value>std::numeric_limits<uint64_t>::max()-dst){valid_=false;return false;}
        dst+=value;return true;
    }
public:
    void begin(uint64_t now) {
        start_=last_=now;end_=total_=wait_=wait_calls_=0;begun_=true;finished_=false;valid_=true;in_scope_=false;
        for(unsigned i=0;i<TIMING_PHASES;++i)us_[i]=calls_[i]=0;
    }
    bool active() const {return begun_&&!finished_;}
    bool add(TimingPhase phase,uint64_t begin,uint64_t end) {
        if(!active()||!valid_)return false;
        const unsigned i=unsigned(phase);
        if(i>=TIMING_PHASES||begin<last_||end<begin){valid_=false;return false;}
        const uint64_t dt=end-begin;last_=end;
        return add_to(total_,dt)&&add_to(us_[i],dt)&&add_to(calls_[i],1);
    }
    bool add_wait(uint64_t begin,uint64_t end) {
        if(!active()||!valid_)return false;
        if(begin<start_||end<begin){valid_=false;return false;}
        return add_to(wait_,end-begin)&&add_to(wait_calls_,1);
    }
    void finish(uint64_t now) {
        if(!active())return;
        if(in_scope_||now<last_)valid_=false;
        finished_=true;end_=now;
    }
    bool snapshot(uint64_t now,TimingSnapshot &out) const {
        out=TimingSnapshot{};if(!begun_)return false;
        const uint64_t end=finished_?end_:now;
        if(!valid_||in_scope_||end<last_||end<start_||total_>end-start_||wait_>end-start_)return false;
        out.valid=true;out.elapsed_us=end-start_;out.accounted_us=total_;out.other_us=out.elapsed_us-total_;
        out.wait_us=wait_;out.wait_calls=wait_calls_;
        for(unsigned i=0;i<TIMING_PHASES;++i){out.us[i]=us_[i];out.calls[i]=calls_[i];}
        return true;
    }
};
class TimingScope {
    TaskTiming &timing_;TimingPhase phase_;uint64_t (*clock_)();uint64_t begin_;bool owns_;
public:
    TimingScope(TaskTiming &timing,TimingPhase phase,uint64_t (*clock)()):timing_(timing),phase_(phase),clock_(clock),
        begin_(clock()),owns_(timing.active()&&!timing.in_scope_) {if(owns_)timing_.in_scope_=true;}
    TimingScope(const TimingScope &)=delete;TimingScope &operator=(const TimingScope &)=delete;
    uint64_t finish() {
        if(!owns_)return 0;
        const uint64_t end=clock_();owns_=false;timing_.in_scope_=false;(void)timing_.add(phase_,begin_,end);
        return end>=begin_?end-begin_:0;
    }
    ~TimingScope(){(void)finish();}
};
}
#endif
