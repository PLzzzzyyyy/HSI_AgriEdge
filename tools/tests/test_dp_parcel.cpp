#include "roi_canvas.h"
#include <cassert>
#include <cstring>
#include <vector>
#include <cstdio>
int main(){
    using namespace s2c;std::vector<uint32_t> frame(DISPLAY_W*DISPLAY_H),reference(frame.size());
    static SceneCanvas c,ref;DisplayView v{};v.boot=1;v.session=2;v.task=3;v.wcrc=4;v.width=10;v.height=2;v.state=ViewState::running;std::memcpy(v.tag,"v2",3);
    assert(c.begin(frame.data(),frame.size(),v));uint32_t words[10];for(unsigned i=0;i<10;++i)words[i]=0x90000000|(i%3);
    assert(c.append(0,0,10,words));v.completed=10;assert(c.update(v));
    ParcelView p{};p.boot=1;p.session=2;p.task=3;p.wcrc=4;p.scene=0;p.classes=9;p.points=4;p.selected=true;p.pixels=100;p.received=10;p.low=2;p.counts[0]=4;p.counts[1]=3;p.counts[2]=3;
    p.xy[1][0]=65535;p.xy[2][0]=p.xy[2][1]=65535;p.xy[3][1]=65535;
    assert(c.parcel(p,1000000));assert(c.completed()==10);assert(c.class_count(0)==4);
    auto bad=p;bad.boot=8;auto before=frame;assert(!c.parcel(bad,2000000));assert(frame==before);
    assert(c.append(1,0,10,words));v.completed=20;v.state=ViewState::done;assert(c.update(v));assert(c.completed()==20);
    assert(c.parcel_age(5000000));assert(c.temperature(55,60,true));
    ParcelView clear{};clear.boot=1;clear.session=2;clear.task=3;clear.wcrc=4;clear.classes=9;assert(c.parcel(clear,6000000));
    auto initial=v;initial.completed=0;initial.state=ViewState::running;assert(ref.begin(reference.data(),reference.size(),initial));assert(ref.append(0,0,10,words));assert(ref.append(1,0,10,words));assert(ref.update(v));
    for(unsigned y=c.map_y();y<c.map_y()+c.map_height();++y)for(unsigned x=c.map_x();x<c.map_x()+c.map_width();++x)assert(frame[y*DISPLAY_W+x]==reference[y*DISPLAY_W+x]);
    std::puts("parcel identity, scan isolation, coverage, stale state, map restoration PASS");
}
