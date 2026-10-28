#include "roi_protocol.h"
#include "roi_models.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>
using namespace s2c;
static void p16(uint8_t *b,unsigned n){b[0]=uint8_t(n);b[1]=uint8_t(n>>8);}
static void p32(uint8_t *b,uint32_t n){for(unsigned i=0;i<4;++i)b[i]=uint8_t(n>>(8*i));}
static uint32_t u32(const uint8_t *b){return b[0]|uint32_t(b[1])<<8|uint32_t(b[2])<<16|uint32_t(b[3])<<24;}
struct Disk: ModelPersistence {unsigned calls=0;bool save(const ModelKey &,const uint8_t *) override {++calls;return true;}};
struct Engine: ModelActivation {unsigned calls=0;int load(const ModelEntry &,const ModelEntry &) override {++calls;return 0;}};
struct Fixture {
    Models models;ResultStore store;Protocol p;Packet out;uint8_t b[1412];unsigned seq=0;uint64_t now=0;Peer peer{1,2};Disk disk;Engine engine;
    Fixture():p(123,true,&store,&models,"1111111111111111111111111111111111111111111111111111111111111111") {assert(p.release_bound());head(5,0);p32(b+12,99);assert(receive(16));}
    void head(unsigned type,unsigned task=0){std::memset(b,0,sizeof(b));p16(b,0x4548);b[2]=uint8_t(type);b[3]=1;p16(b+4,task);p16(b+6,seq++);}
    bool receive(size_t n){return p.receive(b,n,peer,++now,out);}
    uint32_t upload(unsigned scene,unsigned kind) {
        std::vector<uint8_t> data(model_bytes(scene,kind),0);
        if(kind){p32(data.data(),0x32455454);p32(data.data()+4,2);p32(data.data()+8,scene_contract(scene)->classes);p32(data.data()+12,16);data[191232]=3;}
        else data[0]=3;
        const uint32_t crc=model_crc(data.data(),data.size());
        head(0x11);b[12]=uint8_t(scene);b[13]=uint8_t(kind);p32(b+16,uint32_t(data.size()));p32(b+20,crc);std::strcpy(reinterpret_cast<char *>(b+24),"demo");
        // A newer heartbeat may arrive before this command. It is still newer
        // than the preceding model command and must not be rejected as stale.
        uint8_t begin[40];std::memcpy(begin,b,40);head(5);p32(b+12,99);assert(receive(16));std::memcpy(b,begin,40);
        assert(receive(40)&&!out.bytes[13]&&u32(out.bytes+16)==0);uint8_t old[40];std::memcpy(old,b,40);
        for(size_t off=0;off<data.size();) {
            const size_t n=data.size()-off>1384?1384:data.size()-off;
            head(0x10);b[12]=uint8_t(scene);b[13]=uint8_t(kind);p32(b+16,uint32_t(off));p32(b+20,uint32_t(data.size()));p32(b+24,crc);std::memcpy(b+28,data.data()+off,n);
            assert(receive(28+n)&&!out.bytes[13]&&u32(out.bytes+16)==off+n);
            assert(receive(28+n)&&!out.bytes[13]&&u32(out.bytes+16)==off+n); // repeat ACK, no rewrite
            off+=n;
        }
        uint8_t current[1412];std::memcpy(current,b,sizeof(b));std::memcpy(b,old,40);
        assert(receive(40)&&out.bytes[13]==8);std::memcpy(b,current,sizeof(b));
        const unsigned saved=disk.calls;head(0x12);p32(b+12,crc);
        assert(!receive(16)&&disk.calls==saved);assert(!receive(16)&&disk.calls==saved);
        assert(p.model_poll(disk,engine,++now,out)&&out.bytes[12]==0x12&&!out.bytes[13]&&u32(out.bytes+16)==1);
        assert(disk.calls==saved+1);assert(receive(16)&&!out.bytes[13]&&disk.calls==saved+1);
        return crc;
    }
};
int main() {
    std::unique_ptr<Fixture> ptr(new Fixture);auto &f=*ptr;
    f.upload(2,0);
    // Heartbeats can span > half a u16 sequence range between two model
    // commands (e.g. a long paused task). Freshness follows the live peer's
    // receive sequence, not the last model opcode's now-ancient sequence.
    for(unsigned i=0;i<33000;++i){f.head(5);p32(f.b+12,99);assert(f.receive(16));}
    const uint32_t han=f.upload(2,1);f.upload(1,0);const uint32_t hong=f.upload(1,1);
    f.head(7);assert(f.receive(12)&&f.out.size==60+4*28&&f.out.bytes[19]==4);
    for(unsigned i=0;i<16;++i)assert(f.out.bytes[44+4*28+i]==0x11);
    assert(f.out.bytes[44]==2&&f.out.bytes[45]==0&&!std::strcmp(reinterpret_cast<char *>(f.out.bytes+56),"demo"));
    f.head(0x13);f.b[12]=2;p32(f.b+16,han);assert(!f.receive(20)&&!f.engine.calls);
    assert(f.p.model_poll(f.disk,f.engine,++f.now,f.out)&&!f.out.bytes[13]&&f.engine.calls==1);
    f.head(1,7);f.b[12]=1;f.b[13]=2;p16(f.b+16,1216);p16(f.b+18,302);p16(f.b+20,1);p16(f.b+22,1);p32(f.b+24,han);p32(f.b+28,99);
    assert(f.receive(32)&&!f.out.bytes[13]);assert(f.p.scene()==2&&f.p.wcrc()==han&&f.p.take_job());
    auto *slot=f.store.find(99,7);assert(slot&&slot->scene==2&&slot->scene_width==303&&slot->scene_height==1217&&slot->classes==16&&slot->wcrc==han&&!std::strcmp(slot->tag,"demo"));
    f.head(9,7);f.b[12]=2;p16(f.b+14,1216);p16(f.b+16,302);p32(f.b+20,han);assert(!f.receive(24));
    unsigned first_row,first_col;uint16_t first_seq;assert(f.p.take_probe(first_row,first_col,first_seq));
    int32_t first_logits[24]={};f.p.probe_reply(0xffff000f,first_logits,++f.now,f.out);
    f.head(3,7);assert(f.receive(12)&&!f.out.bytes[13]);assert(f.p.apply_control(++f.now,f.out)&&f.p.paused());
    for(unsigned i=0;i<33000;++i){f.head(5,7);p32(f.b+12,99);assert(f.receive(16));}
    f.head(4,7);assert(f.receive(12)&&!f.out.bytes[13]);assert(f.p.apply_control(++f.now,f.out)&&!f.p.paused());
    f.head(9,7);f.b[12]=2;p16(f.b+14,1216);p16(f.b+16,302);p32(f.b+20,han);assert(!f.receive(24));
    assert(f.p.take_probe(first_row,first_col,first_seq));f.p.probe_reply(0xffff000f,first_logits,++f.now,f.out);
    // WACT when=0 waits for a terminal task, not an arbitrary live/paused row.
    f.head(0x13,7);f.b[12]=1;p32(f.b+16,hong);assert(!f.receive(20));
    assert(!f.p.model_poll(f.disk,f.engine,++f.now,f.out)&&f.engine.calls==1);
    // Offline same-session recovery remains possible with a queued WACT;
    // otherwise PAUSE + owner loss could leave a permanent control deadlock.
    f.now+=1000001;f.peer.port=3;f.head(5,7);p32(f.b+12,99);assert(f.receive(16)&&f.out.to.port==3);
    Peer stale{1,2};assert(!f.p.receive(f.b,16,stale,++f.now,f.out));
    uint32_t word=0xffff0010;assert(!f.store.append(99,7,1216,302,1,&word));word=0xffff000f;
    assert(f.store.append(99,7,1216,302,1,&word)&&f.p.progress(1)&&f.p.finish(1));
    assert(f.p.model_poll(f.disk,f.engine,++f.now,f.out)&&!f.out.bytes[13]&&f.engine.calls==2);
    assert(slot->wcrc==han&&slot->scene==2&&slot->words[1216*303+302]==word); // no reinterpretation after WACT
    f.head(7,7);assert(f.receive(12)&&f.out.bytes[27]==2&&u32(f.out.bytes+36)==han);
    f.head(6,7);p16(f.b+12,1);p16(f.b+16,1216);p16(f.b+18,1);assert(f.receive(20)&&!f.out.bytes[13]);
    assert(f.p.replay(++f.now,f.out)&&u32(f.out.bytes+20)==word);
    // A different model/scene PROBE carries its own shape/classes/CRC identity.
    f.head(9,7);f.b[12]=1;p16(f.b+14,939);p16(f.b+16,474);p32(f.b+20,hong);
    assert(!f.receive(24));unsigned row,col;uint16_t seq;assert(f.p.take_probe(row,col,seq)&&row==939&&col==474);
    assert(f.p.probe_scene()==1&&f.p.probe_wcrc()==hong&&f.p.probe_classes()==22);
    int32_t logits[24]={};logits[21]=123;f.p.probe_reply(0xffff0015,logits,++f.now,f.out);
    assert(f.out.size==28+22*4&&f.out.bytes[14]==1&&f.out.bytes[15]==22&&u32(f.out.bytes+20)==hong&&u32(f.out.bytes+28+21*4)==123);
    f.head(0x13,7);f.b[12]=1;f.b[13]=1;p32(f.b+16,hong);assert(f.receive(20)&&f.out.bytes[13]==8&&f.engine.calls==2);
    // Preflight rejection is a terminal empty task, not permanent DMA fault.
    f.head(1,8);f.b[12]=1;f.b[13]=1;p16(f.b+20,1);p16(f.b+22,1);p32(f.b+24,hong);p32(f.b+28,99);
    assert(f.receive(32)&&!f.out.bytes[13]&&f.p.take_job());f.p.reject_job(-203,++f.now,f.out);
    assert(f.receive(32)&&f.out.bytes[13]==6&&int32_t(u32(f.out.bytes+16))==-203);
    p16(f.b+4,9);p16(f.b+6,f.seq++);assert(f.receive(32)&&!f.out.bytes[13]);
    f.models.fault(-55);p16(f.b+4,10);p16(f.b+6,f.seq++);assert(f.receive(32)&&f.out.bytes[13]==6);
    std::puts("model protocol PASS: deferred IO/LOAD_W, repeats/stale, INFO, three-scene task identity, old slot/replay, PROBE classes, no hot switch");
}
