// OFFLINE pipe peer. Uses the actual private Protocol/Models/ResultStore.
// Also uses the actual private ModelSd adapter against an in-memory FatFs API.
// No sockets, UART, physical SD, driver, PL or numeric inference. Foreground
// scheduler/LOAD_W and generated CLASS/LOGITS below are explicit test doubles.
#include "roi_protocol.h"
#include "roi_model_sd.h"
#include "ram_fs.h"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <map>
#include <new>
#include <sstream>
#include <string>
#include <vector>
using namespace s2c;
namespace {
constexpr uint32_t BOOT=0x12345678;
struct MemoryDisk: ModelPersistence {
    ModelSd storage;unsigned calls=0;bool fail=false;
    bool save(const ModelKey &k,const uint8_t *data) override {
        ++calls;model_test_fs::always_fail=fail?"write":"";
        return storage.save(k,data);
    }
} disk;
struct Engine: ModelActivation {
    unsigned calls=0;int failure=0;
    int load(const ModelEntry &a,const ModelEntry &b) override {
        ++calls;assert(model_pair(b.key.scene,a.data,b.data));return failure;
    }
    bool uncertain() const override {return failure!=-203;}
} engine;
Models models;ResultStore results;Protocol protocol(BOOT,true,&results,&models,"1111111111111111111111111111111111111111111111111111111111111111");
uint64_t now=0,compute=0;uint32_t completed=0,whole_crc=0xffffffffu;
unsigned jobs=0,probes=0;bool step_enabled=true,parked=false;
Packet reply;
uint16_t u16(const uint8_t *p){return uint16_t(p[0]|uint16_t(p[1])<<8);}
uint32_t u32(const uint8_t *p){return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
void emit(Packet &p) {
    stamp(p,now);std::cout<<"PACKET "<<p.to.ipv4<<" "<<p.to.port<<" ";
    static const char hex[]="0123456789abcdef";
    for(size_t i=0;i<p.size;++i)std::cout<<hex[p.bytes[i]>>4]<<hex[p.bytes[i]&15];
    std::cout<<"\n";protocol.sent(p.size,true);
}
uint32_t word(unsigned scene,unsigned x,unsigned y) {
    return 0xabcd0000u|((x+y+scene)%scene_contract(scene)->classes);
}
void log_end(const char *kind) {
    char line[180];std::snprintf(line,sizeof(line),"S2C %s session=%08lx task=%u completed=%lu compute_us=%llu crc32=%08lx",
        kind,(unsigned long)protocol.session(),unsigned(protocol.task()),(unsigned long)completed,
        (unsigned long long)compute,(unsigned long)(whole_crc^0xffffffffu));std::cout<<"LOG "<<line<<"\n";
}
void poll() {
    if(parked)return;
    if(protocol.status(now,reply))emit(reply);
    if(protocol.model_poll(disk,engine,now,reply)) {
        emit(reply);const auto *active=models.active();char line[180];
        std::snprintf(line,sizeof(line),"S2C MODELCMD session=%08lx type=%u seq=%u code=%u value=%08lx crc=%08lx active_scene=%d active_crc=%08lx sd_rc=%d",
            (unsigned long)protocol.session(),unsigned(reply.bytes[12]),unsigned(u16(reply.bytes+14)),unsigned(reply.bytes[13]),
            (unsigned long)u32(reply.bytes+16),(unsigned long)protocol.model_command_crc(),active?int(active->key.scene):-1,
            (unsigned long)(active?active->key.crc:0),disk.fail?1:0);std::cout<<"LOG "<<line<<"\n";
        if(models.faulted()){parked=true;return;}
    }
    if(protocol.take_job()) {
        completed=0;compute=0;whole_crc=0xffffffffu;
        const auto r=models.activate(protocol.scene(),protocol.wcrc(),0,true,engine);
        if(r.code) {
            if(models.faulted()){protocol.failure(int32_t(r.value),now,reply);parked=true;}
            else protocol.reject_job(int32_t(r.value),now,reply);
            emit(reply);return;
        }
        ++jobs;char line[180];const auto *active=models.active();
        std::snprintf(line,sizeof(line),"S2C TASK_BEGIN session=%08lx task=%u scene=%u model=%s wcrc=%08lx x=%u y=%u w=%u h=%u classes=%u",
            (unsigned long)protocol.session(),unsigned(protocol.task()),protocol.scene(),active->key.tag,(unsigned long)protocol.wcrc(),
            protocol.x(),protocol.y(),protocol.width(),protocol.height(),unsigned(scene_contract(protocol.scene())->classes));
        std::cout<<"LOG "<<line<<"\n";
    }
    if(protocol.apply_control(now,reply)) {
        emit(reply);char line[160];std::snprintf(line,sizeof(line),"S2C CONTROL session=%08lx task=%u type=%u seq=%u completed=%lu",
            (unsigned long)protocol.session(),unsigned(protocol.task()),unsigned(reply.bytes[12]),unsigned(u16(reply.bytes+14)),(unsigned long)completed);
        std::cout<<"LOG "<<line<<"\n";if(protocol.stopped())log_end("TASK_STOP");
    }
    unsigned row,col;uint16_t seq;
    if(protocol.take_probe(row,col,seq)) {
        ++probes;const unsigned classes=protocol.probe_classes();const uint32_t value=word(protocol.probe_scene(),col,row);
        uint32_t attention[432]={};
        if(protocol.probe_wants_attention()){
            // Synthetic protocol fixture ONLY; never a numerical/board oracle.
            for(unsigned i=0;i<72;++i)attention[i*6]=1u<<24;
            assert(protocol.cache_attention(attention,432));
        }
        int32_t logits[24]={};logits[value&255]=77777;protocol.probe_reply(value,logits,now,reply);emit(reply);
        char line[180];std::snprintf(line,sizeof(line),"S2C PROBE session=%08lx task=%u seq=%u scene=%u wcrc=%08lx ncls=%u x=%u y=%u class_word=%08lx",
            (unsigned long)protocol.session(),unsigned(protocol.task()),unsigned(seq),protocol.probe_scene(),
            (unsigned long)protocol.probe_wcrc(),classes,col,row,(unsigned long)value);std::cout<<"LOG "<<line<<"\n";
        for(unsigned i=0;i<classes;++i){std::snprintf(line,sizeof(line),"S2C LOGIT session=%08lx task=%u seq=%u class=%u q16=%ld",
            (unsigned long)protocol.session(),unsigned(protocol.task()),unsigned(seq),i,(long)logits[i]);std::cout<<"LOG "<<line<<"\n";}
        if(protocol.probe_wants_attention()){
            std::snprintf(line,sizeof(line),"S2C ATTN session=%08lx task=%u seq=%u layers=12 n=6 frac=24 crc32=%08lx",
                (unsigned long)protocol.session(),unsigned(protocol.task()),unsigned(seq),(unsigned long)protocol.attention_crc());std::cout<<"LOG "<<line<<"\n";
            for(unsigned l=0;l<12;++l){std::snprintf(line,sizeof(line),"S2C ATTN_LAYER session=%08lx task=%u seq=%u layer=%u crc32=%08lx",
                (unsigned long)protocol.session(),unsigned(protocol.task()),unsigned(seq),l,(unsigned long)model_crc(reinterpret_cast<uint8_t *>(attention+l*36),144));std::cout<<"LOG "<<line<<"\n";}
        }
    }
    if(protocol.attention_fragment(now,reply))emit(reply);
    if(protocol.running()&&step_enabled) {
        const unsigned width=protocol.width(),n=std::min(4u,width-completed%width);
        const unsigned row0=protocol.y()+completed/width,col0=protocol.x()+completed%width;
        uint32_t words[4];for(unsigned i=0;i<n;++i)words[i]=word(protocol.scene(),col0+i,row0);
        assert(results.append(protocol.session(),protocol.task(),row0,col0,n,words));completed+=n;compute+=n*5000u;
        whole_crc=model_crc_update(whole_crc,reinterpret_cast<const uint8_t *>(words),n*4);
        assert(protocol.progress(completed));assert(protocol.record_compute(compute,completed));
        if(completed%width==0) {
            const auto *slot=results.find(protocol.session(),protocol.task());
            for(unsigned x=protocol.x();x<protocol.x()+width;x+=ROW_MAX) {
                const unsigned count=std::min(ROW_MAX,protocol.x()+width-x);
                if(protocol.row_segment(row0,x,count,slot->words+row0*slot->scene_width+x,now,reply))emit(reply);
            }
        }
        if(completed==protocol.total()) {
            assert(protocol.finish(completed));log_end("TASK_DONE");
            std::cout<<"LOG S2C S3 scope=task session=";
            char suffix[140];std::snprintf(suffix,sizeof(suffix),"%08lx task=%u wait_calls=10 wait_rx=1 max_gap_us=100 max_service_us=5",
                (unsigned long)protocol.session(),unsigned(protocol.task()));std::cout<<suffix<<"\n";
        }
    }
    for(unsigned i=0;i<8&&protocol.replay(now,reply);++i)emit(reply);
}
std::vector<uint8_t> unhex(const std::string &s) {
    if(s.size()%2||s.size()>2824)throw std::runtime_error("invalid frame hex size");
    std::vector<uint8_t> bytes;
    for(size_t i=0;i<s.size();i+=2){unsigned value=0;std::istringstream in(s.substr(i,2));in>>std::hex>>value;if(!in||value>255)throw std::runtime_error("invalid hex");bytes.push_back(uint8_t(value));}
    return bytes;
}
}
int main() {
    std::cout<<"FIXTURE actual private Protocol/Models/ModelSd/ResultStore; RAM FatFs, synthetic numerics, NOT BOARD\n"<<std::flush;
    for(std::string line;std::getline(std::cin,line);) {
        try {
            std::istringstream in(line);std::string op;in>>op;
            if(op=="QUIT")return 0;
            if(op=="RX") {
                unsigned ip,port;std::string hex;in>>now>>ip>>port>>hex;const auto bytes=unhex(hex);
                if(!parked&&protocol.receive(bytes.data(),bytes.size(),Peer{ip,uint16_t(port)},now,reply))emit(reply);
            } else if(op=="POLL") {in>>now;poll();}
            else if(op=="STEP") {unsigned enabled;in>>enabled;step_enabled=bool(enabled);}
            else if(op=="SDFAIL") {unsigned fail;in>>fail;disk.fail=bool(fail);}
            else if(op=="LOADFAIL") {in>>engine.failure;}
            else if(op=="CONTRACTS") {
                for(unsigned i=0;i<3;++i){const auto &s=*scene_contract(i);
                    std::cout<<"CONTRACT "<<s.name<<" "<<s.width<<" "<<s.height<<" "<<unsigned(s.classes)<<" "
                        <<s.bands<<" "<<s.pad<<" "<<s.cube_bytes<<" "<<s.cube_crc<<"\n";}
            }
            else if(op=="RESTART") {
                uint32_t boot;in>>boot;
                // Test-only restart of CPU objects; RAM files persist. This is
                // NOT a PL reset or an SD power-cycle. No DMA exists here.
                protocol.~Protocol();results.~ResultStore();models.~Models();
                new (&models) Models();new (&results) ResultStore();new (&protocol) Protocol(boot,true,&results,&models);
                completed=0;compute=0;whole_crc=0xffffffffu;parked=false;engine.calls=0;engine.failure=0;
                model_test_fs::always_fail.clear();disk.fail=false;
                const bool ok=disk.storage.scan(models);
                std::cout<<"SCAN "<<unsigned(ok)<<" "<<models.count()<<" "<<disk.storage.receipt().rejected<<"\n";
            } else if(op=="CORRUPT") {
                std::string path;in>>path;auto found=model_test_fs::files.find(path);
                if(found==model_test_fs::files.end()||found->second.empty())throw std::runtime_error("missing RAM fixture file");
                found->second[0]^=1;
            }
            else if(op=="STATE") {
                const auto *active=models.active();std::cout<<"STATE "<<protocol.task()<<" "<<protocol.session()<<" "<<models.count()<<" "
                    <<disk.calls<<" "<<engine.calls<<" "<<jobs<<" "<<probes<<" "<<completed<<" "<<unsigned(parked)<<" "
                    <<(active?int(active->key.scene):-1)<<" "<<(active?active->key.crc:0)<<" "<<model_test_fs::files.size()<<"\n";
            } else throw std::runtime_error("unknown fixture command");
            std::cout<<"END\n"<<std::flush;
        } catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 2;}
    }
}
