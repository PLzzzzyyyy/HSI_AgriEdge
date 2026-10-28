// Offline canvas fixtures only; no device or inference. Not board evidence.
#include "roi_canvas.h"
#include <cassert>
#include <vector>
#include <cstdio>
int main() {
    const size_t n=size_t(s2c::DISPLAY_W)*s2c::DISPLAY_H;
    std::vector<uint32_t> buf(n+2,0xdeadbeef);
    s2c::DisplayView v{};v.boot=0x12345678;v.state=s2c::ViewState::ready;
    assert(!s2c::render(nullptr,n,v)); assert(!s2c::render(buf.data()+1,n-1,v));
    assert(s2c::render(buf.data()+1,n,v));
    assert(buf.front()==0xdeadbeef && buf.back()==0xdeadbeef);
    v.state=s2c::ViewState::running;assert(s2c::render(buf.data()+1,n,v));
    for(unsigned i=0;i<15;++i){v.words[i]=0xfedc0000u|(i%9);v.valid[i]=true;}
    v.completed=15;v.state=s2c::ViewState::done;
    assert(s2c::render(buf.data()+1,n,v));
    for(unsigned i=0;i<15;++i)assert(buf[1+(270+(i/5)*218)*1920+32+(i%5)*374]==s2c::class_color(i%9));
    assert(buf.front()==0xdeadbeef && buf.back()==0xdeadbeef);
    auto old=buf;v.completed=14;assert(!s2c::render(buf.data()+1,n,v));assert(buf==old);
    v.completed=15;v.words[0]|=0x100;assert(!s2c::render(buf.data()+1,n,v));assert(buf==old);
    v.words[0]=0;v.error=-5;assert(!s2c::render(buf.data()+1,n,v));
    v.state=s2c::ViewState::failed;for(unsigned i=8;i<15;++i)v.valid[i]=false;v.completed=8;
    assert(s2c::render(buf.data()+1,n,v));
    assert(buf.front()==0xdeadbeef && buf.back()==0xdeadbeef);
    std::puts("PASS: real renderer bounds/status/15-cell colors/invalid completion/8-pixel failure prefix");
}
