// Scheduler-only tests with numeric driver stubs; never physical inference.
#include "roi_runtime.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
static const char *mode;
static unsigned loads=0,inits=0,calls=0,logits_calls=0;
static bool inject=false,reenter=false;
static std::vector<TTM3aRoiResult> visited;
int tt_m3a_sd_load(TTM3aSdSession &s,const TTM3aSdProfile &,const TTM3aSdStorage &){s.loaded=true;return 0;}
int tt_m3a_init(unsigned){++inits;return 0;}
int tt_m3a_load_weights(const void *,size_t,uint32_t){++loads;return std::strcmp(mode,"load_fault")==0?-5:0;}
size_t tt_m3a_output_bytes(uint32_t,unsigned,unsigned,unsigned kind,bool){return kind==TT_ENGINE_OUT_LOGITS?128:64;}
int tt_m3a_run(const TTM3aJob &j,uint32_t){
    ++logits_calls;if(std::strcmp(mode,"probe_fault")==0)return -5;
    int32_t v[32]={};v[2]=65536;std::memcpy(j.output,v,128);return 0;
}
int tt_m3a_roi_run(TTM3aRoiSession &s,const TTM3aRoiRequest &r){
    assert(!s.halted);assert(r.roi_height==1&&r.roi_width>=1&&r.roi_width<=4);
    assert(r.x+r.roi_width<=400&&r.y<550&&r.result_count==r.roi_width);
    ++calls;s.completed=0;s.driver_status=0;
    if(reenter){
        const auto before=s2c::outcome().roi.completed;
        uint32_t w=0xdeadbeef;int32_t l[9]={};
        assert(s2c::begin_task(0,0,1,1)==TT_M3A_ROI_HALTED);
        assert(s2c::step_task()==TT_M3A_ROI_HALTED);
        assert(!s2c::stop_task());
        assert(s2c::probe_once(0,0,w,l)==TT_M3A_ROI_HALTED&&w==0xdeadbeef);
        assert(s2c::outcome().roi.completed==before);
    }
    unsigned n=r.roi_width;
    if(inject)n=1; // committed CPU prefix before DMA failure
    for(unsigned i=0;i<n;++i){r.results[i]={r.x+i,r.y,0xabcd0000u|((r.x+i+r.y)%9)};visited.push_back(r.results[i]);}
    s.completed=n;
    if(inject){s.halted=true;s.driver_status=-5;return TT_M3A_ROI_DRIVER;}
    return 0;
}
int main(int argc,char **argv){
    assert(argc==2);mode=argv[1];assert(!s2c::load_scene());
    for(auto x:{0u,400u})assert(s2c::begin_task(x,0,0,1)==TT_M3A_ROI_ARGUMENT);
    assert(s2c::begin_task(399,549,2,1)==TT_M3A_ROI_ARGUMENT&&loads==0);
    int rc=s2c::begin_task(397,548,3,2);
    if(std::strcmp(mode,"load_fault")==0){assert(rc&&s2c::outcome().roi.halted);assert(s2c::begin_task(0,0,1,1)==TT_M3A_ROI_HALTED&&loads==1);return 0;}
    assert(!rc&&loads==1&&inits==1);
    assert(s2c::begin_task(0,0,1,1)==TT_M3A_ROI_HALTED);
    reenter=true;assert(!s2c::step_task());reenter=false;
    assert(s2c::outcome().roi.completed==3&&visited[0].x==397&&visited[2].x==399&&visited[0].y==548);
    uint32_t words[4],word=0xdeadbeef;int32_t logits[9]={};
    assert(s2c::copy_segment(548,397,3,words));assert(!s2c::copy_segment(549,397,1,words));
    const unsigned before=calls;
    if(std::strcmp(mode,"probe_fault")==0){
        assert(s2c::probe_once(0,0,word,logits)&&s2c::outcome().roi.halted&&word==0xdeadbeef);
        assert(s2c::step_task()==TT_M3A_ROI_HALTED&&calls==before+1);assert(!s2c::stop_task());return 0;
    }
    assert(!s2c::probe_once(0,0,word,logits)&&logits[2]==65536);
    assert(s2c::outcome().roi.completed==3&&s2c::copy_pixel(0,word)&&word==words[0]);
    if(std::strcmp(mode,"fault")==0){
        inject=true;assert(s2c::step_task()!=0&&s2c::outcome().roi.completed==4&&s2c::outcome().roi.halted);
        assert(s2c::copy_pixel(3,word));word=0xdeadbeef;assert(!s2c::copy_pixel(4,word)&&word==0xdeadbeef);
        assert(s2c::begin_task(0,0,1,1)==TT_M3A_ROI_HALTED&&!s2c::stop_task());return 0;
    }
    assert(s2c::stop_task()&&s2c::stop_task());assert(s2c::step_task()==TT_M3A_ROI_HALTED);
    // New healthy task does not reinitialize/reset the engine or reload SD/weights.
    assert(!s2c::begin_task(10,20,5,2));assert(loads==1&&inits==1&&s2c::outcome().roi.completed==0);
    visited.clear();for(unsigned i=0;i<4;++i)assert(!s2c::step_task());
    assert(visited.size()==10&&s2c::outcome().roi.completed==10);
    for(unsigned i=0;i<10;++i)assert(visited[i].x==10+i%5&&visited[i].y==20+i/5);
    assert(s2c::copy_segment(21,10,4,words));assert(!s2c::copy_segment(21,9,1,words));
    assert(!s2c::begin_task(399,549,1,1));assert(!s2c::step_task());
    assert(s2c::copy_pixel(0,word)&&word==(0xabcd0000u|((399+549)%9))&&loads==1);
    std::puts("PASS task runtime: arbitrary ROI/tail batches/new task/stop/probe/reentrancy/fault latch");
}
