// Private scheduling/ownership tests. Numeric/SD stubs, NOT inference accuracy.
#include "roi_runtime.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>
using namespace s2c;
static Models *catalog;
static unsigned loads=0,inits=0,calls=0,ncls=0,fail_load=0;
static const uint8_t *dma_weights;
static std::vector<uint8_t> owned_weights;
static bool run_fault=false;
static bool bad_attention=false;
static void p32(uint8_t *b,uint32_t v){for(unsigned i=0;i<4;++i)b[i]=uint8_t(v>>(8*i));}
static uint32_t add(unsigned scene,const char *tag,unsigned seed) {
    uint32_t crc=0;
    for(unsigned kind=0;kind<2;++kind) {
        std::vector<uint8_t> b(model_bytes(scene,kind),0);
        if(kind){p32(b.data(),0x32455454);p32(b.data()+4,2);p32(b.data()+8,scene_contract(scene)->classes);p32(b.data()+12,16);b[191232]=uint8_t(seed);}
        else b[0]=uint8_t(seed);
        ModelKey k{};k.scene=uint8_t(scene);k.kind=uint8_t(kind);k.bytes=uint32_t(b.size());k.crc=model_crc(b.data(),b.size());std::strcpy(k.tag,tag);
        assert(!catalog->import(k,b.data()).code);crc=k.crc;
    }
    return crc;
}
struct Input: ModelInput {
    std::vector<unsigned> scenes;int fail_scene=-1;
    bool load_input(unsigned scene,void *p,size_t cap) override {
        assert(cap>=scene_contract(scene)->cube_bytes);scenes.push_back(scene);
        // A partial read is intentionally destructive to CPU input; runtime
        // must not reuse it as if the previous scene were still available.
        std::memset(p,0xa5,64);
        if(int(scene)==fail_scene){fail_scene=-1;return false;}return true;
    }
    int input_error() const override {return -123;}
};
int tt_m3a_sd_load(TTM3aSdSession &,const TTM3aSdProfile &,const TTM3aSdStorage &){assert(false);return -1;}
int tt_m3a_init(unsigned){++inits;return 0;}
int tt_m3a_load_weights(const void *p,size_t bytes,uint32_t) {
    ++loads;assert(bytes==MODEL_ENGINE_BYTES);
    for(unsigned i=0;i<catalog->count();++i)assert(p!=catalog->entry(i)->data);
    dma_weights=static_cast<const uint8_t *>(p);owned_weights.assign(dma_weights,dma_weights+bytes);ncls=dma_weights[8];
    return loads==fail_load?-55:0;
}
size_t tt_m3a_output_bytes(uint32_t,unsigned,unsigned,unsigned kind,bool){return kind==TT_ENGINE_OUT_ATTENTION?TT_ENGINE_ATTN_STRIDE:kind==TT_ENGINE_OUT_LOGITS?128:64;}
int tt_m3a_run(const TTM3aJob &j,uint32_t) {
    if(run_fault)return -66;
    int32_t values[32]={};values[ncls-1]=12345;
    if(j.output_kind==TT_ENGINE_OUT_ATTENTION){
        assert(j.output_capacity>=TT_ENGINE_ATTN_STRIDE);auto *p=static_cast<uint8_t *>(j.output);std::memset(p,0,TT_ENGINE_ATTN_STRIDE);
        const uint32_t h[16]={TT_ENGINE_ATTN_MAGIC,4,0xabcd0000u|(ncls-1),ncls,12,6,24,432,0,0,0,0,0,0,0,0};std::memcpy(p,h,64);
        std::memcpy(p+64,values,sizeof(values));for(unsigned i=0;i<72;++i)p32(p+TT_ENGINE_ATTN_OFFSET+i*24,1u<<24);
        if(bad_attention)p[0]^=1;
    }else std::memcpy(j.output,values,sizeof(values));
    return 0;
}
int tt_m3a_roi_run(TTM3aRoiSession &s,const TTM3aRoiRequest &r) {
    ++calls;const unsigned scene=ncls==9?0:ncls==22?1:2;const auto &spec=*scene_contract(scene);
    assert(!s.halted&&r.width==spec.width&&r.height==spec.height&&r.row_pixels==spec.width+6u&&r.cube_bytes==spec.cube_bytes);
    assert(r.x+r.roi_width<=r.width&&r.y<r.height&&r.roi_height==1&&r.roi_width<=4);
    assert(r.results&&r.result_count==r.roi_width);
    // A wait-service callback cannot acquire any model/SD/DMA owner.
    RuntimeModelActivation activation;const auto *e=catalog->active();const auto *a=e?catalog->companion(*e):nullptr;
    if(a){const unsigned before=loads;assert(activation.load(*a,*e)==TT_M3A_ROI_HALTED&&loads==before);}
    s.completed=r.roi_width;s.driver_status=0;
    for(unsigned i=0;i<r.roi_width;++i)r.results[i]={r.x+i,r.y,0xabcd0000u|(ncls-1)};
    return 0;
}
int main(int argc,char **argv) {
    assert(argc==2);const char *mode=argv[1];std::unique_ptr<Models> m(new Models);catalog=m.get();
    const uint32_t longkou=add(0,"demo",1),honghu=add(1,"demo",2),hanchuan=add(2,"demo",3);
    Input input;assert(configure_models(input));assert(!configure_models(input));RuntimeModelActivation activation;
    if(!std::strcmp(mode,"load_fault"))fail_load=1;
    auto r=m->activate(1,honghu,0,true,activation);
    if(fail_load) {
        assert(r.code==6&&int32_t(r.value)==-55&&m->faulted()&&outcome().roi.halted);
        const unsigned before=loads;assert(m->activate(0,longkou,0,true,activation).code==6&&loads==before);
        assert(std::memcmp(dma_weights,owned_weights.data(),owned_weights.size())==0);
        assert(begin_task(0,0,1,1)==TT_M3A_ROI_HALTED);std::puts("model runtime permanent LOAD_W fault PASS");return 0;
    }
    assert(!r.code&&loads==1&&inits==1&&input.scenes==std::vector<unsigned>{1});
    assert(!begin_task(470,939,5,1));assert(!step_task()&&outcome().roi.completed==4);
    uint32_t previous=0;assert(copy_pixel(0,previous)&&previous==0xabcd0015);
    uint32_t word=0xdeadbeef;int32_t values[24];for(auto &v:values)v=-7;
    const unsigned before=loads;
    if(!std::strcmp(mode,"probe_input_fail"))input.fail_scene=2;
    if(!std::strcmp(mode,"probe_load_fault"))fail_load=loads+1;
    if(!std::strcmp(mode,"probe_run_fault"))run_fault=true;
    const bool attention_mode=std::strstr(mode,"attention")!=nullptr;uint32_t attention[432];for(auto &v:attention)v=0xdeadbeef;
    bad_attention=!std::strcmp(mode,"attention_header_fault");
    if(!std::strcmp(mode,"attention_restore_fault"))fail_load=loads+2;
    const int rc=probe_model(*m,2,hanchuan,1216,302,word,values,24,attention_mode?attention:nullptr,attention_mode?432:0);
    if(fail_load||run_fault||bad_attention) {
        assert(rc&&m->faulted()&&outcome().roi.halted&&word==0xdeadbeef&&values[0]==-7);
        for(auto v:attention)assert(v==0xdeadbeef);
        const unsigned after=loads;assert(m->activate(1,honghu,0,true,activation).code==6&&loads==after);
        assert(std::memcmp(dma_weights,owned_weights.data(),owned_weights.size())==0);
        uint32_t old=0;assert(copy_pixel(0,old)&&old==previous&&outcome().roi.completed==4);
        std::puts("model runtime probe fault retains buffers/prefix, no restore DMA PASS");return 0;
    }
    if(!std::strcmp(mode,"probe_input_fail"))assert(rc==TT_M3A_SD_IO&&word==0xdeadbeef&&values[0]==-7);
    else assert(!rc&&word==0xabcd000f&&values[15]==12345&&loads==before+2);
    if(attention_mode)for(unsigned i=0;i<432;++i)assert(attention[i]==(i%6?0:1u<<24));
    assert(!m->faulted()&&m->active()->key.crc==honghu&&outcome().roi.completed==4);
    assert(!step_task()&&outcome().roi.completed==5);uint32_t old=0;assert(copy_pixel(0,old)&&old==previous);
    // Failed scene input preflight does not fabricate activation or poison a
    // healthy driver; retrying the old model revalidates its overwritten cube.
    input.fail_scene=0;r=m->activate(0,longkou,0,true,activation);
    assert(r.code==6&&!m->faulted()&&m->active()->key.crc==honghu&&!outcome().sd.loaded);
    assert(!m->activate(1,honghu,0,true,activation).code&&outcome().sd.loaded);
    assert(!m->activate(0,longkou,0,true,activation).code);
    assert(!begin_task(399,549,1,1)&&!step_task());assert(copy_pixel(0,word)&&word==0xabcd0008);
    assert(!m->activate(2,hanchuan,0,true,activation).code);
    assert(!begin_task(302,1216,1,1)&&!step_task());assert(copy_pixel(0,word)&&word==0xabcd000f);
    assert(inits==1);std::puts("model runtime three scenes/input retry/cross-model probe+restore/one init PASS");
}
