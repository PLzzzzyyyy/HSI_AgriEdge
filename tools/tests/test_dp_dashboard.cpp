#include "roi_canvas.h"
#include "roi_models.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
using namespace s2c;
constexpr size_t PIXELS=size_t(DISPLAY_W)*DISPLAY_H;
constexpr uint32_t GUARD=0x12345678;
static bool map_pixel(const SceneCanvas &c,unsigned x,unsigned y) {
    return x>=c.map_x()&&x<c.map_x()+c.map_width()&&y>=c.map_y()&&y<c.map_y()+c.map_height();
}
int main() {
    assert(scene_gsd_mm(0)==463&&scene_gsd_mm(1)==43&&scene_gsd_mm(2)==109&&scene_gsd_mm(3)==0);
    for(unsigned scene=0;scene<3;++scene) {
        const auto *spec=scene_contract(scene);
        std::vector<uint32_t> allocation(PIXELS+128,GUARD);auto *f=allocation.data()+64;
        SceneCanvas c;DisplayView v{};v.boot=1;v.session=2;v.task=3;v.scene=scene;v.wcrc=4;
        std::memcpy(v.tag,"v2",3);v.x=10;v.y=20;v.width=spec->classes;v.height=2;v.kind=TaskKind::region;v.state=ViewState::running;
        assert(c.begin(f,PIXELS,v));
        auto wrong=v;wrong.kind=TaskKind::full_scene;std::vector<uint32_t> other(PIXELS);SceneCanvas bad;
        assert(!bad.begin(other.data(),PIXELS,wrong));
        std::vector<uint32_t> words(spec->classes);for(unsigned i=0;i<spec->classes;++i)words[i]=0x80000000|i;
        assert(c.append(20,10,spec->classes,words.data()));v.completed=spec->classes;assert(c.update(v));
        ProbeView p{};p.boot=1;p.session=2;p.task=3;p.scene=scene;p.wcrc=4;std::memcpy(p.tag,"v2",3);
        p.row=21;p.col=10;p.state=ProbeState::running;assert(c.probe(p));
        assert(c.append(21,10,spec->classes,words.data()));v.completed*=2;v.state=ViewState::done;assert(c.update(v));
        for(unsigned i=0;i<spec->classes;++i)assert(c.class_count(i)==2);
        p.state=ProbeState::done;p.word=0x90000000;p.attention=true;assert(c.probe(p));
        // Move the overlay away: pixels underneath the previous marker must be exact.
        p.row=spec->height-1;p.col=spec->width-1;assert(c.probe(p));
        SceneCanvas reference;auto initial=v;initial.completed=0;initial.state=ViewState::running;
        assert(reference.begin(other.data(),PIXELS,initial));assert(reference.append(20,10,spec->classes,words.data()));
        assert(reference.append(21,10,spec->classes,words.data()));assert(reference.update(v));
        const unsigned mx=c.map_x()+c.map_width()-25,my=c.map_y()+c.map_height()-25;
        for(unsigned y=0;y<DISPLAY_H;++y)for(unsigned x=0;x<DISPLAY_W;++x)
            if(map_pixel(c,x,y)&&!(x>=mx&&y>=my))assert(f[y*DISPLAY_W+x]==other[y*DISPLAY_W+x]);
        double sum=0;for(unsigned i=0;i<spec->classes;++i)sum+=c.class_area_m2(i);
        const double gsd=double(scene_gsd_mm(scene))/1000.0;
        assert(std::abs(sum-v.completed*gsd*gsd)<1e-8);assert(c.completed()==v.completed);
        const std::vector<uint32_t> before(f,f+PIXELS);auto invalid=p;++invalid.task;
        assert(!c.probe(invalid));assert(std::equal(before.begin(),before.end(),f));
        assert(c.connection(PeerState::timeout,17));
        for(unsigned y=0;y<DISPLAY_H;++y)for(unsigned x=0;x<DISPLAY_W;++x)
            if(map_pixel(c,x,y)||(x>=1240&&y>=80))assert(f[y*DISPLAY_W+x]==before[y*DISPLAY_W+x]);
        assert(c.update(v));assert(c.completed()==v.completed);
        p.state=ProbeState::failed;p.error=-1;assert(c.probe(p));assert(c.completed()==v.completed);
        auto next=initial;++next.task;assert(c.begin(f,PIXELS,next));
        assert(reference.begin(other.data(),PIXELS,next));assert(std::equal(other.begin(),other.end(),f));
        for(unsigned i=0;i<64;++i)assert(allocation[i]==GUARD&&allocation[64+PIXELS+i]==GUARD);
        next.kind=TaskKind::full_scene;next.x=next.y=0;next.width=spec->width;next.height=spec->height;
        assert(c.begin(f,PIXELS,next));
        std::printf("%s: area conservation, ROI bounds, marker restore, peer isolation, new-task reset PASS\n",spec->name);
    }
}
