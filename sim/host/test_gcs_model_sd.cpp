#include "roi_model_sd.h"
#include "ff.h"
#include "ram_fs.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>
using namespace s2c;
using namespace model_test_fs;
namespace {
void put32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));}
std::vector<uint8_t> package(unsigned scene,unsigned kind) {
    std::vector<uint8_t> b(model_bytes(scene,kind),0);
    if(kind){put32(b.data(),0x32455454);put32(b.data()+4,2);put32(b.data()+8,scene_contract(scene)->classes);put32(b.data()+12,16);b[191232]=3;}
    else b[0]=3;
    return b;
}
ModelKey key(unsigned scene,unsigned kind,const std::vector<uint8_t> &b) {
    ModelKey k{};k.scene=uint8_t(scene);k.kind=uint8_t(kind);k.bytes=uint32_t(b.size());k.crc=model_crc(b.data(),b.size());std::strcpy(k.tag,"demo");return k;
}
}
static void persistence_readback_and_scan() {
    reset();std::unique_ptr<ModelSd> disk(new ModelSd);
    for(unsigned scene=0;scene<3;++scene)for(unsigned kind=0;kind<2;++kind) {
        auto b=package(scene,kind);auto k=key(scene,kind,b);assert(disk->save(k,b.data()));
        assert(disk->receipt().complete&&disk->receipt().crc==k.crc&&disk->receipt().bytes==b.size());
    }
    const unsigned previous=writes;auto a=package(0,0);auto k=key(0,0,a);assert(disk->save(k,a.data())&&writes==previous);
    std::unique_ptr<Models> models(new Models);assert(disk->scan(*models));assert(models->count()==6&&disk->receipt().registered==6&&!models->active());
    for(unsigned i=0;i<6;++i)assert(models->entry(i)->persisted);
    for(const auto &f:files)assert(f.first.find(".tmp")==std::string::npos);
    // Existing final files are immutable, including on an attempted tag rebind.
    files.at("1:/scenes/longkou/weights/demo/weights_all.bin")[0]^=1;
    assert(!disk->save(k,a.data())&&!disk->receipt().complete&&writes==previous);
    models.reset(new Models);assert(disk->scan(*models));assert(models->count()==5&&disk->receipt().rejected==1);
    assert(!models->find(0,1,key(0,1,package(0,1)).crc)); // engine pair rejected, not silently used
    assert(mounts==unmounts);
    std::puts("RAM FatFs: exact split files/readback/idempotence/scan/pair PASS");
}
static void fault_injection() {
    for(const char *op:{"mount","mkdir","open","write","short_write","sync","close","rename","read","short_read","unmount"}) {
        reset();std::unique_ptr<ModelSd> disk(new ModelSd);auto a=package(0,0);auto k=key(0,0,a);fail=op;
        assert(!disk->save(k,a.data())&&!disk->receipt().complete);assert(mounts==unmounts);
        // A failed receipt never causes a claim of successful persistence. A
        // later cold scan may prove complete files, but never trusts .tmp.
        for(auto &f:files)if(f.first.find(".tmp")!=std::string::npos)assert(f.first.find("weights/demo/")!=std::string::npos);
        fail.clear();assert(disk->save(k,a.data()));std::unique_ptr<Models> models(new Models);
        assert(disk->scan(*models)&&models->count()==1); // incomplete engine remains unavailable
    }
    reset();std::unique_ptr<ModelSd> disk(new ModelSd);auto a=package(0,0);auto k=key(0,0,a);assert(disk->save(k,a.data()));
    std::unique_ptr<Models> models(new Models);always_fail="read";
    assert(!disk->scan(*models)); // physical read failure must not be swallowed as a harmless missing tag
    assert(disk->receipt().status==FR_DISK_ERR&&models->count()==0&&mounts==unmounts);
    std::puts("RAM FatFs: write/sync/close/rename/read/mount failure gates PASS");
}
struct ServiceContext {ModelSd *disk;unsigned calls=0;};
static void service(void *context) {
    auto &s=*static_cast<ServiceContext *>(context);++s.calls;
    // The foreground owner cannot be replaced while servicing the callback;
    // this does not reset SD status or perform recursive file/DMA work.
    assert(!s.disk->set_service(nullptr,nullptr));
}
static void serviced_io(const char *cube_path) {
    reset();std::unique_ptr<ModelSd> disk(new ModelSd);ServiceContext ctx{disk.get()};
    assert(disk->set_service(service,&ctx));auto a=package(0,0);auto k=key(0,0,a);
    assert(disk->save(k,a.data())&&ctx.calls>100);
    const unsigned before=ctx.calls;std::unique_ptr<Models> models(new Models);assert(disk->scan(*models));
    assert(ctx.calls>before&&models->count()==1);
    if(cube_path) {
        const auto &spec=*scene_contract(0);auto &raw=files["1:/scenes/longkou/cube_f32.bin"];
        raw.resize(spec.cube_bytes);std::ifstream in(cube_path,std::ios::binary);
        in.read(reinterpret_cast<char *>(raw.data()),raw.size());assert(size_t(in.gcount())==raw.size()&&in.peek()==EOF);
        std::vector<uint8_t> destination(raw.size()+128,0x5a);const unsigned calls=ctx.calls;
        assert(disk->load_input(0,destination.data()+64,raw.size()));
        assert(disk->receipt().crc==spec.cube_crc&&disk->receipt().bytes==raw.size());
        assert(ctx.calls-calls==(raw.size()+(1u<<20)-1)/(1u<<20));
        assert(std::memcmp(destination.data()+64,raw.data(),raw.size())==0);
        for(unsigned i=0;i<64;++i)assert(destination[i]==0x5a&&destination[destination.size()-1-i]==0x5a);
        raw[0]^=1;
        assert(!disk->load_input(0,destination.data()+64,raw.size()));
        assert(!disk->receipt().complete&&disk->receipt().bytes==0);
        std::puts("RAM FatFs: actual LOCAL LongKou cube streaming CRC/servicing/guards/corruption gate PASS; NOT SD readback");
    }
    assert(disk->set_service(nullptr,nullptr));
    std::puts("RAM FatFs: foreground service and reentry owner gate PASS");
}
int main(int argc,char **argv){assert(argc<=2);persistence_readback_and_scan();fault_injection();serviced_io(argc==2?argv[1]:nullptr);}
