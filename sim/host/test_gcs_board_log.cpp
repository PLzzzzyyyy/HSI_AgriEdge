#include "roi_board_log.h"
#include "roi_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
static void p16(uint8_t *p,unsigned v){p[0]=uint8_t(v);p[1]=uint8_t(v>>8);}
static void p32(uint8_t *p,unsigned v){for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));}
static unsigned u32(const uint8_t *p){return p[0]|unsigned(p[1])<<8|unsigned(p[2])<<16|unsigned(p[3])<<24;}
static void head(uint8_t *b,unsigned type,unsigned task,unsigned seq){std::memset(b,0,32);p16(b,0x4548);b[2]=uint8_t(type);b[3]=1;p16(b+4,task);p16(b+6,seq);}
static void query(uint8_t *b,unsigned task,unsigned session,unsigned offset=0,unsigned size=0,unsigned boot=0x12345678){
    head(b,0x14,task,91);p32(b+12,boot);p32(b+16,session);p32(b+20,offset);p32(b+24,size);
}
int main(){
    static s2c::BoardLog log;
    const std::string release(64,'a');
    const std::string build="S2C BUILD app=gcs_r1_abi4 release="+release+" sources="+std::string(64,'b')+" xsa="+std::string(64,'c')+"\r\n";
    assert(build.size()==242&&log.append(build.c_str()));
    auto boot=log.view(0,0);assert(boot.valid&&!boot.overflow&&boot.size==242);
    assert(std::memcmp(boot.data,build.data(),build.size())==0); // actual bounded production sink, not an ideal parser string
    static s2c::ResultStore store;
    s2c::Protocol protocol(0x12345678,true,&store,nullptr,release.c_str(),&log);
    s2c::Peer owner{1,2},other{1,3};s2c::Packet out;uint8_t b[32];
    head(b,5,0,0);p32(b+12,99);
    assert(protocol.receive(b,16,owner,1,out)&&out.bytes[2]==0x83&&out.bytes[13]!=0);
    assert(protocol.session()==0&&protocol.received_count()==0); // startup cannot claim a task peer
    head(b,7,0,0);assert(protocol.receive(b,12,other,2,out)&&out.bytes[2]==0x86);
    query(b,0,0);assert(protocol.receive(b,28,other,3,out)&&out.bytes[2]==0x88);
    assert(out.to.port==other.port&&out.size==282&&u32(out.bytes+12)==0x12345678);
    assert(u32(out.bytes+28)==242&&u32(out.bytes+32)==s2c::model_crc(reinterpret_cast<const uint8_t *>(build.data()),build.size()));
    assert(std::memcmp(out.bytes+40,build.data(),242)==0&&protocol.session()==0);
    query(b,0,0,0,0,0x12345679);assert(protocol.receive(b,28,other,4,out)&&out.bytes[2]==0x83&&out.bytes[13]!=0);
    query(b,0,99);assert(!protocol.receive(b,28,other,5,out)); // unowned model stream stays private
    protocol.mark_startup_ready();
    head(b,5,0,0);p32(b+12,99);assert(protocol.receive(b,16,owner,6,out)&&out.bytes[2]==0x84);
    assert(log.view(99,0).valid&&log.view(99,0).size==0); // model session, not boot or a fake task
    for(unsigned i=0;i<100;++i)assert(log.append_model(99,"S2C MODELCMD retained session record independent of boot/task\r\n"));
    assert(log.view(99,0).size>4096&&!log.view(0,0).overflow&&log.view(0,0).size==242);
    assert(!log.append_model(98,"wrong session\r\n"));
    const auto before_reads=protocol.received_count();
    query(b,0,99);assert(protocol.receive(b,28,owner,7,out)&&out.bytes[2]==0x88&&u32(out.bytes+16)==99);
    query(b,0,99);assert(!protocol.receive(b,28,other,8,out));
    query(b,0,98);assert(protocol.receive(b,28,owner,9,out)&&out.bytes[2]==0x83&&out.bytes[13]!=0);
    assert(protocol.received_count()==before_reads); // diagnostic reads never refresh heartbeat/order
    for(unsigned task=1;task<=5;++task){
        head(b,1,task,task*10);b[12]=1;p16(b+16,549);p16(b+18,399);p16(b+20,1);p16(b+22,1);p32(b+24,s2c::WCRC);p32(b+28,99);
        assert(protocol.receive(b,32,owner,task*100,out)&&out.bytes[13]==0&&protocol.take_job());
        assert(log.append("S2C task first line\r\n"));
        auto initial=log.view(99,task);const unsigned first=unsigned(initial.size);
        const unsigned first_crc=s2c::model_crc(initial.data,initial.size);
        assert(log.append("S2C task next line\r\n"));
        const auto task_size=log.view(99,task).size;
        const auto model_prefix=log.view(99,0);
        const unsigned model_size=unsigned(model_prefix.size),model_crc=s2c::model_crc(model_prefix.data,model_prefix.size);
        assert(log.append_model(99,"S2C MODELCMD while task is running\r\n"));
        assert(log.view(99,task).size==task_size&&log.view(0,0).size==242);
        const auto reads=protocol.received_count();
        query(b,0,99,0,model_size);assert(protocol.receive(b,28,owner,task*100+1,out)&&out.bytes[2]==0x88);
        assert(u32(out.bytes+28)==model_size&&u32(out.bytes+32)==model_crc&&protocol.received_count()==reads);
        query(b,task,99,0,first);assert(protocol.receive(b,28,owner,task*100+1,out)&&out.bytes[2]==0x88);
        assert(u32(out.bytes+28)==first&&u32(out.bytes+32)==first_crc); // stable prefix while later records append
        query(b,task,99);assert(!protocol.receive(b,28,other,task*100+2,out)); // never steal task socket
        query(b,task,99,0,65537);assert(protocol.receive(b,28,owner,task*100+3,out)&&out.bytes[13]!=0);
        uint32_t word=0x80000001;assert(store.append(99,task,549,399,1,&word));assert(protocol.progress(1)&&protocol.finish(1));
    }
    assert(!log.view(99,1).valid&&!store.find(99,1));
    assert(log.view(99,2).valid&&store.find(99,2));
    assert(!log.begin(99,5)); // duplicate selection cannot erase an already used stream
    query(b,1,99);assert(protocol.receive(b,28,owner,600,out)&&out.bytes[2]==0x83&&out.bytes[13]==7);
    query(b,2,99);assert(protocol.receive(b,28,owner,601,out)&&out.bytes[2]==0x88&&out.bytes[4]==2);
    static s2c::BoardLog large;
    assert(large.begin(7,1));
    const std::string record(300,'x');const std::string terminated=record+"\r\n";
    while(large.append(terminated.c_str())){}
    const auto exhausted=large.view(7,1);assert(exhausted.overflow&&exhausted.size<=s2c::BoardLog::TASK_BYTES);
    assert(!large.append("more\r\n")&&large.view(7,1).size==exhausted.size);
    assert(large.begin(7,2)&&large.append("new stream\r\n")&&!large.view(7,2).overflow);
    static s2c::BoardLog malformed;
    assert(!malformed.append("unterminated line")&&malformed.view(0,0).overflow);
    static s2c::BoardLog model_full;
    assert(model_full.append(build.c_str()));
    s2c::Protocol model_protocol(0x12345678,true,nullptr,nullptr,release.c_str(),&model_full);
    model_protocol.mark_startup_ready();head(b,5,0,1);p32(b+12,77);
    assert(model_protocol.receive(b,16,owner,1,out)&&out.bytes[2]==0x84);
    const std::string block=std::string(254,'m')+"\r\n";
    for(unsigned i=0;i<256;++i)assert(model_full.append_model(77,block.c_str()));
    auto full=model_full.view(77,0);assert(full.size==65536&&!full.overflow);
    const auto full_crc=s2c::model_crc(full.data,full.size);
    query(b,0,77);assert(model_protocol.receive(b,28,owner,2,out)&&out.bytes[23]==0&&u32(out.bytes+28)==65536);
    assert(model_full.begin_model(77)&&!model_full.begin_model(78)); // recovery cannot reset a full stream
    assert(!model_full.append_model(77,"\r\n"));
    full=model_full.view(77,0);assert(full.overflow&&full.size==65536&&s2c::model_crc(full.data,full.size)==full_crc);
    query(b,0,77);assert(model_protocol.receive(b,28,owner,3,out)&&out.bytes[2]==0x88&&out.bytes[23]==1);
    assert(!model_full.append_model(77,"later\r\n")&&model_full.view(0,0).size==242&&!model_full.view(0,0).overflow);
    assert(model_full.begin(77,1)&&model_full.append("task after model overflow\r\n")&&!model_full.view(77,1).overflow);
    static s2c::BoardLog model_bad;
    assert(model_bad.begin_model(2)&&!model_bad.append_model(2,nullptr)&&model_bad.view(2,0).overflow);
    assert(model_bad.begin_model(2)&&!model_bad.append_model(2,"no reset\r\n")&&!model_bad.view(0,0).overflow);
    std::puts("board log PASS: full BUILD, model/task isolation, exact-capacity overflow, no reset, stable prefix, same peer, four tasks");
}
