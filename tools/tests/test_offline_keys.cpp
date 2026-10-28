#include "roi_protocol.h"
#include "roi_board_log.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <vector>
using namespace s2c;
static Models models;static ResultStore results;static BoardLog logs;
static void p16(uint8_t *p,unsigned n){p[0]=uint8_t(n);p[1]=uint8_t(n>>8);}
static void p32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=uint8_t(n>>(8*i));}
static std::vector<uint8_t> read(const std::string &path){std::ifstream f(path,std::ios::binary);assert(f);return {std::istreambuf_iterator<char>(f),{}};}
static void import(unsigned scene,const char *tag) {
    const auto *spec=scene_contract(scene);const std::string base="data/scenes/"+std::string(spec->name)+"/weights/"+tag+"/";
    const char *files[]={"weights_all.bin","cls_token.bin","pos_embed.bin","classifier_w.bin","classifier_b.bin"};
    std::vector<uint8_t> companion;
    for(auto name:files){auto bytes=read(base+name);companion.insert(companion.end(),bytes.begin(),bytes.end());}
    auto engine=read(base+"weights_engine.bin");
    for(unsigned kind=0;kind<2;++kind){const auto &bytes=kind?engine:companion;
        ModelKey key{};key.scene=uint8_t(scene);key.kind=uint8_t(kind);key.bytes=unsigned(bytes.size());key.crc=model_crc(bytes.data(),bytes.size());std::strcpy(key.tag,tag);
        assert(!models.import(key,bytes.data()).code);
    }
}
static void complete(Protocol &p,uint64_t now) {
    assert(p.take_job());const auto *spec=scene_contract(p.scene());
    std::vector<uint32_t> words(p.width(),0x90000000u|(p.scene()+1));
    for(unsigned y=p.y();y<p.y()+p.height();++y) {
        assert(results.append(p.session(),p.task(),y,p.x(),p.width(),words.data()));
        assert(p.progress((y-p.y()+1)*p.width()));
        assert(p.running());
    }
    assert(spec&&p.finish(p.total(),now));assert(!p.running());
    assert(p.dispatch_view().phase==DispatchPhase::done);
}
int main() {
    import(0,"v2");import(1,"v1");import(2,"v1");
    assert(default_key_model(models,0)->key.crc==WCRC);
    const char *release="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    Protocol p(17,true,&results,&models,release,&logs);p.mark_startup_ready();Packet reply{};
    uint64_t now=1000000;
    for(unsigned scene=0;scene<3;++scene)for(unsigned key:{5u,6u})for(unsigned gesture:{1u,2u}) {
        LocalKeyPlan plan;assert(make_local_key_plan(key,gesture,scene,unsigned(now),plan));
        const auto *spec=scene_contract(scene);assert(plan.x+plan.width<=spec->width&&plan.y+plan.height<=spec->height);
        if(key==6){assert(plan.width*plan.height<=4096);assert(plan.width*plan.height*uint64_t(scene==0?463*463:scene==1?43*43:109*109)<=6000000000ULL);}
        if(plan.points){unsigned count=0;assert(plan.points>=3&&plan.points<=5);
            for(unsigned y=plan.y;y<plan.y+plan.height;++y)for(unsigned x=plan.x;x<plan.x+plan.width;++x)count+=plan.contains(y,x);
            assert(count&&count<plan.width*plan.height);
        }
        assert(p.queue_key(key,gesture,now));KeyEvent event;assert(p.take_local_key(now,event));assert(!p.peer_seen());
        assert(!p.queue_key(key,gesture,now)); // planning is an exclusive owner
        assert(p.begin_local_task(plan,default_key_model(models,scene)->key.crc,now));
        p.complete_local_key(true,13);assert(p.local_owner());assert(!p.take_local_key(now,event));
        assert(p.dispatch_view().source==key);
        // A late host START cannot mutate or duplicate the local task.
        uint8_t start[32]={0x48,0x45,1,1};p16(start+4,p.task()+1);const auto task=p.task();
        assert(p.receive(start,32,{1,5010},now,reply));assert(reply.bytes[13]==9&&p.task()==task);
        complete(p,now+1000000);now+=2000000;
    }
    // Long hold stops only at a committed row, then selects without loading SD.
    assert(p.queue_key(5,2,now));KeyEvent event;assert(p.take_local_key(now,event));LocalKeyPlan scan;
    assert(make_local_key_plan(5,2,0,1,scan));assert(p.begin_local_task(scan,WCRC,now));p.complete_local_key(true,13);assert(p.take_job());
    // Independent local probes reuse the actual running task without changing
    // its scan counters. The preceding completed probe cannot swallow a click.
    for(unsigned i=0;i<2;++i){assert(p.queue_key(5,1,now));assert(p.take_local_key(now,event));
        assert(p.begin_local_probe(2,3));p.complete_local_key(true,13);
        unsigned row,col;uint16_t seq;assert(p.take_probe(row,col,seq));assert(row==2&&col==3);
        int32_t logits[24]={};p.probe_reply(0x90000001,logits,now,reply);
        assert(p.dispatch_view().action==DispatchAction::scan&&p.dispatch_view().phase==DispatchPhase::preparing);
        assert(results.find(p.session(),p.task())->completed==0);
    }
    assert(p.queue_key(6,3,now+1));assert(p.take_local_key(now+1,event));assert(p.request_local_stop());
    uint32_t words[400]={};assert(results.append(p.session(),p.task(),0,0,1,words));assert(p.progress(1));
    assert(!p.apply_control(now+2,reply));assert(results.append(p.session(),p.task(),0,1,399,words));assert(p.progress(400));
    assert(p.apply_control(now+3,reply)&&p.stopped());p.complete_local_key(true,10,1);
    assert(p.key_scene()==1&&p.dispatch_view().phase==DispatchPhase::selected);
    uint8_t info[12]={0x48,0x45,7,1};assert(p.receive(info,12,{1,5010},now+4,reply));assert(reply.bytes[43]==1);
    const auto session=p.session();uint8_t ping[16]={0x48,0x45,5,1};p32(ping+12,session);
    assert(p.receive(ping,16,{2,5010},now+5,reply));assert(reply.bytes[13]==9&&p.local_owner());
    const auto retained=p.task();
    p16(ping+4,65535);assert(p.receive(ping,16,{2,5010},now+6,reply));assert(!p.local_owner()&&p.task()==retained&&p.session()==session);
    assert(p.receive(info,12,{2,5010},now+7,reply));assert(reply.bytes[43]==0);
    assert(results.find(session,13)); // retained final task, not cleared on PC handoff
    assert(p.power_packet(now+2000000,reply));
    assert((reply.bytes[4]|unsigned(reply.bytes[5])<<8)==retained);
    assert((reply.bytes[32]|unsigned(reply.bytes[33])<<8)==retained);
    assert(reply.bytes[36]==144&&reply.bytes[37]==1); // actual stopped prefix: 400
    const uint64_t later=now+4000000;
    assert(p.queue_key(5,1,later));assert(p.take_local_key(later,event));
    LocalKeyPlan point;assert(make_local_key_plan(5,1,0,1,point));assert(p.begin_local_task(point,WCRC,later));p.complete_local_key(true,13);
    complete(p,later+1000000);
    assert(p.receive(ping,16,{2,5010},later+2000000,reply));
    assert(!p.local_owner()&&p.dispatch_view().phase==DispatchPhase::done);
    std::puts("OFFLINE_KEYS_PASS: all scenes/actions, real V2 package selection, bounds/area, no peer, late-command isolation, row-safe stop, explicit reconnect");
}
