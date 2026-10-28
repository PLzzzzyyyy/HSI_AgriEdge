// New accessor only: fake producer writes CPU committed prefix, never DMA data.
#include "roi_runtime.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
int tt_m3a_sd_load(TTM3aSdSession &s,const TTM3aSdProfile &,const TTM3aSdStorage &) {s.loaded=true;return 0;}
int tt_m3a_init(unsigned){return 0;}
int tt_m3a_load_weights(const void *,size_t,uint32_t){return 0;}
// The prefix-only fixture never reaches the PROBE driver. Fail unconditionally
// if runtime changes violate that boundary, including builds with NDEBUG.
size_t tt_m3a_output_bytes(uint32_t,uint32_t,uint32_t,uint32_t,bool) {
    std::fputs("Unexpected PROBE output sizing in prefix-only fixture\n",stderr);
    std::abort();
}
int tt_m3a_run(const TTM3aJob &,uint32_t) {
    std::fputs("Unexpected PROBE driver run in prefix-only fixture\n",stderr);
    std::abort();
}
int tt_m3a_roi_run(TTM3aRoiSession &s,const TTM3aRoiRequest &r) {
    s.completed=8;s.halted=true;s.driver_status=-5;
    for(unsigned i=0;i<8;++i)r.results[i]={i%5,i/5,0xfedc0000u|i};
    return TT_M3A_ROI_DRIVER;
}
int main() {
    uint32_t word=0xdeadbeef;
    assert(!s2c::copy_pixel(0,word) && word==0xdeadbeef);
    assert(s2c::load_scene()==0);assert(s2c::run_once()==TT_M3A_ROI_DRIVER);
    for(unsigned i=0;i<8;++i)assert(s2c::copy_pixel(i,word) && word==(0xfedc0000u|i));
    word=0xdeadbeef;
    assert(!s2c::copy_pixel(8,word) && word==0xdeadbeef);
    assert(!s2c::copy_pixel(15,word) && word==0xdeadbeef);
    assert(s2c::outcome().roi.halted);
    int32_t logits[9]={};
    assert(s2c::probe_once(0,0,word,logits,9)==TT_M3A_ROI_HALTED);
    assert(word==0xdeadbeef);
    for(int32_t value:logits)assert(value==0);
    std::puts("PASS: display accessor exposes only 8 committed CPU pixels after failure, suffix untouched");
}
