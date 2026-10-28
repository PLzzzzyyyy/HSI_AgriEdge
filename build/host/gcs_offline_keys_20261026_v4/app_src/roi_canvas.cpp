#include "roi_canvas.h"
#include <cstdio>
#include <cmath>
#include <cstring>
#include <cctype>
#include "roi_models.h"
#include "roi_labels.h"
namespace s2c {
namespace {
constexpr uint32_t color(unsigned r,unsigned g,unsigned b) {return 0xff000000u|(b<<16)|(g<<8)|r;}
constexpr uint32_t BG=color(11,16,22), FG=color(214,226,238), MUTED=color(123,142,163);
// Hand-written 5x7 uppercase/digit glyph rows, no font dependency or SD asset.
const char chars[]="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-./:()=,%?_ ";
const unsigned char font[][7]={
 {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},{30,1,1,14,1,1,30},
 {2,6,10,18,31,2,2},{31,16,16,30,1,1,30},{14,16,16,30,17,17,14},{31,1,2,4,8,8,8},
 {14,17,17,14,17,17,14},{14,17,17,15,1,1,14},
 {14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{14,17,16,16,16,17,14},
 {30,17,17,17,17,17,30},{31,16,16,30,16,16,31},{31,16,16,30,16,16,16},
 {14,17,16,23,17,17,15},{17,17,17,31,17,17,17},{14,4,4,4,4,4,14},
 {7,2,2,2,2,18,12},{17,18,20,24,20,18,17},{16,16,16,16,16,16,31},
 {17,27,21,21,17,17,17},{17,25,21,19,17,17,17},{14,17,17,17,17,17,14},
 {30,17,17,30,16,16,16},{14,17,17,17,21,18,13},{30,17,17,30,20,18,17},
 {15,16,16,14,1,1,30},{31,4,4,4,4,4,4},{17,17,17,17,17,17,14},
 {17,17,17,17,17,10,4},{17,17,17,21,21,21,10},{17,17,10,4,10,17,17},
 {17,17,10,4,4,4,4},{31,1,2,4,8,16,31},
 {0,0,0,31,0,0,0},{0,0,0,0,0,6,6},{1,2,2,4,8,8,16},{0,6,6,0,6,6,0},
 {2,4,8,8,8,4,2},{8,4,2,2,2,4,8},{0,0,31,0,31,0,0},{0,0,0,0,6,4,8},{17,2,4,4,8,16,17},{14,17,1,2,4,0,4},{0,0,0,0,0,0,31},{0,0,0,0,0,0,0}
};
static_assert(sizeof(font)/sizeof(font[0])==sizeof(chars)-1,"glyph count");
void box(uint32_t *f,unsigned x,unsigned y,unsigned w,unsigned h,uint32_t c) {
    for(unsigned yy=y; yy<y+h && yy<DISPLAY_H; ++yy)
        for(unsigned xx=x; xx<x+w && xx<DISPLAY_W; ++xx) f[yy*DISPLAY_W+xx]=c;
}
void text(uint32_t *f,unsigned x,unsigned y,const char *s,unsigned scale,uint32_t c=FG) {
    for(unsigned i=0;s[i] && x<DISPLAY_W;++i,x+=6*scale) {
        unsigned k=0;while(chars[k] && chars[k]!=s[i])++k;
        if(!chars[k]){k=0;while(chars[k]!='?')++k;}
        for(unsigned yy=0;yy<7;++yy)for(unsigned xx=0;xx<5;++xx)
            if(font[k][yy]&(1u<<(4-xx)))box(f,x+xx*scale,y+yy*scale,scale,scale,c);
    }
}
}
namespace {
void bitmap(uint32_t *f,unsigned x,unsigned y,const labels::Bitmap &b,uint32_t c=FG) {
    for(unsigned yy=0;yy<b.h && y+yy<DISPLAY_H;++yy)
        for(unsigned xx=0;xx<b.w && x+xx<DISPLAY_W;++xx) {
            const unsigned bit=yy*b.w+xx;
            if(b.bits[bit/8]&(1u<<(7-bit%8)))f[(y+yy)*DISPLAY_W+x+xx]=c;
        }
}
}
bool SceneCanvas::keys(uint32_t id,unsigned state,unsigned code) {
    if(!frame_)return false;
    box(frame_,88,1046,1800,30,color(10,17,25));
    char line[140];
    if(!id)std::snprintf(line,sizeof(line),"KEY5: POINT / DOUBLE: SCAN   KEY6: ROI / DOUBLE: PARCEL   HOLD 2S: SCENE");
    else {
        const char *status=code==13?"BOARD LOCAL":state==1?"WAITING FOR PC":state==2?"ACCEPTED BY PC":state==3?"EXECUTED":"REJECTED";
        const char *why=code==1?"PC BACKEND OFFLINE":code==2?"TASK BUSY":code==3?"MODEL/INPUT NOT READY":
            code==4?"ACTION FAILED":code==10?"SCENE SELECTED - START A TASK TO LOAD INPUT":
            code==11?"PREPARING TASK - FIRST SCENE LOAD MAY TAKE 15-40S":
            code==12?"STOPPING TASK / SELECTING SCENE":"";
        std::snprintf(line,sizeof(line),"KEY EVENT %lu: %s  %s",(unsigned long)id,status,why);
    }
    text(frame_,88,1052,line,2,color(45,212,191));return true;
}
uint32_t class_color(unsigned id) {
    // The three GCS palettes share this prefix. Class IDs stay zero-based.
    static const uint32_t colors[22]={color(255,0,0),color(238,154,0),color(255,255,0),
        color(0,255,0),color(0,255,207),color(0,160,255),color(0,0,255),color(176,0,255),color(255,182,193),
        color(139,69,19),color(127,255,0),color(255,20,147),color(64,224,208),color(255,215,0),
        color(173,255,47),color(220,20,60),color(0,206,209),color(147,112,219),color(240,230,140),
        color(255,127,80),color(46,139,87),color(192,192,192)};
    return id<22?colors[id]:MUTED;
}
bool render(uint32_t *f,size_t pixels,const DisplayView &v) {
    if(!f || pixels<size_t(DISPLAY_W)*DISPLAY_H || v.completed>15) return false;
    unsigned count=0;
    for(unsigned i=0;i<15;++i) {
        if(v.valid[i]) { if((v.words[i]&255)>8 || (v.words[i]&0xff00))return false; ++count; }
    }
    if(count!=v.completed || (v.state==ViewState::done && (count!=15 || v.error)))return false;
    for(size_t i=0;i<size_t(DISPLAY_W)*DISPLAY_H;++i)f[i]=BG;
    text(f,32,24,"HSI AGRIEDGE / REAL BOARD",5);
    const char *status=v.state==ViewState::ready?"READY - WAIT FOR GCS":v.state==ViewState::preparing?"LOADING INPUT":
                       v.state==ViewState::running?"RUNNING":v.state==ViewState::paused?"PAUSED":
                       v.state==ViewState::stopped?"STOPPED":v.state==ViewState::done?"BOARD COMPLETE":"FAILED - RETAIN COMMITTED PREFIX";
    text(f,32,80,status,4,v.state==ViewState::failed?color(244,63,94):color(45,212,191));
    char s[128];
    std::snprintf(s,sizeof(s),"BOOT %08lX  SESSION %08lX  TASK %u",(unsigned long)v.boot,(unsigned long)v.session,v.task);
    text(f,32,130,s,3);
    text(f,32,170,"LONGKOU/V2  ROI (0,0) 5X3  WCRC 27231983",3);
    std::snprintf(s,sizeof(s),"CPU COMMITTED %u/15  ERROR %d  UDP RECEIPT: SEE GCS",v.completed,v.error);
    text(f,32,210,s,3);
    for(unsigned i=0;i<15;++i) {
        const unsigned x=32+(i%5)*374,y=270+(i/5)*218;
        box(f,x,y,358,202,color(22,33,45));
        box(f,x,y,358,10,v.valid[i]?class_color(v.words[i]&255):MUTED);
        std::snprintf(s,sizeof(s),"(%u,%u)",i%5,i/5);text(f,x+12,y+22,s,3);
        if(!v.valid[i]) {text(f,x+12,y+76,"NO RESULT",3,MUTED);continue;}
        std::snprintf(s,sizeof(s),"CLASS %lu",(unsigned long)(v.words[i]&255));text(f,x+12,y+64,s,4);
        std::snprintf(s,sizeof(s),"WORD %08lX",(unsigned long)v.words[i]);text(f,x+12,y+103,s,3);
        std::snprintf(s,sizeof(s),"Q16 %lu/65536",(unsigned long)(v.words[i]>>16));text(f,x+12,y+138,s,3);
        std::snprintf(s,sizeof(s),"CONF %.16f",double(v.words[i]>>16)/65536.0);text(f,x+12,y+175,s,2);
    }
    text(f,32,950,"TEMP / POWER / PERFORMANCE / PHY: NOT MEASURED",3,MUTED);
    text(f,32,994,"FIXED ROI ONLY - NOT FULL V1 / SCENE / OA / SOAK",3,MUTED);
    text(f,32,1035,"ON DMA FAILURE: EXTERNAL PL RESET + APP RESTART",3,MUTED);
    return true;
}

unsigned scene_gsd_mm(unsigned scene) {return scene<3?labels::SCENE_GSD_MM[scene]:0;}
double SceneCanvas::class_area_m2(unsigned id) const {
    const uint64_t mm=scene_gsd_mm(scene_);
    return id<classes_?double(uint64_t(counts_[id])*mm*mm)/1000000.0:0.0;
}
void SceneCanvas::outline() {
    if(!wcrc_)return;
    const unsigned x0=map_x_+x_*map_w_/scene_width_,y0=row_y(y_);
    const unsigned x1=map_x_+(x_+width_)*map_w_/scene_width_,y1=row_y(y_+height_);
    const uint32_t accent=color(45,212,191);
    // Border is outside the task's class pixels, so incremental rows preserve it.
    for(unsigned x=x0-2;x<x1+2;++x)if((x-x0+2)%12<7){box(frame_,x,y0-2,1,2,accent);box(frame_,x,y1,1,2,accent);}
    for(unsigned y=y0-2;y<y1+2;++y)if((y-y0+2)%12<7){box(frame_,x0-2,y,2,1,accent);box(frame_,x1,y,2,1,accent);}
}
void SceneCanvas::restore_marker() {
    if(!marker_)return;
    for(unsigned y=0;y<marker_h_;++y)for(unsigned x=0;x<marker_w_;++x)
        frame_[(marker_y_+y)*DISPLAY_W+marker_x_+x]=marker_back_[y*25+x];
}
void SceneCanvas::paint_marker() {
    if(!marker_)return;
    const unsigned cx=map_x_+(2*probe_col_+1)*map_w_/(2*scene_width_);
    const unsigned cy=map_y_+(2*probe_row_+1)*map_h_/(2*scene_height_);
    marker_x_=cx>map_x_+12?cx-12:map_x_;marker_y_=cy>map_y_+12?cy-12:map_y_;
    marker_w_=map_x_+map_w_-marker_x_;if(marker_w_>25)marker_w_=25;
    marker_h_=map_y_+map_h_-marker_y_;if(marker_h_>25)marker_h_=25;
    for(unsigned y=0;y<marker_h_;++y)for(unsigned x=0;x<marker_w_;++x) {
        const unsigned xx=marker_x_+x,yy=marker_y_+y;
        marker_back_[y*25+x]=frame_[yy*DISPLAY_W+xx];
        const int dx=std::abs(int(xx)-int(cx)),dy=std::abs(int(yy)-int(cy));
        if((dx<=11&&dy<=2)||(dy<=11&&dx<=2)||(dx<=5&&dy>=3&&dy<=5)||(dy<=5&&dx>=3&&dx<=5))
            frame_[yy*DISPLAY_W+xx]=color(3,8,14);
        if((dx<=10&&dy<=1)||(dy<=10&&dx<=1)||(dx<=4&&dy==4)||(dy<=4&&dx==4))
            frame_[yy*DISPLAY_W+xx]=color(255,220,60);
    }
}
bool SceneCanvas::begin(uint32_t *f,size_t pixels,const DisplayView &v) {
    const auto *spec=scene_contract(v.scene);
    if(!f || pixels<size_t(DISPLAY_W)*DISPLAY_H || v.completed || v.error ||
       !spec || v.x>=spec->width || v.y>=spec->height || !v.width || !v.height ||
       v.width>spec->width-v.x || v.height>spec->height-v.y || v.tag[15] ||
       (v.kind==TaskKind::full_scene&&(v.x||v.y||v.width!=spec->width||v.height!=spec->height)) ||
       (v.state!=ViewState::ready && v.state!=ViewState::preparing && v.state!=ViewState::running))return false;
    frame_=f;boot_=v.boot;session_=v.session;task_=v.task;completed_=0;kind_=v.kind;state_=v.state;marker_=false;parcel_selected_=false;parcel_age_=0;
    std::memset(map_base_,0,sizeof(map_base_));
    x_=v.x;y_=v.y;width_=v.width;height_=v.height;
    scene_=v.scene;classes_=spec->classes;scene_width_=spec->width;scene_height_=spec->height;
    wcrc_=v.wcrc;std::memcpy(tag_,v.tag,16);
    map_h_=SCENE_MAP_H;map_w_=scene_width_*map_h_/scene_height_;
    if(map_w_>SCENE_MAP_W){map_w_=SCENE_MAP_W;map_h_=scene_height_*map_w_/scene_width_;}
    map_x_=SCENE_MAP_X+(SCENE_MAP_W-map_w_)/2;map_y_=SCENE_MAP_Y+(SCENE_MAP_H-map_h_)/2;
    for(unsigned &n:counts_)n=0;
    for(size_t i=0;i<size_t(DISPLAY_W)*DISPLAY_H;++i)f[i]=BG;
    const uint32_t panel=color(17,25,35),line=color(32,48,65),accent=color(45,212,191);
    box(f,0,0,DISPLAY_W,64,panel);box(f,0,63,DISPLAY_W,1,line);
    bitmap(f,24,16,labels::TITLE);bitmap(f,680,12,(v.wcrc||v.preview_scene)?labels::SCENES[scene_]:labels::NO_TASK,accent);
    char s[100];std::snprintf(s,sizeof(s),"%s / AXU5EV-E",v.tag);for(char *q=s;*q;++q)*q=char(std::toupper(static_cast<unsigned char>(*q)));
    text(f,680,43,s,2,MUTED);
    box(f,map_x_-2,map_y_-2,map_w_+4,map_h_+4,MUTED);
    box(f,map_x_,map_y_,map_w_,map_h_,color(23,35,49));outline();
    box(f,1240,80,650,250,panel);box(f,1240,350,650,690,panel);
    bitmap(f,1260,368,wcrc_?(kind_==TaskKind::full_scene?labels::AREA_SCAN:labels::AREA_REGION):labels::TASK_WAIT);
    bitmap(f,1570,377,labels::AREA_BASIS,MUTED);
    bitmap(f,1260,417,labels::AREA_CLASS,MUTED);bitmap(f,1536,417,labels::AREA_M2,MUTED);
    bitmap(f,1718,417,labels::AREA_SHARE,MUTED);bitmap(f,1810,417,labels::AREA_PIXELS,MUTED);
    for(unsigned i=0;i<classes_;++i){box(f,1260,456+i*24,12,12,class_color(i));bitmap(f,1284,453+i*24,labels::CLASS_TABLES[scene_][i]);}
    bitmap(f,1260,1008,labels::AREA_TOTAL,MUTED);
    box(f,88,100,312,300,panel);bitmap(f,104,118,labels::PROBE_TITLE,accent);
    bitmap(f,104,180,labels::PROBE_EMPTY,MUTED);bitmap(f,104,350,labels::PROBE_ONLY,MUTED);
    box(f,88,430,312,190,panel);bitmap(f,104,448,labels::SYSTEM,MUTED);
    bitmap(f,88,879,labels::PARCEL_HINT,MUTED);
    bitmap(f,88,1055,labels::UNMEASURED_HINT,MUTED);
    connection(PeerState::waiting,0);
    return update(v);
}
bool SceneCanvas::append(unsigned row,unsigned col,unsigned n,const uint32_t *words) {
    if(!frame_ || !words || row!=y_+completed_/width_ || col!=x_+completed_%width_ ||
       row>=y_+height_ || !n || n>x_+width_-col)return false;
    for(unsigned i=0;i<n;++i)if((words[i]&255)>=classes_ || (words[i]&0xff00))return false;
    restore_marker();
    const unsigned y=row_y(row),h=row_height(row);
    for(unsigned i=0;i<n;++i) {
        const unsigned x=map_x_+(col+i)*map_w_/scene_width_;
        const unsigned w=(col+i+1)*map_w_/scene_width_-(col+i)*map_w_/scene_width_;
        box(frame_,x,y,w,h,class_color(words[i]&255));
        for(unsigned yy=y;yy<y+h;++yy)for(unsigned xx=x;xx<x+w;++xx)
            map_base_[(yy-map_y_)*SCENE_MAP_W+xx-map_x_]=uint8_t((words[i]&255)+1);
        ++counts_[words[i]&255];
    }
    completed_+=n;parcel_outline();paint_marker();return true;
}
bool SceneCanvas::update(const DisplayView &v) {
    if(!frame_ || v.boot!=boot_ || v.session!=session_ || v.task!=task_ || v.completed!=completed_ ||
       v.x!=x_ || v.y!=y_ || v.width!=width_ || v.height!=height_ || v.kind!=kind_ ||
       v.scene!=scene_ || v.wcrc!=wcrc_ || std::memcmp(v.tag,tag_,16) ||
       (v.state==ViewState::preparing && completed_) ||
       (v.state==ViewState::done && (completed_!=width_*height_ || v.error)) ||
       (v.error && v.state!=ViewState::failed))return false;
    state_=v.state;
    const uint32_t panel=color(17,25,35),accent=color(45,212,191);
    box(frame_,1260,94,610,224,panel);
    bitmap(frame_,1260,98,!wcrc_?labels::TASK_WAIT:kind_==TaskKind::full_scene?labels::TASK_SCAN:labels::TASK_REGION,accent);
    const auto &status=v.state==ViewState::preparing?labels::STATE_PREP:v.state==ViewState::running?labels::STATE_RUNNING:
        v.state==ViewState::paused?labels::STATE_PAUSED:v.state==ViewState::stopped?labels::STATE_STOPPED:
        v.state==ViewState::done?labels::STATE_DONE:v.state==ViewState::failed?labels::STATE_FAILED:labels::READY;
    bitmap(frame_,1650,106,status,v.state==ViewState::failed?color(244,63,94):accent);
    char s[100];const unsigned total=width_*height_;
    if(wcrc_)std::snprintf(s,sizeof(s),"%u X %u",height_,width_);else std::snprintf(s,sizeof(s),"-- X --");
    text(frame_,1260,154,s,4);bitmap(frame_,1530,158,labels::DIMENSION,MUTED);
    bitmap(frame_,1260,207,labels::ROW,MUTED);bitmap(frame_,1576,207,labels::COL,MUTED);
    if(wcrc_)std::snprintf(s,sizeof(s),"%u - %u",y_,y_+height_-1);else std::snprintf(s,sizeof(s),"--");text(frame_,1304,210,s,3);
    if(wcrc_)std::snprintf(s,sizeof(s),"%u - %u",x_,x_+width_-1);else std::snprintf(s,sizeof(s),"--");text(frame_,1620,210,s,3);
    bitmap(frame_,1260,247,labels::COMPUTED,MUTED);
    std::snprintf(s,sizeof(s),"%u / %u",completed_,wcrc_?total:0);text(frame_,1380,251,s,2);
    std::snprintf(s,sizeof(s),"%.1f%%",wcrc_?100.0*completed_/total:0.0);text(frame_,1750,249,s,3,accent);
    box(frame_,1260,284,610,10,color(23,35,49));box(frame_,1260,284,completed_*610/total,10,accent);
    bitmap(frame_,1260,302,labels::BOARD_TASK,MUTED);std::snprintf(s,sizeof(s),"%u",task_);text(frame_,1370,304,s,2,MUTED);
    box(frame_,104,488,280,120,panel);bitmap(frame_,104,488,labels::RATE,MUTED);bitmap(frame_,104,552,labels::LATENCY,MUTED);
    if(std::isfinite(v.compute_ms_per_pixel)&&v.compute_ms_per_pixel>0&&completed_)std::snprintf(s,sizeof(s),"%.1f",1000.0/v.compute_ms_per_pixel);
    else std::snprintf(s,sizeof(s),"--");
    text(frame_,104,512,s,3,accent);
    if(std::isfinite(v.compute_ms_per_pixel)&&v.compute_ms_per_pixel>0&&completed_)std::snprintf(s,sizeof(s),"%.3f",double(v.compute_ms_per_pixel));
    else std::snprintf(s,sizeof(s),"--");
    text(frame_,104,578,s,3,accent);
    statistics();
    if(v.state==ViewState::failed){bitmap(frame_,88,903,labels::FAULT_HINT,color(244,63,94));std::snprintf(s,sizeof(s),"ERROR %d",v.error);text(frame_,88,878,s,2,color(244,63,94));}
    connection(peer_state_,peer_age_);
    return true;
}

void SceneCanvas::statistics() {
    if(!frame_)return;
    const uint32_t panel=color(17,25,35),accent=color(45,212,191);
    box(frame_,1240,350,650,690,panel);char s[100];
    if(parcel_selected_) {
        const double gsd=double(scene_gsd_mm(scene_))/1000.0;
        bitmap(frame_,1260,366,labels::PARCEL_TITLE,accent);
        const labels::Bitmap name={192,24,parcel_.name_bits};bitmap(frame_,1380,366,name);
        bitmap(frame_,1650,370,!parcel_.received?labels::PARCEL_NONE:parcel_.received==parcel_.pixels?labels::PARCEL_FULL:labels::PARCEL_PART,accent);
        bitmap(frame_,1260,403,labels::PARCEL_TOTAL,MUTED);std::snprintf(s,sizeof(s),"%.1f M2",parcel_.pixels*gsd*gsd);text(frame_,1380,405,s,2);
        bitmap(frame_,1580,403,labels::PARCEL_SEEN,MUTED);std::snprintf(s,sizeof(s),"%.1f M2",parcel_.received*gsd*gsd);text(frame_,1700,405,s,2);
        bitmap(frame_,1260,433,labels::PARCEL_COVER,MUTED);std::snprintf(s,sizeof(s),"%.1f%%  (%u / %u)",100.0*parcel_.received/parcel_.pixels,parcel_.received,parcel_.pixels);text(frame_,1380,435,s,2,accent);
        unsigned main=0;for(unsigned i=1;i<classes_;++i)if(parcel_.counts[i]>parcel_.counts[main])main=i;
        bitmap(frame_,1260,463,labels::PARCEL_MAIN,MUTED);
        if(parcel_.received)bitmap(frame_,1360,462,labels::CLASS_TABLES[scene_][main]);else text(frame_,1360,465,"--",2);
        bitmap(frame_,1260,494,labels::PARCEL_SHARE,MUTED);bitmap(frame_,1460,494,labels::PARCEL_MIX,MUTED);bitmap(frame_,1660,494,labels::PARCEL_LOW,MUTED);
        const double share=parcel_.received?double(parcel_.counts[main])/parcel_.received:0;
        if(parcel_.received)std::snprintf(s,sizeof(s),"%.1f%%",100*share);else std::snprintf(s,sizeof(s),"--");text(frame_,1344,496,s,2);
        if(parcel_.received)std::snprintf(s,sizeof(s),"%.1f%%",100*(1-share));else std::snprintf(s,sizeof(s),"--");text(frame_,1544,496,s,2);
        if(parcel_.received)std::snprintf(s,sizeof(s),"%.1f%%",100.0*parcel_.low/parcel_.received);else std::snprintf(s,sizeof(s),"--");text(frame_,1760,496,s,2);
        bitmap(frame_,1260,526,labels::AREA_CLASS,MUTED);bitmap(frame_,1536,526,labels::AREA_M2,MUTED);bitmap(frame_,1718,526,labels::AREA_SHARE,MUTED);bitmap(frame_,1810,526,labels::AREA_PIXELS,MUTED);
        unsigned order[24];for(unsigned i=0;i<classes_;++i)order[i]=i;
        for(unsigned i=1;i<classes_;++i)for(unsigned j=i;j&&parcel_.counts[order[j]]>parcel_.counts[order[j-1]];--j){unsigned t=order[j];order[j]=order[j-1];order[j-1]=t;}
        for(unsigned i=0;i<classes_;++i){const unsigned cls=order[i],yy=552+i*(classes_<=18?24:19);
            box(frame_,1260,yy+2,10,10,class_color(cls));bitmap(frame_,1280,yy,labels::CLASS_TABLES[scene_][cls]);
            std::snprintf(s,sizeof(s),"%.1f",parcel_.counts[cls]*gsd*gsd);text(frame_,1536,yy+2,s,2);
            if(parcel_.received)std::snprintf(s,sizeof(s),"%.1f%%",100.0*parcel_.counts[cls]/parcel_.received);else std::snprintf(s,sizeof(s),"--");text(frame_,1718,yy+2,s,2,accent);
            std::snprintf(s,sizeof(s),"%u",parcel_.counts[cls]);text(frame_,1810,yy+2,s,2,MUTED);
        }
        bitmap(frame_,1260,980,labels::PARCEL_SCOPE,MUTED);
        bitmap(frame_,1260,1008,parcel_.local?labels::PARCEL_LOCAL_SOURCE:labels::PARCEL_SOURCE,MUTED);
        std::snprintf(s,sizeof(s),"REV %u / T %.2f",parcel_.revision,double(parcel_.threshold)/65535);text(frame_,1600,1010,s,2,MUTED);
        return;
    }
    bitmap(frame_,1260,368,wcrc_?(kind_==TaskKind::full_scene?labels::AREA_SCAN:labels::AREA_REGION):labels::TASK_WAIT);
    bitmap(frame_,1570,377,labels::AREA_BASIS,MUTED);
    bitmap(frame_,1260,417,labels::AREA_CLASS,MUTED);bitmap(frame_,1536,417,labels::AREA_M2,MUTED);
    bitmap(frame_,1718,417,labels::AREA_SHARE,MUTED);bitmap(frame_,1810,417,labels::AREA_PIXELS,MUTED);
    bitmap(frame_,1260,1008,labels::AREA_TOTAL,MUTED);
    unsigned order[24];for(unsigned i=0;i<classes_;++i)order[i]=i;
    if(state_==ViewState::done||state_==ViewState::stopped||state_==ViewState::failed)
        for(unsigned i=1;i<classes_;++i){unsigned j=i;while(j&&counts_[order[j]]>counts_[order[j-1]]){const unsigned t=order[j];order[j]=order[j-1];order[j-1]=t;--j;}}
    for(unsigned i=0;i<classes_;++i) {
        const unsigned cls=order[i],yy=456+i*24;box(frame_,1260,yy-3,620,23,panel);
        box(frame_,1260,yy,12,12,class_color(cls));bitmap(frame_,1284,yy-3,labels::CLASS_TABLES[scene_][cls]);
        std::snprintf(s,sizeof(s),"%.1f",class_area_m2(cls));text(frame_,1536,yy,s,2);
        if(completed_)std::snprintf(s,sizeof(s),"%.1f%%",100.0*counts_[cls]/completed_);else std::snprintf(s,sizeof(s),"--");text(frame_,1718,yy,s,2,accent);
        std::snprintf(s,sizeof(s),"%u",counts_[cls]);text(frame_,1810,yy,s,2,MUTED);
    }
    box(frame_,1530,1004,350,25,panel);
    const double gsd=double(scene_gsd_mm(scene_))/1000.0;
    std::snprintf(s,sizeof(s),"%.1f",completed_*gsd*gsd);text(frame_,1536,1010,s,2,accent);
    std::snprintf(s,sizeof(s),"%u",completed_);text(frame_,1810,1010,s,2,MUTED);
}
void SceneCanvas::restore_map() {
    for(unsigned y=0;y<map_h_;++y)for(unsigned x=0;x<map_w_;++x){const unsigned cls=map_base_[y*SCENE_MAP_W+x];frame_[(map_y_+y)*DISPLAY_W+map_x_+x]=cls?class_color(cls-1):color(23,35,49);}
    outline();
}
void SceneCanvas::parcel_outline() {
    if(!parcel_selected_)return;
    const uint32_t yellow=color(255,220,60);
    for(unsigned i=0;i<parcel_.points;++i){const unsigned j=(i+1)%parcel_.points;
        int x=int(map_x_+uint64_t(parcel_.xy[i][0])*(map_w_-1)/65535),y=int(map_y_+uint64_t(parcel_.xy[i][1])*(map_h_-1)/65535);
        const int endx=int(map_x_+uint64_t(parcel_.xy[j][0])*(map_w_-1)/65535),endy=int(map_y_+uint64_t(parcel_.xy[j][1])*(map_h_-1)/65535);
        const int dx=std::abs(endx-x),sx=x<endx?1:-1,dy=-std::abs(endy-y),sy=y<endy?1:-1;int error=dx+dy;
        for(;;){box(frame_,unsigned(x),unsigned(y),2,2,yellow);if(x==endx&&y==endy)break;const int e=2*error;if(e>=dy){error+=dy;x+=sx;}if(e<=dx){error+=dx;y+=sy;}}
    }
    const unsigned x=map_x_+uint64_t(parcel_.xy[0][0])*(map_w_-1)/65535,y=map_y_+uint64_t(parcel_.xy[0][1])*(map_h_-1)/65535;
    const unsigned labelx=x+194<map_x_+map_w_?x:map_x_+map_w_>194?map_x_+map_w_-194:map_x_;
    const unsigned labely=y>map_y_+26?y-26:map_y_;
    box(frame_,labelx,labely,192,24,color(3,8,14));const labels::Bitmap name={192,24,parcel_.name_bits};bitmap(frame_,labelx,labely,name,yellow);
}
bool SceneCanvas::parcel(const ParcelView &v,uint64_t now) {
    if(!frame_||v.boot!=boot_||v.session!=session_||v.task!=task_||v.scene!=scene_||v.wcrc!=wcrc_||v.classes!=classes_||v.points>128||
       v.received>v.pixels||v.received>completed_||v.low>v.received||(v.selected&&(!v.pixels||v.points<3)))return false;
    uint64_t sum=0;for(unsigned i=0;i<24;++i){if(i>=classes_&&v.counts[i])return false;sum+=v.counts[i];}if(sum!=v.received)return false;
    restore_marker();parcel_=v;parcel_selected_=v.selected;parcel_at_=now;parcel_age_=0;
    restore_map();parcel_outline();paint_marker();statistics();return parcel_age(now);
}
bool SceneCanvas::parcel_age(uint64_t now) {
    if(!frame_)return false;
    const unsigned age=parcel_selected_&&!parcel_.local?unsigned((now-parcel_at_)/1000000):0;
    parcel_age_=age;box(frame_,470,1018,640,19,BG);
    if(parcel_selected_){bitmap(frame_,470,1018,parcel_.local?labels::PARCEL_LOCAL_LIVE:age>=3?labels::PARCEL_STALE:labels::PARCEL_LIVE,age>=3?color(255,180,70):MUTED);
        if(!parcel_.local){char s[40];std::snprintf(s,sizeof(s),"%u S",age);text(frame_,930,1020,s,2,MUTED);}}
    return true;
}
bool SceneCanvas::temperature(float current,float peak,bool valid) {
    if(!frame_)return false;
    box(frame_,88,910,312,70,color(17,25,35));bitmap(frame_,104,920,labels::CHIP_TEMP,MUTED);
    if(valid&&std::isfinite(current)&&std::isfinite(peak)){char s[40];std::snprintf(s,sizeof(s),"%.1f C",double(current));text(frame_,280,922,s,2,color(45,212,191));bitmap(frame_,104,950,labels::TEMP_PEAK,MUTED);std::snprintf(s,sizeof(s),"%.1f C",double(peak));text(frame_,280,952,s,2);}
    else bitmap(frame_,104,952,labels::TEMP_FAIL,MUTED);
    return true;
}
bool SceneCanvas::power(const PowerView &v) {
    if(!frame_||!std::isfinite(v.watts)||v.watts<=0||!std::isfinite(v.joules)||v.joules<0)return false;
    const uint32_t panel=color(17,25,35),accent=color(45,212,191);char s[80];
    box(frame_,88,410,312,68,panel);bitmap(frame_,104,418,labels::POWER_EST,MUTED);
    std::snprintf(s,sizeof(s),"%.2f W",double(v.watts));text(frame_,264,420,s,2,accent);
    bitmap(frame_,104,448,v.temperature_valid?labels::POWER_MODEL:labels::POWER_FALLBACK,MUTED);
    box(frame_,88,980,312,62,panel);bitmap(frame_,104,984,labels::ENERGY_EST,MUTED);
    // A scene preview/task switch must not label the old task energy as new.
    if(v.task&&v.task==task_)std::snprintf(s,sizeof(s),"T%u  %.2f J",v.task,v.joules);
    else std::snprintf(s,sizeof(s),"-- J");
    text(frame_,104,1008,s,2,accent);return true;
}
bool SceneCanvas::probe(const ProbeView &v) {
    if(!frame_ || v.boot!=boot_ || v.session!=session_ || v.task!=task_ ||
       v.scene!=scene_ || v.wcrc!=wcrc_ || std::memcmp(v.tag,tag_,16) ||
       !v.wcrc || v.row>=scene_height_ || v.col>=scene_width_ ||
       (v.state!=ProbeState::running&&v.state!=ProbeState::done&&v.state!=ProbeState::failed) ||
       (v.state==ProbeState::done&&((v.word&0xff00)||(v.word&255)>=classes_)))return false;
    const uint32_t panel=color(17,25,35),accent=color(45,212,191);
    box(frame_,PROBE_PANEL_X,PROBE_PANEL_Y,PROBE_PANEL_W,PROBE_PANEL_H,panel);
    bitmap(frame_,104,118,labels::PROBE_TITLE,accent);
    char s[64];std::snprintf(s,sizeof(s),"ROW %u  COL %u",v.row,v.col);text(frame_,104,160,s,2,MUTED);
    if(v.state==ProbeState::running)bitmap(frame_,104,208,labels::PROBE_RUNNING,accent);
    else if(v.state==ProbeState::failed){bitmap(frame_,104,208,labels::PROBE_FAILED,color(244,63,94));std::snprintf(s,sizeof(s),"ERROR %d",v.error);text(frame_,104,252,s,2);}
    else {
        box(frame_,104,208,16,16,class_color(v.word&255));bitmap(frame_,132,208,labels::CLASS_TABLES[scene_][v.word&255]);
        bitmap(frame_,104,252,labels::PROBE_CONF,MUTED);std::snprintf(s,sizeof(s),"%.2f%%",double(v.word>>16)*100.0/65536.0);text(frame_,218,254,s,2,accent);
        bitmap(frame_,104,298,v.attention?labels::PROBE_ATTN:labels::PROBE_DONE,MUTED);
    }
    bitmap(frame_,104,350,labels::PROBE_ONLY,MUTED);
    restore_marker();marker_=true;probe_row_=v.row;probe_col_=v.col;paint_marker();return true;
}
bool SceneCanvas::connection(PeerState state,unsigned age_seconds) {
    if(!frame_)return false;
    peer_state_=state;peer_age_=age_seconds;
    return dispatch(dispatch_);
}
bool SceneCanvas::dispatch(const DispatchView &v) {
    if(!frame_||unsigned(v.action)>unsigned(DispatchAction::stop)||unsigned(v.phase)>unsigned(DispatchPhase::selected)||
       (v.source&&v.source!=5&&v.source!=6))return false;
    dispatch_=v;
    const uint32_t panel=color(17,25,35),accent=color(45,212,191);
    // Task ownership, not heartbeat age: a completed task is idle even while
    // its result/probe channel stays open; a local-key task may outlive PC traffic.
    const bool active=v.action!=DispatchAction::none&&
        (v.phase==DispatchPhase::waiting||v.phase==DispatchPhase::received||
         v.phase==DispatchPhase::preparing||v.phase==DispatchPhase::running||v.phase==DispatchPhase::paused);
    const auto &status=!active?labels::COMMAND_IDLE:!v.source?labels::COMMAND_PC:labels::COMMAND_TERMINAL;
    box(frame_,1490,8,410,48,panel);bitmap(frame_,1510,20,status,accent);
    box(frame_,88,650,312,216,panel);bitmap(frame_,104,668,labels::DISPATCH_TITLE,accent);
    const auto &source=v.action==DispatchAction::none?labels::DISPATCH_NONE:!v.source?labels::DISPATCH_PC:
        v.source==5?(v.gesture==1?labels::DISPATCH_K5_ONE:v.gesture==2?labels::DISPATCH_K5_TWO:labels::DISPATCH_K5_HOLD):
        v.gesture==1?labels::DISPATCH_K6_ONE:v.gesture==2?labels::DISPATCH_K6_TWO:labels::DISPATCH_K6_HOLD;
    bitmap(frame_,104,700,source);
    const labels::Bitmap *const actions[]={&labels::DISPATCH_NONE,&labels::DISPATCH_POINT,&labels::DISPATCH_SCAN,
        &labels::DISPATCH_REGION,&labels::DISPATCH_PARCEL,&labels::DISPATCH_SCENE,&labels::DISPATCH_PAUSE,
        &labels::DISPATCH_RESUME,&labels::DISPATCH_STOP};
    bitmap(frame_,104,726,labels::DISPATCH_ACTION,MUTED);bitmap(frame_,164,726,*actions[unsigned(v.action)]);
    const labels::Bitmap *const phases[]={&labels::DISPATCH_WAIT,&labels::DISPATCH_RECEIVED,&labels::DISPATCH_PREP,
        &labels::DISPATCH_RUNNING,&labels::STATE_PAUSED,&labels::DISPATCH_DONE,&labels::STATE_STOPPED,
        &labels::DISPATCH_FAILED,&labels::DISPATCH_SELECTED};
    if(v.action!=DispatchAction::none)bitmap(frame_,104,752,*phases[unsigned(v.phase)],
        v.phase==DispatchPhase::failed?color(255,190,70):accent);
    bitmap(frame_,104,788,labels::KEY_GUIDE5,MUTED);bitmap(frame_,104,812,labels::KEY_GUIDE6,MUTED);
    bitmap(frame_,104,836,labels::KEY_GUIDE_HOLD,MUTED);return true;
}
}
