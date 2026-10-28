// Link-time unit fakes test ONLY the new scheduling adapter; no inference,
// no BSP, no sockets, and no claim these words are board results.
#include "roi_runtime.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static const char *mode;
static unsigned loads=0,inits=0,weights=0,rois=0;
int tt_m3a_sd_load(TTM3aSdSession &s,const TTM3aSdProfile &p,const TTM3aSdStorage &b) {
    ++loads; assert(p.width==400 && p.height==550 && p.files[3].crc32==0x27231983u);
    assert(b.files[0].capacity==243794880 && b.files[3].capacity==480576);
    s.attempted=true; s.loaded=std::strcmp(mode,"sd")!=0; return s.loaded?0:-203;
}
int tt_m3a_init(unsigned id) { ++inits; assert(id==0); return 0; }
int tt_m3a_load_weights(const void *,size_t n,uint32_t polls) {
    ++weights; assert(n==480576 && polls==100000000);
    return std::strcmp(mode,"load")==0?-5:0;
}
int tt_m3a_roi_run(TTM3aRoiSession &s,const TTM3aRoiRequest &r) {
    ++rois; assert(r.width==400 && r.height==550 && r.row_pixels==406);
    assert(r.x==0 && r.y==0 && r.roi_width==5 && r.roi_height==3 && r.batch_size==4);
    assert(r.cube_bytes==243794880 && r.cls_count==2646 && r.pos_count==15876);
    const bool fail=std::strcmp(mode,"roi")==0;
    s.completed=fail?8:15; s.halted=fail; s.driver_status=fail?-5:0;
    for(size_t i=0;i<s.completed;++i) r.results[i]={uint32_t(i%5),uint32_t(i/5),uint32_t(i)};
    return fail?TT_M3A_ROI_DRIVER:0;
}
int main(int argc,char **argv) {
    assert(argc==2); mode=argv[1]; uint32_t row[5];
    assert(!s2c::copy_row(0,row)); assert(!inits && !weights && !rois);
    const int sd=s2c::load_scene(); assert(loads==1 && !inits && !weights && !rois);
    const int rc=s2c::run_once();
    assert(s2c::run_once()==TT_M3A_ROI_HALTED); // never repeat LOAD_W or ROI
    if(std::strcmp(mode,"sd")==0) { assert(sd && rc && !inits && !weights && !rois); }
    else if(std::strcmp(mode,"load")==0) { assert(rc && inits==1 && weights==1 && !rois && s2c::outcome().roi.halted); }
    else if(std::strcmp(mode,"roi")==0) {
        assert(rc && inits==1 && weights==1 && rois==1 && s2c::outcome().roi.halted);
        assert(s2c::copy_row(0,row) && row[4]==4); assert(!s2c::copy_row(1,row));
    } else {
        assert(!rc && inits==1 && weights==1 && rois==1 && s2c::outcome().roi.completed==15);
        assert(s2c::copy_row(2,row) && row[4]==14);
    }
    assert(!s2c::copy_row(3,row)); assert(!s2c::copy_row(0,nullptr));
    std::puts("PASS: private scheduling/one-shot/failure-prefix adapter ONLY");
}
