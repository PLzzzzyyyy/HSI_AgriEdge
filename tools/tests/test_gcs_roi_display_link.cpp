// Pure CPU checks: no BSP, transport, device access or firmware execution.
#include "roi_canvas.h"
#include "roi_models.h"
#include "roi_labels.h"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {
constexpr size_t PIXELS=size_t(s2c::DISPLAY_W)*s2c::DISPLAY_H,GUARD=64;
constexpr uint32_t CANARY=0x1234abcdu;
unsigned marker_left=0,marker_top=0;
bool in_probe_panel(size_t i) {
    const unsigned x=unsigned(i%s2c::DISPLAY_W),y=unsigned(i/s2c::DISPLAY_W);
    return x>=s2c::PROBE_PANEL_X && x<s2c::PROBE_PANEL_X+s2c::PROBE_PANEL_W &&
           y>=s2c::PROBE_PANEL_Y && y<s2c::PROBE_PANEL_Y+s2c::PROBE_PANEL_H;
}
void same_outside_panel(const uint32_t *frame,const std::vector<uint32_t> &before) {
    for(size_t i=0;i<PIXELS;++i) {
        const unsigned x=unsigned(i%s2c::DISPLAY_W),y=unsigned(i/s2c::DISPLAY_W);
        const bool marker=x>=marker_left&&x<marker_left+25&&y>=marker_top&&y<marker_top+25;
        if(!in_probe_panel(i)&&!marker)assert(frame[i]==before[i]);
    }
}
void guarded(const std::vector<uint32_t> &storage) {
    for(size_t i=0;i<GUARD;++i)assert(storage[i]==CANARY && storage[GUARD+PIXELS+i]==CANARY);
}
void rejected(s2c::SceneCanvas &canvas,const s2c::ProbeView &probe,uint32_t *frame) {
    const std::vector<uint32_t> before(frame,frame+PIXELS);
    assert(!canvas.probe(probe));assert(std::equal(before.begin(),before.end(),frame));
    assert(canvas.completed()==1);
}
}

int main() {
    static_assert(s2c::PROBE_PANEL_X+s2c::PROBE_PANEL_W<=s2c::SCENE_MAP_X,"Probe card must stay left of map");
    static_assert(s2c::PROBE_PANEL_Y+s2c::PROBE_PANEL_H<s2c::DISPLAY_H,"Probe card fits framebuffer");
    s2c::SceneCanvas empty;s2c::ProbeView none{};assert(!empty.probe(none));
    for(unsigned scene=0;scene<3;++scene) {
        const auto *spec=s2c::scene_contract(scene);
        std::vector<uint32_t> storage(PIXELS+2*GUARD,CANARY);uint32_t *frame=storage.data()+GUARD;
        s2c::SceneCanvas canvas;s2c::DisplayView view{};
        view.boot=0x12345678;view.session=0x87654321;view.task=9;view.scene=scene;view.wcrc=0x27231983+scene;
        std::memcpy(view.tag,"v2",3);view.width=spec->width;view.height=spec->height;view.state=s2c::ViewState::preparing;
        assert(canvas.begin(frame,PIXELS,view));assert(canvas.completed()==0);guarded(storage);
        marker_left=canvas.map_x()+canvas.map_width()-25;marker_top=canvas.map_y()+canvas.map_height()-25;
        const std::vector<uint32_t> preparing(frame,frame+PIXELS);
        view.state=s2c::ViewState::running;assert(canvas.update(view));
        assert(!std::equal(preparing.begin(),preparing.end(),frame));
        const uint32_t scan_word=0x80000000;
        assert(canvas.append(0,0,1,&scan_word));view.completed=1;view.state=s2c::ViewState::stopped;
        assert(canvas.update(view));
        auto invalid_preparing=view;invalid_preparing.state=s2c::ViewState::preparing;
        const std::vector<uint32_t> stopped(frame,frame+PIXELS);
        assert(!canvas.update(invalid_preparing));assert(std::equal(stopped.begin(),stopped.end(),frame));
        s2c::ProbeView probe{};probe.boot=view.boot;probe.session=view.session;probe.task=view.task;
        probe.scene=scene;probe.wcrc=view.wcrc;std::memcpy(probe.tag,view.tag,16);
        probe.row=spec->height-1;probe.col=spec->width-1;probe.attention=true;
        for(unsigned cls=0;cls<spec->classes;++cls) {
            probe.word=((0x8000u+cls)<<16)|cls;
            const std::vector<uint32_t> before_probe(frame,frame+PIXELS);
            assert(canvas.probe(probe));assert(canvas.completed()==1);
            assert(!std::equal(before_probe.begin(),before_probe.end(),frame));
            const auto &label=s2c::labels::CLASS_TABLES[scene][cls];
            for(unsigned y=0;y<label.h;++y)for(unsigned x=0;x<label.w;++x) {
                const unsigned bit=y*label.w+x;
                const uint32_t expected=(label.bits[bit/8]&(1u<<(7-bit%8)))?0xffeee2d6u:0xff231911u;
                assert(frame[(208+y)*s2c::DISPLAY_W+132+x]==expected);
            }
            same_outside_panel(frame,stopped); // also preserves STOPPED task card
            assert(canvas.update(view));same_outside_panel(frame,stopped); // histogram re-render stays exact
            guarded(storage); // every Chinese class label stays in the separate card
        }
        auto bad=probe;bad.scene=(scene+1)%3;rejected(canvas,bad,frame);
        bad=probe;++bad.wcrc;rejected(canvas,bad,frame);
        bad=probe;bad.wcrc=0;rejected(canvas,bad,frame);
        bad=probe;++bad.boot;rejected(canvas,bad,frame);
        bad=probe;++bad.session;rejected(canvas,bad,frame);
        bad=probe;++bad.task;rejected(canvas,bad,frame);
        bad=probe;bad.tag[1]='3';rejected(canvas,bad,frame);
        bad=probe;bad.row=spec->height;rejected(canvas,bad,frame);
        bad=probe;bad.col=spec->width;rejected(canvas,bad,frame);
        bad=probe;bad.word=0x80000100;rejected(canvas,bad,frame);
        bad=probe;bad.word=0x80000000|spec->classes;rejected(canvas,bad,frame);
        view.state=s2c::ViewState::paused;assert(canvas.update(view));
        const std::vector<uint32_t> paused(frame,frame+PIXELS);
        assert(canvas.probe(probe));assert(canvas.update(view));same_outside_panel(frame,paused);
        // A probe must not consume the next scan coordinate or alter counts.
        assert(canvas.append(0,1,1,&scan_word));view.completed=2;assert(canvas.update(view));
        std::vector<uint32_t> expected(PIXELS);s2c::SceneCanvas reference;
        auto initial=view;initial.completed=0;initial.state=s2c::ViewState::running;
        assert(reference.begin(expected.data(),PIXELS,initial));
        const uint32_t pair[2]={scan_word,scan_word};assert(reference.append(0,0,2,pair));assert(reference.update(view));
        same_outside_panel(frame,expected);assert(canvas.completed()==reference.completed());guarded(storage);
        // New task clears the old probe card and accepts its own identity.
        auto next=initial;++next.task;next.state=s2c::ViewState::preparing;
        assert(canvas.begin(frame,PIXELS,next));assert(reference.begin(expected.data(),PIXELS,next));
        assert(std::equal(expected.begin(),expected.end(),frame));guarded(storage);
        std::printf("scene %s: preparing/running, isolated probe, model/task rejection, counters, bounds PASS\n",spec->name);
    }
}
