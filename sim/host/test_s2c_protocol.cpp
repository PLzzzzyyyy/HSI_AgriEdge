// Offline state/wire checks. NOT a simulated board or inference test.
#include "roi_protocol.h"
#include <cassert>
#include <cstdio>
using namespace s2c;
static void p16(uint8_t *p,uint16_t v) { p[0]=uint8_t(v); p[1]=uint8_t(v>>8); }
static void p32(uint8_t *p,uint32_t v) { for(int i=0;i<4;++i) p[i]=uint8_t(v>>(8*i)); }
static uint32_t u32(const uint8_t *p) { return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24; }
int main() {
    const Peer peer={1,5011}, foreign={2,5011}; Packet out; Protocol p(0x12345678);
    uint8_t ping[16]={0x48,0x45,5,1}; p32(ping+12,0x11223344);
    uint8_t start[32]={0x48,0x45,1,1}; p16(start+4,7); p16(start+6,1);
    start[12]=1; p16(start+20,3); p16(start+22,5);
    p32(start+24,WCRC); p32(start+28,0x11223344);
    assert(!p.take_job()); assert(!p.receive(start,32,peer,0,out));
    assert(!p.receive(nullptr,0,peer,0,out));
    for(size_t n=0;n<16;++n) assert(!p.receive(ping,n,peer,0,out));
    assert(p.receive(ping,16,peer,1,out)); assert(out.size==24 && out.bytes[2]==0x84);
    assert(p.status(2,out)); assert(out.size==92 && u32(out.bytes+36)==0x12345678);
    assert(u32(out.bytes+44)==WCRC && u32(out.bytes+16)==0);
    for(size_t n=0;n<32;++n) assert(!p.receive(start,n,peer,3,out));
    start[22]=4; assert(p.receive(start,32,peer,4,out) && out.bytes[13]==8);
    assert(!p.take_job()); start[22]=5;
    start[24]^=1; assert(p.receive(start,32,peer,5,out) && out.bytes[13]==5);
    start[24]^=1; assert(!p.receive(start,32,foreign,6,out));
    assert(p.receive(start,32,peer,7,out)); assert(out.size==20 && out.bytes[13]==0);
    assert(out.bytes[14]==1 && out.bytes[4]==7);
    assert(p.take_job()); assert(!p.take_job());
    assert(p.receive(start,32,peer,8,out) && out.bytes[13]==0); assert(!p.take_job());
    start[13]=1; assert(p.receive(start,32,peer,9,out) && out.bytes[13]==8); start[13]=0;
    start[4]=8; assert(p.receive(start,32,peer,10,out) && out.bytes[13]==9); start[4]=7;
    assert(!p.receive(ping,16,foreign,11,out));
    uint32_t words[15]; for(unsigned i=0;i<15;++i) words[i]=0x80000000u+i%9;
    assert(!p.row(0,words,12,out));
    assert(p.finish(15));
    for(unsigned y=0;y<3;++y) {
        assert(p.row(y,words+y*5,13,out)); assert(out.size==40 && out.bytes[2]==0x81);
        assert(out.bytes[12]==y && out.bytes[16]==5 && out.bytes[18]==0);
        assert(u32(out.bytes+20)==words[y*5]);
    }
    assert(!p.row(3,words,14,out));
    assert(p.status(15,out)); assert(out.bytes[32]==3 && u32(out.bytes+12)==15 && out.bytes[48]==3);
    assert(p.receive(start,32,peer,16,out) && out.bytes[13]==0); assert(!p.take_job());
    Protocol failed(1); assert(failed.receive(ping,16,peer,0,out));
    assert(failed.receive(start,32,peer,1,out)); assert(failed.take_job());
    assert(!failed.finish(14)); assert(!failed.row(0,words,2,out));
    failed.failure(-5,3,out); assert(out.bytes[13]==6 && u32(out.bytes+16)==0xfffffffbu);
    assert(!failed.take_job());
    assert(!p.row(0,words,1000017,out));
    std::puts("PASS: new one-shot START/ACK/ROW/STATUS state and boundary checks");
}
