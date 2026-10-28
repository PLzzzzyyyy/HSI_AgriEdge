#include "roi_canvas.h"
#include "roi_labels.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
int main(int argc,char **argv){
    using namespace s2c;assert(argc==2);
    std::vector<uint32_t> f(DISPLAY_W*DISPLAY_H);static SceneCanvas c;
    DisplayView v{};v.boot=1;v.session=2;v.scene=1;v.width=475;v.height=940;v.preview_scene=true;v.state=ViewState::ready;
    assert(c.begin(f.data(),f.size(),v));
    DispatchView d{};d.source=6;d.gesture=2;d.action=DispatchAction::parcel;d.phase=DispatchPhase::preparing;
    assert(c.dispatch(d));auto old=f;assert(c.connection(PeerState::online,0));
    for(unsigned y=650;y<866;++y)for(unsigned x=88;x<400;++x)assert(f[y*DISPLAY_W+x]==old[y*DISPLAY_W+x]);
    assert(c.completed()==0&&c.class_count(0)==0); // card cannot create inference data
    FILE *file=std::fopen(argv[1],"wb");assert(file);std::fprintf(file,"P6\n1920 1080\n255\n");
    for(auto w:f){unsigned char rgb[]={static_cast<unsigned char>(w),static_cast<unsigned char>(w>>8),static_cast<unsigned char>(w>>16)};assert(std::fwrite(rgb,1,3,file)==3);}
    assert(!std::fclose(file));
}
