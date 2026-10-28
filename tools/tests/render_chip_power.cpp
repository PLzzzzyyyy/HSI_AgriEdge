#include "roi_canvas.h"
#include <cassert>
#include <cstdio>
#include <vector>
int main(int argc,char **argv){
    using namespace s2c;assert(argc==2);
    const size_t count=DISPLAY_W*DISPLAY_H;constexpr uint32_t sentinel=0x13572468;
    std::vector<uint32_t> f(count+64,sentinel);static SceneCanvas canvas;
    DisplayView task{};task.boot=1;task.session=2;task.task=7;task.scene=1;task.width=475;task.height=940;
    task.preview_scene=true;task.state=ViewState::ready;assert(canvas.begin(f.data(),count,task));
    assert(canvas.temperature(38.5f,40.2f,true));const auto before=f;
    PowerView power{};power.watts=chip_power_w(38.5f);power.temperature=38.5f;power.temperature_valid=true;
    power.task=7;power.joules=123.45;power.duration_us=20000000;
    assert(canvas.power(power));
    for(size_t i=0;i<count;++i){
        const auto x=i%DISPLAY_W,y=i/DISPLAY_W;
        if(!(x>=88&&x<400&&((y>=410&&y<478)||(y>=980&&y<1042))))assert(f[i]==before[i]);
    }
    for(size_t i=count;i<f.size();++i)assert(f[i]==sentinel);
    FILE *file=std::fopen(argv[1],"wb");assert(file);std::fprintf(file,"P6\n1920 1080\n255\n");
    for(size_t i=0;i<count;++i){const auto word=f[i];unsigned char rgb[]={static_cast<unsigned char>(word),static_cast<unsigned char>(word>>8),static_cast<unsigned char>(word>>16)};assert(std::fwrite(rgb,1,3,file)==3);}
    assert(!std::fclose(file));std::puts("PASS power canvas bounds and isolated repaint");
}
