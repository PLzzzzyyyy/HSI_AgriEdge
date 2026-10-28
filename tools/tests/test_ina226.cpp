#include "../../src/ps/power_monitor/ina226.h"
#include <cassert>
#include <cstdio>
using namespace power_monitor;
struct Fixture {
    uint16_t registers[256]={};unsigned writes=0;bool fail=false;
    Fixture(){registers[0xfe]=0x5449;registers[0xff]=0x2260;registers[6]=8;}
    static bool read(void *ctx,uint8_t address,uint8_t reg,uint16_t &value){
        auto &f=*static_cast<Fixture *>(ctx);
        if(f.fail||address!=0x40)return false;
        value=f.registers[reg];return true;
    }
    static bool write(void *ctx,uint8_t address,uint8_t reg,uint16_t value){
        auto &f=*static_cast<Fixture *>(ctx);
        if(f.fail||address!=0x40)return false;
        ++f.writes;f.registers[reg]=value;return true;
    }
    Bus bus(){return {this,read,write};}
};
int main(){
    Fixture f;Ina226 sensor(f.bus());Config c{};Sample s{};
    assert(!sensor.start(0));assert(f.writes==0);
    assert(sensor.identify(0x40));assert(f.writes==0);
    assert(!sensor.configure(c));assert(!sensor.start(0));assert(f.writes==0);
    c.shunt_microohms=10000;c.maximum_milliamps=5000;
    assert(!sensor.configure(c)); // Wiring is never inferred from an ID response.
    c.wiring_confirmed=true;assert(sensor.configure(c));
    f.registers[2]=9600;f.registers[1]=4000; // 12V, 10mV / 10mOhm = 1A, 12W.
    assert(sensor.start(100));assert(f.registers[0]==0x4523);
    assert(!sensor.poll(35100));assert(sensor.poll(36100));
    assert(sensor.sample().bus_microvolts==12000000);
    assert(sensor.sample().current_microamps==1000000);
    assert(sensor.sample().power_microwatts==12000000);
    assert(!sensor.poll(36200));
    assert(sensor.start(100000));assert(!sensor.poll(200001));
    assert(sensor.sample().state==State::timeout);
    assert(sensor.start(300000));f.fail=true;assert(!sensor.poll(340000));
    assert(sensor.sample().state==State::io_error);f.fail=false;
    f.registers[0xff]=0x1234;assert(!sensor.identify(0x40));
    const auto writes=f.writes;assert(!sensor.configure(c));assert(!sensor.start(0));assert(f.writes==writes);
    assert(!Ina226::convert(9600,-4000,c,s));assert(s.state==State::reverse_current);
    assert(s.power_microwatts==-12000000);
    assert(!Ina226::convert(28801,4000,c,s));
    assert(!Ina226::convert(9600,32767,c,s));
    // Same raw shunt measurement on R100 would be 0.1A, not 1A.
    c.shunt_microohms=100000;assert(Ina226::convert(9600,4000,c,s));assert(s.current_microamps==100000);
    c.shunt_microohms=0;assert(!Ina226::convert(9600,4000,c,s));
    c.shunt_microohms=10000;c.maximum_milliamps=800;
    assert(!Ina226::convert(9600,4000,c,s));
    TaskEnergy energy;energy.begin(7,1000);
    s={};s.state=State::valid;s.power_microwatts=10000000;s.sequence=1;s.sampled_us=1000;
    energy.add(s);s.sequence=2;s.sampled_us=101000;energy.add(s);
    assert(energy.measured_microjoules()==1000000);assert(energy.covered_us()==100000);
    energy.add(s);assert(energy.measured_microjoules()==1000000); // Duplicate.
    s.sequence=3;s.sampled_us=501000;energy.add(s); // Missing 400ms is not filled.
    assert(energy.measured_microjoules()==1000000);
    s.sequence=4;s.sampled_us=601000;energy.add(s);assert(energy.measured_microjoules()==2000000);
    s.state=State::io_error;energy.add(s);s.state=State::valid;
    s.sequence=5;s.sampled_us=701000;energy.add(s);assert(energy.measured_microjoules()==2000000);
    energy.finish(801000);const auto frozen=energy.measured_microjoules();
    s.sequence=6;s.sampled_us=901000;energy.add(s);assert(energy.measured_microjoules()==frozen);
    assert(energy.duration_us()==800000);assert(energy.covered_us()==200000);
    energy.begin(8,1000000);assert(energy.task()==8);assert(energy.measured_microjoules()==0);
    energy.add(s);assert(energy.covered_us()==0); // Old task sample.
    std::puts("INA226_OFFLINE_PASS: identity, explicit wiring/shunt, real voltage/current conversion, faults, energy gaps and task isolation");
}
