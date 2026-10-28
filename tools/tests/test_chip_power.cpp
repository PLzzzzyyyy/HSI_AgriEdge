#include "roi_protocol.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
static void p32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));}
int main(){
    using namespace s2c;
    PowerEstimate estimate;
    assert(std::abs(estimate.view(0).watts-6.029)<.0001);
    assert(!estimate.view(0).temperature_valid);
    estimate.temperature(55,true,1000000);estimate.begin(1,1000000);
    auto value=estimate.view(2000000);
    assert(std::abs(value.joules-6.173)<.0001&&value.fallback_us==0);
    // Expired thermometer: split exactly at 3 s, fall back to declared 40 C.
    value=estimate.view(5000000);
    assert(std::abs(value.joules-(3*6.173+6.029))<.0001);
    assert(value.duration_us==4000000&&value.fallback_us==1000000&&!value.temperature_valid);
    estimate.finish(6000000);const auto frozen=estimate.view(6000000);
    estimate.temperature(85,true,7000000);value=estimate.view(9000000);
    assert(value.joules==frozen.joules&&value.duration_us==frozen.duration_us&&!value.active);
    estimate.begin(2,9000000);value=estimate.view(9000000);
    assert(value.task==2&&value.joules==0&&value.duration_us==0);
    estimate.temperature(NAN,true,9000000);assert(!estimate.view(9000000).temperature_valid);

    Protocol protocol(17,true);Packet reply;
    uint8_t ping[16]={0x48,0x45,5,1};p32(ping+12,18);
    assert(protocol.receive(ping,16,{1,5010},1000000,reply));
    protocol.set_temperature(40,40,true,1000000);
    uint8_t start[32]={0x48,0x45,1,1,1,0,1,0};start[12]=1;start[20]=3;start[22]=5;
    p32(start+24,WCRC);p32(start+28,18);
    assert(protocol.receive(start,32,{1,5010},1100000,reply)&&reply.bytes[13]==0);
    assert(protocol.take_job());assert(protocol.progress(15));assert(protocol.finish(15,2100000));
    value=protocol.power_view(3000000);
    assert(std::abs(value.joules-6.029)<.0001&&value.duration_us==1000000&&!value.active);
    assert(protocol.power_packet(3000000,reply)&&reply.size==80&&reply.bytes[2]==0x8c);
    double energy;std::memcpy(&energy,reply.bytes+48,8);assert(std::abs(energy-6.029)<.0001);
    assert(!protocol.power_packet(3000100,reply));
    // Duplicate START must not reset the finished energy account.
    assert(protocol.receive(start,32,{1,5010},3100000,reply));
    assert(protocol.power_view(3100000).joules==value.joules);
    // Pausing is part of wall-time energy; STOP freezes it immediately.
    start[4]=2;start[6]=2;assert(protocol.receive(start,32,{1,5010},4000000,reply));
    assert(protocol.take_job());assert(protocol.progress(15));
    uint8_t stop[12]={0x48,0x45,2,1,2,0,3,0};
    assert(protocol.receive(stop,12,{1,5010},5000000,reply));
    assert(protocol.apply_control(5000000,reply));
    value=protocol.power_view(6000000);assert(!value.active&&value.duration_us==1000000);
    assert(value.fallback_us==1000000);
    // Canvas rendering is checked separately; none of these calls touch BSP/IO.
    std::puts("PASS chip power interpolation, expiry, integral, task identity, duplicate START and STOP freeze");
}
