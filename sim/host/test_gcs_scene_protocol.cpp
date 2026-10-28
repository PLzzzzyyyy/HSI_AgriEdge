// New full-scene protocol byte fixtures, no networking or numerical work.
#include "roi_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static void p16(unsigned char *p,unsigned v){p[0]=v;p[1]=v>>8;}
static void p32(unsigned char *p,unsigned v){for(unsigned i=0;i<4;++i)p[i]=v>>(8*i);}
static unsigned u32(const unsigned char *p){return p[0]|unsigned(p[1])<<8|unsigned(p[2])<<16|unsigned(p[3])<<24;}
int main(){
    s2c::Protocol p(0x12345678);s2c::Peer peer{0x0101a8c0,54321};s2c::Packet out;
    unsigned char b[32]{};p16(b,0x4548);b[2]=5;b[3]=1;p32(b+12,42);
    assert(p.receive(b,16,peer,0,out));assert(out.size==24);
    b[2]=1;p16(b+4,7);p16(b+6,1);std::memset(b+12,0,20);p16(b+20,550);p16(b+22,400);p32(b+24,s2c::WCRC);p32(b+28,42);
    assert(p.receive(b,32,peer,10,out)&&out.bytes[13]==0);assert(p.full_scene()&&p.total()==220000&&p.take_job());
    assert(!p.take_job());assert(!p.finish(15));assert(p.progress(4));assert(!p.progress(3));
    uint32_t words[348]{};assert(!p.row_segment(0,0,348,words,20,out));
    assert(p.progress(400));assert(p.row_segment(0,0,348,words,21,out)&&out.size==1412);
    assert(p.row_segment(0,348,52,words,22,out)&&out.size==228&&out.bytes[14]==92&&out.bytes[15]==1);
    assert(!p.row_segment(0,348,53,words,23,out));assert(!p.row_segment(0,0,349,words,24,out));
    assert(p.status(25,out)&&u32(out.bytes+12)==400&&u32(out.bytes+16)==220000&&out.bytes[32]==1);
    assert(!p.finish(219999));assert(p.progress(220000));assert(p.finish(220000));
    assert(p.status(30,out)&&out.bytes[32]==3&&u32(out.bytes+12)==220000);
    assert(p.receive(b,32,peer,40,out)&&out.bytes[13]==0);assert(!p.take_job());
    // A dispatched probe still owns the input/output buffers. Late older seqs
    // must never evict the one-entry reply cache or trigger new inference.
    b[2]=9;std::memset(b+12,0,20);p16(b+6,65534);p16(b+14,549);p16(b+16,399);p32(b+20,s2c::WCRC);
    assert(!p.receive(b,24,peer,41,out));unsigned row,col;uint16_t seq;
    assert(p.take_probe(row,col,seq)&&row==549&&col==399&&seq==65534);
    assert(!p.receive(b,24,peer,42,out)&&!p.take_probe(row,col,seq));
    p16(b+6,65535);assert(p.receive(b,24,peer,43,out)&&out.bytes[13]==8);
    assert(!p.take_probe(row,col,seq));
    int32_t logits[9]={0,0,0,0,65536,0,0,0,0};p.probe_reply(0xabcd0004,logits,44,out);
    p16(b+6,65534);assert(p.receive(b,24,peer,45,out)&&out.size==64&&u32(out.bytes+24)==0xabcd0004);
    p16(b+16,398);assert(p.receive(b,24,peer,46,out)&&out.bytes[13]==8);p16(b+16,399);
    p16(b+6,1);assert(!p.receive(b,24,peer,47,out)&&p.take_probe(row,col,seq)&&seq==1);
    p.probe_reply(0xabcd0004,logits,48,out);
    p16(b+6,65534);assert(p.receive(b,24,peer,49,out)&&out.bytes[13]==8&&!p.take_probe(row,col,seq));
    // Wrong peer cannot read cached logits; wrong task/scene/CRC cannot dispatch.
    assert(!p.receive(b,24,{peer.ipv4,1234},50,out));
    p16(b+6,2);p16(b+4,8);assert(p.receive(b,24,peer,51,out)&&out.bytes[13]==9);p16(b+4,7);
    b[12]=1;assert(p.receive(b,24,peer,52,out)&&out.bytes[13]==8);b[12]=0;
    p32(b+20,1);assert(p.receive(b,24,peer,53,out)&&out.bytes[13]==5);
    s2c::Protocol q(1);b[2]=5;p32(b+12,42);q.receive(b,16,peer,0,out);b[2]=1;std::memset(b+12,0,20);p16(b+20,550);p16(b+22,400);p32(b+24,s2c::WCRC);p32(b+28,42);q.receive(b,32,peer,1,out);assert(q.take_job());q.failure(-5,2,out);assert(out.bytes[13]==6);assert(!q.finish(220000)&&!q.progress(4));
    std::puts("PASS full protocol: existing START/STATUS, 1412/228B row segments, progress and fail closed");
}
