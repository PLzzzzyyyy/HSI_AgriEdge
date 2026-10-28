#include "roi_models.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <fstream>
#include <cstdlib>
#include <vector>
using namespace s2c;
static void put32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));}
static std::vector<uint8_t> package(unsigned scene,unsigned kind,unsigned seed=1) {
    std::vector<uint8_t> b(model_bytes(scene,kind),0);
    if(kind) { put32(b.data(),0x32455454);put32(b.data()+4,2);
        put32(b.data()+8,scene_contract(scene)->classes);put32(b.data()+12,16);b[191232]=uint8_t(seed);
    } else b[0]=uint8_t(seed);
    return b;
}
static ModelKey key(unsigned scene,unsigned kind,const char *tag,const std::vector<uint8_t> &b) {
    ModelKey k{};k.scene=uint8_t(scene);k.kind=uint8_t(kind);k.bytes=uint32_t(b.size());
    k.crc=model_crc(b.data(),b.size());assert(std::strlen(tag)<=15);std::strcpy(k.tag,tag);return k;
}
struct Disk: ModelPersistence {
    unsigned calls=0;bool fail=false;
    bool save(const ModelKey &k,const uint8_t *p) override {
        ++calls;assert(k.crc==model_crc(p,k.bytes));return !fail;
    }
};
struct Engine: ModelActivation {
    unsigned calls=0;int error=0;
    int load(const ModelEntry &a,const ModelEntry &b) override {
        ++calls;assert(a.key.kind==0&&b.key.kind==1);assert(model_pair(a.key.scene,a.data,b.data));return error;
    }
};
static void upload(Models &m,const ModelKey &k,const std::vector<uint8_t> &b) {
    auto r=m.begin(k);assert(r.code==0&&r.value==0);
    for(size_t off=0;off<b.size();) {
        const size_t n=(b.size()-off)>1384?1384:b.size()-off;
        r=m.chunk(k.scene,k.kind,k.bytes,k.crc,uint32_t(off),b.data()+off,n);
        off+=n;assert(!r.code&&r.value==off);
    }
}
static void contracts_and_validation() {
    assert(!scene_contract(3)&&!model_bytes(3,0)&&!model_bytes(0,2));
    const unsigned w[]={400,475,303},h[]={550,940,1217},n[]={9,22,16};
    const uint32_t sizes[]={243794880,491428080,408139560};
    for(unsigned s=0;s<3;++s) {
        const auto &c=*scene_contract(s);assert(c.width==w[s]&&c.height==h[s]&&c.classes==n[s]);
        assert(c.cube_bytes==sizes[s]&&c.bands==270&&c.pad==3);
        auto a=package(s,0),b=package(s,1);
        assert(model_package(s,0,a.data(),a.size())&&model_package(s,1,b.data(),b.size()));
        assert(model_pair(s,a.data(),b.data()));
        b[16]=1;assert(!model_package(s,1,b.data(),b.size()));b[16]=0;
        b[32+n[s]]=1;assert(!model_package(s,1,b.data(),b.size()));b[32+n[s]]=0;
        b[63744+5292]=1;assert(!model_package(s,1,b.data(),b.size()));b[63744+5292]=0;
        b[191232]^=1;assert(!model_pair(s,a.data(),b.data()));b[191232]^=1;
        put32(a.data()+289344,0x7f800000);assert(!model_package(s,0,a.data(),a.size()));
        put32(a.data()+289344,0x3f000000);assert(!model_pair(s,a.data(),b.data()));
        put32(b.data()+64,8388608);assert(model_pair(s,a.data(),b.data()));
    }
    std::puts("contracts/finite/reserved/pair PASS");
}
static void upload_order_and_identity() {
    std::unique_ptr<Models> p(new Models);auto &m=*p;auto a=package(0,0);auto k=key(0,0,"demo",a);
    assert(!m.begin(k).code);assert(!m.chunk(0,0,k.bytes,k.crc,0,a.data(),100).code);
    auto r=m.begin(k);assert(!r.code&&r.value==100);
    r=m.chunk(0,0,k.bytes,k.crc,0,a.data(),100);assert(!r.code&&r.value==100);
    a[1]=3;r=m.chunk(0,0,k.bytes,k.crc,0,a.data(),100);assert(r.code==2&&r.value==100);a[1]=0;
    assert(m.chunk(0,0,k.bytes,k.crc,200,a.data()+200,100).code==2);
    assert(m.chunk(0,1,k.bytes,k.crc,100,a.data()+100,100).code==8);
    ModelKey bad=k;std::strcpy(bad.tag,"../bad");assert(m.begin(bad).code==8);
    bad=k;std::memset(bad.tag,'a',16);assert(m.begin(bad).code==8);
    bad=k;bad.tag[8]='x';assert(m.begin(bad).code==8); // nonzero after NUL
    bad=k;bad.bytes--;assert(m.begin(bad).code==8);assert(m.begin(k).value==100);
    assert(m.commit(k.crc,false,nullptr).code==2);
    for(size_t off=100;off<a.size();) {size_t n=a.size()-off;if(n>1384)n=1384;
        assert(!m.chunk(0,0,k.bytes,k.crc,uint32_t(off),a.data()+off,n).code);off+=n;}
    r=m.commit(k.crc,false,nullptr);assert(!r.code&&!r.value&&m.count()==1);
    assert(!m.entry(0)->persisted&&!m.active());
    Disk disk;assert(m.flush_one(disk)&&disk.calls==1&&m.entry(0)->persisted);
    r=m.commit(k.crc,true,&disk);assert(!r.code&&r.value==1&&disk.calls==1);
    assert(m.begin(k).value==k.bytes); // registered identity resumes, never erases it
    std::puts("bounded upload/repeat/identity/deferred persist PASS");
}
static void commit_activation_and_failure() {
    std::unique_ptr<Models> p(new Models);auto &m=*p;Disk disk;Engine engine;
    auto a=package(1,0),b=package(1,1);auto ka=key(1,0,"demo",a),kb=key(1,1,"demo",b);
    upload(m,kb,b);assert(m.commit(kb.crc,true,&disk).code==5&&m.count()==0); // companion mandatory
    upload(m,ka,a);disk.fail=true;auto r=m.commit(ka.crc,true,&disk);
    assert(r.code==4&&!r.value&&m.count()==1&&!m.entry(0)->persisted);
    assert(!m.flush_one(disk)); // failure is not busy-retried forever
    disk.fail=false;r=m.commit(ka.crc,true,&disk);assert(!r.code&&r.value==1);
    upload(m,kb,b);assert(!m.commit(kb.crc,true,&disk).code&&m.count()==2);
    assert(m.activate(1,kb.crc,1,true,engine).code==8&&engine.calls==0); // one bank
    assert(m.activate(1,kb.crc,0,false,engine).code==8&&engine.calls==0);
    assert(!m.activate(1,kb.crc,0,true,engine).code&&engine.calls==1&&m.active()->key.crc==kb.crc);
    assert(!m.activate(1,kb.crc,0,true,engine).code&&engine.calls==1);
    // Bad upload never changes the active entry. Same tag cannot be rebound.
    a[0]=3;auto conflict=key(1,0,"demo",a);assert(m.begin(conflict).code==3);
    auto wrong=key(1,0,"next",a);wrong.crc^=1;upload(m,wrong,a);assert(m.commit(wrong.crc,true,&disk).code==1);
    assert(m.active()->key.crc==kb.crc&&engine.calls==1);
    // Valid second pair followed by LOAD_W failure invalidates hardware identity permanently.
    a=package(1,0,2);b=package(1,1,2);ka=key(1,0,"next",a);kb=key(1,1,"next",b);
    upload(m,ka,a);assert(!m.commit(ka.crc,true,&disk).code);upload(m,kb,b);assert(!m.commit(kb.crc,true,&disk).code);
    engine.error=-77;r=m.activate(1,kb.crc,0,true,engine);assert(r.code==6&&int32_t(r.value)==-77);
    assert(m.faulted()&&!m.active());assert(m.activate(1,kb.crc,0,true,engine).code==6&&engine.calls==2);
    assert(m.begin(ka).code==6&&m.commit(ka.crc,true,&disk).code==6);
    std::puts("commit/SD failure/single-bank/fault latch PASS");
}
static void registry_bound_and_import() {
    std::unique_ptr<Models> p(new Models);auto &m=*p;
    for(unsigned i=0;i<MODEL_MAX_ENTRIES;++i) {
        auto a=package(0,0,i+1);char tag[16];std::snprintf(tag,sizeof(tag),"m%u",i);auto k=key(0,0,tag,a);
        assert(!m.import(k,a.data()).code);assert(m.entry(i)->persisted);
    }
    auto a=package(2,0);auto k=key(2,0,"extra",a);assert(m.import(k,a.data()).code==8);
    assert(m.count()==MODEL_MAX_ENTRIES&&!m.active());
    assert(!m.entry(MODEL_MAX_ENTRIES));
    std::puts("registry bound/verified import/not activation PASS");
}
int main(int argc,char **argv) {
    if(argc==4) {
        const unsigned scene=unsigned(std::strtoul(argv[1],nullptr,10));assert(scene_contract(scene));
        std::vector<uint8_t> a(model_bytes(scene,0)),b(model_bytes(scene,1));
        for(unsigned kind=0;kind<2;++kind) {
            auto &data=kind?b:a;std::ifstream in(argv[2+kind],std::ios::binary);
            in.read(reinterpret_cast<char *>(data.data()),data.size());assert(size_t(in.gcount())==data.size()&&in.peek()==EOF);
        }
        assert(model_pair(scene,a.data(),b.data()));std::puts("real local exported pair validation PASS; NOT inference or SD/board proof");return 0;
    }
    assert(argc==1);
    contracts_and_validation();upload_order_and_identity();commit_activation_and_failure();registry_bound_and_import();
}
