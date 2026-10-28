// Pure DP frame rendering, no device/driver. Optional real words replay is NOT DP visual acceptance.
#include "roi_canvas.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <fstream>
static void ppm(const char *path,const uint32_t *f) {
    std::ofstream out(path,std::ios::binary);out<<"P6\n1920 1080\n255\n";
    for(unsigned i=0;i<1920*1080;++i){char c[3]={char(f[i]),char(f[i]>>8),char(f[i]>>16)};out.write(c,3);}
}
int main(int argc,char **argv) {
    const size_t size=size_t(s2c::DISPLAY_W)*s2c::DISPLAY_H;
    std::vector<uint32_t> frame(size+2,0xdeadbeef),words(220000);
    for(unsigned i=0;i<words.size();++i)words[i]=0xabcd0000u|(i%9);
    if(argc==4){std::ifstream in(argv[1],std::ios::binary);in.read(reinterpret_cast<char*>(words.data()),880000);assert(in.gcount()==880000);}
    const unsigned limit=argc==4?unsigned(std::strtoul(argv[3],nullptr,10)):220000;
    assert(limit<=220000);
    s2c::DisplayView v{};v.boot=0xbb6bd8e3;v.session=0xae327bac;v.task=17276;v.state=s2c::ViewState::running;
    s2c::SceneCanvas canvas;
    assert(!canvas.begin(nullptr,size,v));assert(!canvas.begin(frame.data()+1,size-1,v));
    assert(canvas.begin(frame.data()+1,size,v));
    auto old=frame;
    assert(!canvas.append(0,1,1,words.data()));assert(frame==old);
    uint32_t invalid=0x00000100;
    assert(!canvas.append(0,0,1,&invalid));assert(frame==old);
    for(unsigned i=0;i<limit;){
        const unsigned n=(limit-i<400-i%400?limit-i:400-i%400);
        assert(canvas.append(i/400,i%400,n,words.data()+i));i+=n;
        v.completed=i;assert(canvas.update(v));
    }
    assert(canvas.completed()==limit);
    if(limit<220000){
        unsigned x=s2c::SCENE_MAP_X+(limit%400)*s2c::SCENE_MAP_W/400;
        unsigned y=s2c::SCENE_MAP_Y+(limit/400)*s2c::SCENE_MAP_H/550;
        assert(frame[1+y*1920+x]==(0xff000000u|(49u<<16)|(35u<<8)|23u));
    }
    for(unsigned i=0;i<limit;++i){
        unsigned x=s2c::SCENE_MAP_X+(i%400)*s2c::SCENE_MAP_W/400;
        unsigned y=s2c::SCENE_MAP_Y+(i/400)*s2c::SCENE_MAP_H/550;
        assert(frame[1+y*1920+x]==s2c::class_color(words[i]&255));
    }
    v.state=limit==220000?s2c::ViewState::done:s2c::ViewState::failed;v.error=limit==220000?0:-5;
    assert(canvas.update(v));
    old=frame;v.completed=limit+1;assert(!canvas.update(v));assert(frame==old);
    assert(frame.front()==0xdeadbeef&&frame.back()==0xdeadbeef);
    if(argc==4)ppm(argv[2],frame.data()+1);
    // An incomplete image must not claim DONE; immutable identity per frame.
    v.completed=0;v.error=0;v.state=s2c::ViewState::running;assert(canvas.begin(frame.data()+1,size,v));
    assert(frame[1+s2c::SCENE_MAP_Y*1920+s2c::SCENE_MAP_X]==(0xff000000u|(49u<<16)|(35u<<8)|23u));
    assert(canvas.append(0,0,3,words.data()));v.completed=3;v.state=s2c::ViewState::done;
    old=frame;assert(!canvas.update(v));assert(frame==old);
    v.state=s2c::ViewState::failed;v.error=-5;assert(canvas.update(v));
    v.task++;old=frame;assert(!canvas.update(v));assert(frame==old);
    v={};v.boot=1;v.task=2;v.state=s2c::ViewState::running;v.x=395;v.y=548;v.width=5;v.height=2;
    assert(canvas.begin(frame.data()+1,size,v));
    assert(!canvas.append(0,0,1,words.data()));assert(canvas.append(548,395,5,words.data()));
    v.completed=5;v.state=s2c::ViewState::paused;assert(canvas.update(v));
    v.state=s2c::ViewState::stopped;assert(canvas.update(v));
    v.task++;v.completed=0;v.state=s2c::ViewState::running;v.x=399;v.y=549;v.width=v.height=1;
    assert(canvas.begin(frame.data()+1,size,v));assert(canvas.append(549,399,1,words.data()));
    v.completed=1;v.state=s2c::ViewState::done;assert(canvas.update(v));
    old=frame;v.compute_ms_per_pixel=5;assert(canvas.update(v));assert(frame!=old);
    // Timing updates only the telemetry, never repaint valid class pixels.
    const unsigned px=s2c::SCENE_MAP_X+399*s2c::SCENE_MAP_W/400,py=s2c::SCENE_MAP_Y+549*s2c::SCENE_MAP_H/550;
    assert(frame[1+py*1920+px]==old[1+py*1920+px]);
    auto measured=frame;v.compute_ms_per_pixel=0;assert(canvas.update(v));assert(frame!=measured);
    assert(frame.front()==0xdeadbeef&&frame.back()==0xdeadbeef);
    std::puts("PASS scene canvas: full map/partial prefix/identity/class validation/guard words");
}
