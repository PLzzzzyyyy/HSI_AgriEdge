#include "roi_canvas.h"
#include "roi_labels.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
using namespace s2c;
static constexpr uint32_t PANEL=0xff000000u|17u|(25u<<8)|(35u<<16),ACCENT=0xff000000u|45u|(212u<<8)|(191u<<16);
static void check(const std::vector<uint32_t> &f,const labels::Bitmap &label) {
    assert(label.w<=390&&label.h<=36);
    for(unsigned y=8;y<56;++y)for(unsigned x=1490;x<1900;++x) {
        bool ink=false;
        if(x>=1510&&x<1510+label.w&&y>=20&&y<20+label.h) {
            const unsigned bit=(y-20)*label.w+x-1510;
            ink=(label.bits[bit/8]&(1u<<(7-bit%8)))!=0;
        }
        assert(f[y*DISPLAY_W+x]==(ink?ACCENT:PANEL));
    }
}
static void snapshot(const std::vector<uint32_t> &f,const char *dir,const char *name) {
    if(!dir)return;
    const std::string path=std::string(dir)+"/"+name+".ppm";
    auto *out=std::fopen(path.c_str(),"wb");assert(out);
    std::fprintf(out,"P6\n%u %u\n255\n",DISPLAY_W,DISPLAY_H);
    for(auto p:f){const unsigned char rgb[]={static_cast<unsigned char>(p),static_cast<unsigned char>(p>>8),static_cast<unsigned char>(p>>16)};std::fwrite(rgb,1,3,out);}
    std::fclose(out);
}
int main(int argc,char **argv) {
    std::vector<uint32_t> frame(size_t(DISPLAY_W)*DISPLAY_H);
    SceneCanvas canvas;DisplayView v{};v.width=20;v.height=10;
    assert(canvas.begin(frame.data(),frame.size(),v));check(frame,labels::COMMAND_IDLE);
    for(auto peer:{PeerState::waiting,PeerState::online,PeerState::timeout}) {
        assert(canvas.connection(peer,999));check(frame,labels::COMMAND_IDLE);
    }
    snapshot(frame,argc>1?argv[1]:nullptr,"idle");
    for(unsigned source:{0u,5u,6u}) {
        DispatchView d{};d.source=source;d.gesture=1;d.action=DispatchAction::region;
        for(auto phase:{DispatchPhase::waiting,DispatchPhase::received,DispatchPhase::preparing,DispatchPhase::running,DispatchPhase::paused}) {
            d.phase=phase;assert(canvas.dispatch(d));
            const auto &label=source?labels::COMMAND_TERMINAL:labels::COMMAND_PC;
            check(frame,label);
            // Heartbeats and their expiry must never change the task source.
            for(auto peer:{PeerState::online,PeerState::timeout,PeerState::waiting}) {
                assert(canvas.connection(peer,999));check(frame,label);
            }
        }
        snapshot(frame,argc>1?argv[1]:nullptr,source?"terminal":"pc");
        for(auto phase:{DispatchPhase::done,DispatchPhase::stopped,DispatchPhase::failed,DispatchPhase::selected}) {
            d.phase=phase;assert(canvas.dispatch(d));check(frame,labels::COMMAND_IDLE);
        }
    }
    DispatchView probe{};probe.action=DispatchAction::point;probe.phase=DispatchPhase::running;
    assert(canvas.dispatch(probe));check(frame,labels::COMMAND_PC);
    probe.phase=DispatchPhase::done;assert(canvas.dispatch(probe));check(frame,labels::COMMAND_IDLE);
    // Invalid packets cannot replace a valid status or touch framebuffer pixels.
    const auto before=frame;probe.source=7;assert(!canvas.dispatch(probe));assert(frame==before);
    std::puts("DP command status: idle / PC / KEY5 / KEY6, lifecycle, heartbeat isolation, stale-text clearing PASS");
}
