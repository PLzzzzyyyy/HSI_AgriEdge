#include "roi_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static void p16(uint8_t*p,unsigned v){p[0]=v;p[1]=v>>8;}
static void p32(uint8_t*p,unsigned v){for(unsigned i=0;i<4;++i)p[i]=v>>(8*i);}
static unsigned u32(const uint8_t*p){return p[0]|unsigned(p[1])<<8|unsigned(p[2])<<16|unsigned(p[3])<<24;}
static void head(uint8_t*b,unsigned type,unsigned task,unsigned seq){std::memset(b,0,32);p16(b,0x4548);b[2]=type;b[3]=1;p16(b+4,task);p16(b+6,seq);}
int main(int argc,char **argv){
    s2c::Protocol p(0x12345678,true);s2c::Peer peer{1,2};s2c::Packet out;uint8_t b[32];
    head(b,5,0,0);p32(b+12,99);assert(p.receive(b,16,peer,1,out));
    head(b,1,7,1);b[12]=1;p16(b+20,1);p16(b+22,1);p32(b+24,s2c::WCRC);p32(b+28,99);
    assert(p.receive(b,32,peer,2,out)&&!out.bytes[13]&&p.take_job());assert(p.progress(1)&&p.finish(1));
    head(b,9,7,2);b[13]=1;p32(b+20,s2c::WCRC);assert(!p.receive(b,24,peer,3,out));
    unsigned row,col;uint16_t seq;assert(p.take_probe(row,col,seq)&&p.probe_wants_attention());
    uint32_t a[432]={};for(unsigned i=0;i<72;++i)a[i*6]=1u<<24;
    assert(!p.cache_attention(a,431));a[0]=0;assert(!p.cache_attention(a,432));a[0]=1u<<24;
    assert(p.cache_attention(a,432));int32_t lg[9]={1};p.probe_reply(0xffff0000,lg,4,out);assert(out.bytes[2]==0x85);
    for(unsigned part=0;part<2;++part){
        assert(p.attention_fragment(5+part,out)&&out.size==912&&out.bytes[2]==0x87&&out.bytes[38]==part);
        assert(u32(out.bytes+24)==0x12345678&&u32(out.bytes+28)==99&&u32(out.bytes+32)==p.attention_crc());
        if(argc==2){char path[512];std::snprintf(path,sizeof(path),"%s/attention_%u.bin",argv[1],part);FILE*f=std::fopen(path,"wb");assert(f);assert(std::fwrite(out.bytes,1,out.size,f)==out.size);std::fclose(f);}
    }
    assert(!p.attention_fragment(7,out));assert(p.receive(b,24,peer,8,out)&&out.bytes[2]==0x85);assert(!p.take_probe(row,col,seq));
    assert(p.attention_fragment(9,out)&&out.bytes[38]==0); // exact replay, no HLS
    b[13]=0;assert(p.receive(b,24,peer,10,out)&&out.bytes[13]==8); // same request cannot change mode
    p16(b+6,3);assert(!p.receive(b,24,peer,11,out)&&p.take_probe(row,col,seq)&&!p.probe_wants_attention());
    p.probe_reply(0xffff0000,lg,12,out);assert(out.bytes[2]==0x85&&!p.attention_fragment(13,out));
    std::puts("ATTENTION_PROTOCOL_PASS actual private protocol; synthetic Q0.24; fragmentation replay identity ordinary LOGITS");
}
