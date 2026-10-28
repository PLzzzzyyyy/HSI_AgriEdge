#include "roi_protocol.h"
#include <cassert>
#include <cstring>
static void p32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));}
int main(){
    s2c::Protocol protocol(17,true);s2c::Packet reply;
    uint8_t ping[16]={0x48,0x45,5,1};p32(ping+12,18);
    assert(protocol.receive(ping,16,{1,5010},1000000,reply));
    assert(!protocol.queue_key(7,1,1000010));
    assert(protocol.queue_key(5,1,1000010));assert(!protocol.queue_key(6,1,1000011));
    assert(protocol.key_packet(1000020,reply));assert(reply.size==28&&reply.bytes[2]==0x8b&&reply.bytes[24]==5&&reply.bytes[25]==1);
    uint8_t ack[28]={0x48,0x45,0x17,1};p32(ack+12,17);p32(ack+16,19);p32(ack+20,1);ack[24]=2;
    (void)protocol.receive(ack,28,{1,5010},1100000,reply);assert(protocol.key_state()==1);
    p32(ack+16,18);(void)protocol.receive(ack,28,{1,5010},1200000,reply);assert(protocol.key_state()==2);
    assert(protocol.key_packet(1400000,reply)); // receipt/result retry retains the same event ID
    ack[24]=3;ack[25]=10;ack[26]=1;
    (void)protocol.receive(ack,28,{1,5010},1500000,reply);assert(protocol.key_state()==3&&protocol.key_scene()==1);
    ack[24]=2;(void)protocol.receive(ack,28,{1,5010},1600000,reply);assert(protocol.key_state()==3);
    assert(protocol.queue_key(6,3,1700000));
    assert(protocol.key_packet(1800000,reply));assert(reply.bytes[26]==1); // next hold uses selected Honghu, not old active scene
    (void)protocol.key_packet(7000001,reply);s2c::KeyEvent offline;
    assert(protocol.take_local_key(7000001,offline));assert(offline.key==6&&offline.gesture==3);
    assert(protocol.key_state()==2&&protocol.key_code()==13);
    // A real PC START is shown as PC, and a physical START retains KEY6's
    // polygon action despite its inference request being a rectangle.
    for(unsigned physical=0;physical<2;++physical){
        s2c::Protocol p(17,true);(void)p.receive(ping,16,{1,5010},1000000,reply);
        if(physical){assert(p.queue_key(6,2,1010000));}
        uint8_t start[32]={0x48,0x45,1,1,1,0,1,0};start[12]=1;start[20]=3;start[22]=5;p32(start+24,s2c::WCRC);p32(start+28,18);
        assert(p.receive(start,32,{1,5010},1100000,reply));assert(reply.bytes[13]==0);
        auto display=p.dispatch_view();assert(display.source==(physical?6u:0u));
        assert(display.action==(physical?s2c::DispatchAction::parcel:s2c::DispatchAction::region));
        assert(p.take_job());assert(p.progress(15));assert(p.finish(15));
        if(!physical)assert(p.dispatch_view().phase==s2c::DispatchPhase::done);
    }
}
