#include "roi_canvas.h"
#include "roi_models.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>
using namespace s2c;
static void ppm(const std::string &path,const uint32_t *f) {
    std::ofstream out(path,std::ios::binary);out<<"P6\n1920 1080\n255\n";
    for(unsigned i=0;i<1920*1080;++i){char c[3]={char(f[i]),char(f[i]>>8),char(f[i]>>16)};out.write(c,3);}
    assert(out.good());
}
int main(int argc,char **argv) {
    assert(argc==2);const size_t size=size_t(DISPLAY_W)*DISPLAY_H;std::vector<uint32_t> frame(size+2,0xdeadbeef);
    for(unsigned scene=0;scene<3;++scene) {
        const auto &spec=*scene_contract(scene);DisplayView v{};v.scene=scene;v.wcrc=0x12345678+scene;std::strcpy(v.tag,"demo_1");
        v.boot=1;v.session=2;v.task=10+scene;v.state=ViewState::running;v.width=spec.width;v.height=spec.height;
        SceneCanvas canvas;assert(canvas.begin(frame.data()+1,size,v));assert(canvas.map_x()+canvas.map_width()<=SCENE_MAP_X+SCENE_MAP_W);
        assert(std::abs(double(canvas.map_width())*spec.height/canvas.map_height()-spec.width)<2);
        uint32_t bad=spec.classes;auto before=frame;assert(!canvas.append(0,0,1,&bad)&&frame==before);
        std::vector<uint32_t> words(spec.width);
        for(unsigned row=0;row<spec.height;++row) {
            for(unsigned col=0;col<spec.width;++col)words[col]=0xabcd0000u|((row/30+col/20)%spec.classes);
            assert(canvas.append(row,0,spec.width,words.data()));v.completed+=spec.width;assert(canvas.update(v));
        }
        v.state=ViewState::done;v.compute_ms_per_pixel=5;assert(canvas.update(v));
        assert(canvas.completed()==unsigned(spec.width)*spec.height&&frame.front()==0xdeadbeef&&frame.back()==0xdeadbeef);
        ppm(std::string(argv[1])+"/"+spec.name+".ppm",frame.data()+1);
        before=frame;v.scene=(scene+1)%3;assert(!canvas.update(v)&&frame==before);v.scene=scene;
        ++v.wcrc;assert(!canvas.update(v)&&frame==before);--v.wcrc;v.tag[0]='x';assert(!canvas.update(v)&&frame==before);
        // Lowest-right ROI remains in its own scene coordinate system.
        v.tag[0]='d';++v.task;v.x=spec.width-1;v.y=spec.height-1;v.width=v.height=1;v.completed=0;v.state=ViewState::running;
        assert(canvas.begin(frame.data()+1,size,v));uint32_t word=0xffff0000u|(spec.classes-1);
        assert(canvas.append(v.y,v.x,1,&word));v.completed=1;v.state=ViewState::done;assert(canvas.update(v));
        const unsigned x=canvas.map_x()+canvas.map_width()-1,y=canvas.map_y()+canvas.map_height()-1;
        assert(frame[1+y*DISPLAY_W+x]==class_color(spec.classes-1));
    }
    std::puts("three-scene canvas PASS: shapes/classes/palette/immutable model identity/edge ROI/cache damage coordinates; synthetic frames NOT DP board acceptance");
}
