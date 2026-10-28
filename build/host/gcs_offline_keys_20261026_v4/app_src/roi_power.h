#ifndef S2C_ROI_POWER_H
#define S2C_ROI_POWER_H
#include <cmath>
#include <cstdint>
#include "roi_power_profile.h"
namespace s2c {
// Temperature-conditioned VECTORLESS design estimate, never current telemetry.
// Fixed activity assumptions: no inferred idle/active multiplier, no fake noise.
struct PowerView {
    float watts=0,temperature=40;
    double joules=0;
    uint64_t duration_us=0,fallback_us=0;
    unsigned task=0;
    bool active=false,temperature_valid=false;
};
inline float chip_power_w(float temperature) {
    using namespace power_profile;
    if(temperature<=TEMPERATURES[0])return WATTS[0];
    for(unsigned i=1;i<POINTS;++i)if(temperature<=TEMPERATURES[i]) {
        const float fraction=(temperature-TEMPERATURES[i-1])/(TEMPERATURES[i]-TEMPERATURES[i-1]);
        return WATTS[i-1]+fraction*(WATTS[i]-WATTS[i-1]);
    }
    return WATTS[POINTS-1];
}
class PowerEstimate {
    PowerView value_{};
    uint64_t sampled_=0,last_=0;
    float temperature_=40;
    bool valid_=false;
    bool fresh(uint64_t at) const {return valid_&&at>=sampled_&&at-sampled_<3000000;}
    void segment(uint64_t end,bool measured_temperature) {
        if(value_.active&&end>last_) {
            const uint64_t dt=end-last_;
            value_.duration_us+=dt;
            if(!measured_temperature)value_.fallback_us+=dt;
            value_.joules+=double(chip_power_w(measured_temperature?temperature_:40))*double(dt)/1000000.0;
        }
        last_=end;
    }
public:
    void advance(uint64_t now) {
        if(now<last_)return;
        // Split at expiry so an old temperature is not silently held forever.
        const uint64_t expiry=sampled_+3000000;
        if(valid_&&last_<expiry&&now>=expiry)segment(expiry,true);
        segment(now,fresh(now));
        value_.temperature_valid=fresh(now);
        value_.temperature=value_.temperature_valid?temperature_:40;
        value_.watts=chip_power_w(value_.temperature);
    }
    void temperature(float value,bool valid,uint64_t now) {
        advance(now);
        valid_=valid&&std::isfinite(value)&&value>=-40&&value<=125;
        temperature_=value;sampled_=now;advance(now);
    }
    void begin(unsigned task,uint64_t now) {
        advance(now);value_.task=task;value_.joules=0;value_.duration_us=value_.fallback_us=0;
        value_.active=true;last_=now;
    }
    void finish(uint64_t now) {advance(now);value_.active=false;}
    PowerView view(uint64_t now) {advance(now);return value_;}
};
}
#endif
