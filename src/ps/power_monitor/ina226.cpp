#include "ina226.h"
#include <limits>

namespace power_monitor {
bool Ina226::identify(uint8_t address) {
    identified_=configured_=false;sample_=Sample{};
    if(address<0x40||address>0x4f||!bus_.read||!bus_.write)return false;
    uint16_t maker=0,device=0;
    if(!bus_.read(bus_.context,address,0xfe,maker)||
       !bus_.read(bus_.context,address,0xff,device)) {sample_.state=State::io_error;return false;}
    identified_=maker==0x5449&&(device&0xfff0)==0x2260;
    identified_address_=address;
    sample_.state=identified_?State::idle:State::unidentified;
    return identified_;
}
bool Ina226::configure(const Config &c) {
    configured_=false;
    if(!identified_||c.address!=identified_address_||!c.wiring_confirmed||
       !c.shunt_microohms||c.shunt_microohms>1000000||
       !c.maximum_milliamps||c.maximum_milliamps>100000) {
        sample_.state=State::disabled;return false;
    }
    config_=c;configured_=true;sample_.state=State::idle;return true;
}
bool Ina226::start(uint64_t now) {
    if(!configured_||sample_.state==State::converting)return false;
    // AVG=16, bus/shunt conversion=1.1ms each, triggered shunt+bus (35.2ms).
    // A triggered conversion holds all results stable while we read them.
    if(!bus_.write(bus_.context,config_.address,0x00,0x4523)) {
        sample_.state=State::io_error;return false;
    }
    started_=now;sample_.state=State::converting;return true;
}
bool Ina226::convert(uint16_t bus,int16_t shunt,const Config &c,Sample &s) {
    s.state=State::range_error;
    if(!c.shunt_microohms||c.shunt_microohms>1000000||
       !c.maximum_milliamps||c.maximum_milliamps>100000||bus>28800||
       shunt==std::numeric_limits<int16_t>::min()||shunt==std::numeric_limits<int16_t>::max())return false;
    const int64_t nano=int64_t(shunt)*2500;
    const int64_t microamps=nano*1000/c.shunt_microohms;
    const int64_t microvolts=int64_t(bus)*1250;
    const int64_t microwatts=microvolts*microamps/1000000;
    if(microamps>int64_t(c.maximum_milliamps)*1000||
       microamps<-int64_t(c.maximum_milliamps)*1000||
       microwatts>INT32_MAX||microwatts<INT32_MIN)return false;
    s.bus_microvolts=uint32_t(microvolts);s.shunt_nanovolts=int32_t(nano);
    s.current_microamps=int32_t(microamps);s.power_microwatts=int32_t(microwatts);
    s.state=microamps<0?State::reverse_current:State::valid;
    return s.state==State::valid;
}
bool Ina226::poll(uint64_t now) {
    if(sample_.state!=State::converting)return false;
    if(now<started_||now-started_>100000) {sample_.state=State::timeout;return false;}
    if(now-started_<36000)return false;
    uint16_t status=0,shunt=0,bus=0;
    if(!bus_.read(bus_.context,config_.address,0x06,status)) {sample_.state=State::io_error;return false;}
    if(!(status&8))return false;
    if(!bus_.read(bus_.context,config_.address,0x01,shunt)||
       !bus_.read(bus_.context,config_.address,0x02,bus)) {sample_.state=State::io_error;return false;}
    Sample fresh{};fresh.sequence=sample_.sequence+1;fresh.sampled_us=now;
    const int16_t signed_shunt=shunt<0x8000?int16_t(shunt):int16_t(int32_t(shunt)-65536);
    const bool valid=convert(bus,signed_shunt,config_,fresh);
    sample_=fresh;return valid;
}
void TaskEnergy::begin(uint32_t task,uint64_t now) {
    task_=task;active_=true;previous_=false;start_=end_=now;
    last_at_=energy_=covered_=0;last_power_=0;last_sequence_=0;
}
void TaskEnergy::add(const Sample &s) {
    if(!active_)return;
    if(s.state!=State::valid||s.power_microwatts<0) {previous_=false;return;}
    if(s.sampled_us<start_)return;
    if(previous_&&s.sequence==last_sequence_)return;
    if(previous_&&s.sampled_us<=last_at_) {previous_=false;return;}
    // A gap over 300ms is missing coverage for a nominal 10Hz sampler.
    if(previous_&&s.sampled_us-last_at_<=300000) {
        const uint64_t dt=s.sampled_us-last_at_;
        energy_+=(uint64_t(last_power_)+uint64_t(s.power_microwatts))*dt/2000000;
        covered_+=dt;
    }
    previous_=true;last_at_=s.sampled_us;last_power_=s.power_microwatts;
    last_sequence_=s.sequence;end_=s.sampled_us;
}
void TaskEnergy::finish(uint64_t now) {
    if(!active_)return;
    if(now>=end_)end_=now;
    active_=previous_=false;
}
} // namespace power_monitor
