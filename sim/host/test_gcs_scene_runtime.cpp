// New full-scene scheduler only, fake producer: no board/numerical inference.
#include "roi_runtime.h"
#include "roi_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static bool fail;
static unsigned calls=0,loads=0;
static const char *mode;
static unsigned probes=0,logit_calls=0;
static const int16_t *probe_input;
size_t tt_m3a_output_bytes(uint32_t n,uint32_t lo,uint32_t hi,uint32_t kind,bool dump) {
    assert(n==1&&lo==0&&hi==11&&kind==TT_ENGINE_OUT_LOGITS&&!dump);
    return std::strcmp(mode,"probe_size")==0?0:128;
}
int tt_m3a_run(const TTM3aJob &j,uint32_t polls) {
    ++logit_calls;
    assert(j.input==probe_input&&j.input[0]==1234&&j.input_capacity==TT_ENGINE_IN_STRIDE);
    assert(j.output_capacity==TT_ENGINE_ATTN_STRIDE&&j.n_patch==1&&j.layer_lo==0&&j.layer_hi==11);
    assert(j.output_kind==TT_ENGINE_OUT_LOGITS&&!j.dump&&polls==100000000);
    if(std::strcmp(mode,"probe_dma")==0)return TT_M3A_TIMEOUT;
    int32_t q[9]={-300,-200,-100,0,65536,0,-100,-200,-300};
    std::memcpy(j.output,q,sizeof(q));return 0;
}
int tt_m3a_sd_load(TTM3aSdSession &s,const TTM3aSdProfile &,const TTM3aSdStorage &){s.loaded=true;return 0;}
int tt_m3a_init(unsigned){return 0;}
int tt_m3a_load_weights(const void *,size_t,uint32_t){++loads;return 0;}
int tt_m3a_roi_run(TTM3aRoiSession &s,const TTM3aRoiRequest &r) {
    if(r.roi_width==1) {
        ++probes;assert(r.roi_height==1&&r.result_count==1&&r.x==399&&r.y==549);
        probe_input=r.input;r.input[0]=1234;s.completed=0;
        if(std::strcmp(mode,"probe_class")==0){s.halted=true;s.driver_status=-5;return TT_M3A_ROI_DRIVER;}
        if(std::strcmp(mode,"probe_short")==0)return 0;
        r.results[0]={399,549,0xabcd0004};s.completed=1;return 0;
    }
    assert(r.roi_width==4&&r.roi_height==1&&r.result_count==4&&r.batch_size==4);
    assert(r.x==(calls*4)%400&&r.y==(calls*4)/400);
    ++calls;s.completed=0;s.driver_status=0;
    if(fail&&calls==103){s.halted=true;s.driver_status=-5;return TT_M3A_ROI_DRIVER;}
    for(unsigned i=0;i<4;++i)r.results[i]={r.x+i,r.y,0xabcd0000u|((r.x+i+r.y)%9)};
    s.completed=4;return 0;
}
int main(int argc,char **argv){
    assert(argc==2);mode=argv[1];fail=std::strcmp(mode,"fail")==0;
    uint32_t untouched=0xdeadbeef;int32_t logits[9];for(auto &q:logits)q=0x12345678;
    assert(s2c::probe_once(549,399,untouched,logits)==TT_M3A_ROI_HALTED&&probes==0);
    assert(!s2c::load_scene());assert(!s2c::begin_scene());assert(loads==1);
    if(std::strcmp(mode,"probe_early")==0){
        assert(s2c::probe_once(549,399,untouched,logits)==TT_M3A_ROI_HALTED&&probes==0);
        std::puts("PASS incomplete task cannot probe");return 0;
    }
    assert(s2c::begin_scene()==TT_M3A_ROI_HALTED);
    unsigned steps=0;int rc=0;
    while(s2c::outcome().roi.completed<220000&&!rc){rc=s2c::step_scene();++steps;}
    uint32_t words[348],word=0xdeadbeef;
    if(fail){assert(rc&&steps==103&&s2c::outcome().roi.completed==408&&s2c::outcome().roi.halted);
        assert(s2c::copy_pixel(407,word));word=0xdeadbeef;assert(!s2c::copy_pixel(408,word)&&word==0xdeadbeef);
        assert(s2c::step_scene()==TT_M3A_ROI_HALTED&&calls==103);
        assert(s2c::copy_segment(0,348,52,words));assert(!s2c::copy_segment(1,0,348,words));
    }else{assert(!rc&&steps==55000&&loads==1&&s2c::outcome().roi.completed==220000);
        for(unsigned y=0;y<550;++y)for(unsigned col=0;col<400;col+=348){unsigned n=400-col<348?400-col:348;
            assert(s2c::copy_segment(y,col,n,words));for(unsigned i=0;i<n;++i)assert(words[i]==(0xabcd0000u|((col+i+y)%9)));}
        assert(!s2c::copy_segment(549,399,2,words));assert(!s2c::copy_pixel(220000,word));}
    if(std::strncmp(mode,"probe_",6)==0) {
        assert(s2c::probe_once(550,399,untouched,logits)==TT_M3A_ROI_ARGUMENT&&probes==0);
        const int prc=s2c::probe_once(549,399,untouched,logits);
        assert(s2c::outcome().roi.completed==220000&&loads==1&&probes==1);
        if(std::strcmp(mode,"probe_ok")==0){assert(prc==0&&untouched==0xabcd0004&&logits[4]==65536&&logit_calls==1);}
        else {assert(prc!=0&&untouched==0xdeadbeef);for(auto q:logits)assert(q==0x12345678);
            assert(s2c::outcome().roi.halted);
            assert(s2c::probe_once(549,399,untouched,logits)==TT_M3A_ROI_HALTED&&probes==1);
            assert(logit_calls==(std::strcmp(mode,"probe_dma")==0?1u:0u));}
        assert(s2c::copy_pixel(219999,word)&&word==(0xabcd0000u|((399+549)%9)));
    }
    std::puts("PASS scheduler/probe: committed prefixes and unchanged numeric path; no device inference");
}
