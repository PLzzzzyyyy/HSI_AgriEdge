#include "roi_canvas.h"
#include "roi_models.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
int main(int argc,char **argv) {
    if(argc!=10)return 1;
    const unsigned scene=unsigned(std::atoi(argv[3]));const auto *spec=s2c::scene_contract(scene);if(!spec)return 2;
    const unsigned n=unsigned(spec->width)*spec->height;
    std::vector<uint32_t> words(n),frame(size_t(s2c::DISPLAY_W)*s2c::DISPLAY_H);
    FILE *input=std::fopen(argv[1],"rb");if(!input)return 3;
    const size_t got=std::fread(words.data(),4,n,input);std::fclose(input);if(got!=n)return 4;
    s2c::DisplayView v{};v.boot=1;v.session=2;v.task=5;v.scene=scene;v.wcrc=0x27231983;
    v.x=unsigned(std::atoi(argv[4]));v.y=unsigned(std::atoi(argv[5]));v.width=unsigned(std::atoi(argv[6]));v.height=unsigned(std::atoi(argv[7]));
    v.kind=std::atoi(argv[8])?s2c::TaskKind::full_scene:s2c::TaskKind::region;
    v.state=s2c::ViewState::running;std::memcpy(v.tag,"v2",3);
    s2c::SceneCanvas c;if(!c.begin(frame.data(),frame.size(),v))return 5;
    for(unsigned y=v.y;y<v.y+v.height;++y)if(!c.append(y,v.x,v.width,words.data()+y*spec->width+v.x))return 6;
    v.completed=v.width*v.height;v.state=s2c::ViewState::done;v.compute_ms_per_pixel=4.405f;
    if(!c.update(v))return 7;
    if(scene==0&&v.y<=169&&v.x<=68&&v.y+v.height>169&&v.x+v.width>68){
        s2c::ProbeView p{};p.boot=1;p.session=2;p.task=5;p.scene=scene;p.wcrc=v.wcrc;
        std::memcpy(p.tag,v.tag,16);p.row=169;p.col=68;p.word=words[169*spec->width+68];p.attention=true;if(!c.probe(p))return 8;
    }
    c.connection(std::atoi(argv[9])?s2c::PeerState::timeout:s2c::PeerState::online,std::atoi(argv[9])?17:0);
    FILE *out=std::fopen(argv[2],"wb");if(!out)return 9;
    std::fprintf(out,"P6\n%u %u\n255\n",s2c::DISPLAY_W,s2c::DISPLAY_H);
    for(auto pixel:frame){const unsigned char rgb[3]={static_cast<unsigned char>(pixel),static_cast<unsigned char>(pixel>>8),static_cast<unsigned char>(pixel>>16)};std::fwrite(rgb,1,3,out);}
    std::fclose(out);return 0;
}
