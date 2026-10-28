#ifndef S2C_ROI_CANVAS_H
#define S2C_ROI_CANVAS_H
#include "roi_power.h"
#include <cstdint>
#include <cstddef>
namespace s2c {
constexpr unsigned DISPLAY_W=1920, DISPLAY_H=1080;
enum class ViewState { ready, running, done, failed, paused, stopped, preparing };
enum class TaskKind { region, full_scene };
enum class PeerState { waiting, online, timeout };
enum class ProbeState { running, done, failed };
enum class DispatchAction { none, point, scan, region, parcel, scene, pause, resume, stop };
enum class DispatchPhase { waiting, received, preparing, running, paused, done, stopped, failed, selected };
struct DispatchView {
    unsigned source=0,gesture=0,task=0;uint32_t event=0;
    DispatchAction action=DispatchAction::none;DispatchPhase phase=DispatchPhase::waiting;
};
struct DisplayView {
    uint32_t boot, session; unsigned task, completed; ViewState state;
    uint32_t words[15]; bool valid[15]; int error;
    unsigned x=0,y=0,width=400,height=550;
    unsigned scene=0;uint32_t wcrc=0;char tag[16]={};
    bool fault_requires_reset=true;
    float compute_ms_per_pixel=0; // zero/NaN means unmeasured, never a fabricated latency
    TaskKind kind=TaskKind::region;
    bool preview_scene=false; // selected scene/model, with no inference task yet
};
// A probe is an independent observation, never a committed scan pixel.
struct ProbeView {
    uint32_t boot=0,session=0;unsigned task=0,scene=0;uint32_t wcrc=0;
    char tag[16]={};unsigned row=0,col=0;uint32_t word=0;bool attention=false;
    ProbeState state=ProbeState::done;int error=0;
};
// PC summaries of verified received board pixels. Coordinates normalized to
// 0..65535 only for drawing; classification membership is computed on the PC.
struct ParcelView {
    uint32_t boot=0,session=0,wcrc=0,revision=0,id=0,serial=0;
    unsigned task=0,scene=0,classes=0,points=0;
    bool selected=false;
    bool local=false; // CPU-only origin; not part of the PC parcel wire layout
    uint32_t pixels=0,received=0,low=0,counts[24]={};
    uint16_t threshold=0,xy[128][2]={};
    uint8_t name_bits[576]={}; // 192x24, row-major MSB first, rendered by PC
};
// Pure CPU drawing. No device, inference, reference lookup or buffer ownership changes.
uint32_t class_color(unsigned id);
unsigned scene_gsd_mm(unsigned scene);
bool render(uint32_t *frame, size_t pixels, const DisplayView &view);
constexpr unsigned SCENE_MAP_X=470,SCENE_MAP_Y=88,SCENE_MAP_W=640,SCENE_MAP_H=880;
constexpr unsigned SCENE_PANEL_X=1240,SCENE_PANEL_Y=80;
constexpr unsigned PROBE_PANEL_X=88,PROBE_PANEL_Y=100,PROBE_PANEL_W=312,PROBE_PANEL_H=300;
// Private incremental full-scene canvas. Only committed CPU CLASS words enter;
// no inference/DMA output reads. New task clears the whole frame exactly once.
class SceneCanvas {
    uint32_t *frame_=nullptr;
    uint32_t boot_=0,session_=0;
    unsigned task_=0,completed_=0,counts_[24]={},scene_=0,classes_=9,scene_width_=400,scene_height_=550;
    uint32_t wcrc_=0;char tag_[16]={};
    TaskKind kind_=TaskKind::region;
    ViewState state_=ViewState::ready;
    PeerState peer_state_=PeerState::waiting;unsigned peer_age_=0;
    DispatchView dispatch_{};
    bool marker_=false;unsigned marker_x_=0,marker_y_=0,marker_w_=0,marker_h_=0;
    uint32_t marker_back_[25*25]={};
    unsigned probe_row_=0,probe_col_=0;
    ParcelView parcel_{};bool parcel_selected_=false;
    uint64_t parcel_at_=0;unsigned parcel_age_=0;
    uint8_t map_base_[SCENE_MAP_W*SCENE_MAP_H]={};
    void statistics();void parcel_outline();void restore_map();
    void restore_marker();void paint_marker();void outline();
    unsigned x_=0,y_=0,width_=400,height_=550;
    unsigned map_x_=SCENE_MAP_X,map_y_=SCENE_MAP_Y,map_w_=SCENE_MAP_W,map_h_=SCENE_MAP_H;
public:
    bool begin(uint32_t *,size_t,const DisplayView &);
    bool append(unsigned row,unsigned col,unsigned n,const uint32_t *words);
    bool update(const DisplayView &);
    // Updates only the separate probe card. Task state, histogram and progress
    // stay unchanged; probes from another task/model are rejected atomically.
    bool probe(const ProbeView &);
    bool connection(PeerState,unsigned age_seconds);
    bool dispatch(const DispatchView &);
    bool parcel(const ParcelView &,uint64_t now_us);
    bool parcel_age(uint64_t now_us);
    bool temperature(float current,float peak,bool valid);
    bool power(const PowerView &);
    bool keys(uint32_t id,unsigned state,unsigned code);
    unsigned class_count(unsigned id) const {return id<classes_?counts_[id]:0;}
    double class_area_m2(unsigned id) const;
    unsigned completed() const {return completed_;}
    unsigned map_x() const {return map_x_;}
    unsigned map_y() const {return map_y_;}
    unsigned map_width() const {return map_w_;}
    unsigned map_height() const {return map_h_;}
    unsigned row_y(unsigned row) const {return map_y_+row*map_h_/scene_height_;}
    unsigned row_height(unsigned row) const {return (row+1)*map_h_/scene_height_-row*map_h_/scene_height_;}
};
}
#endif
