#ifndef S2C_ROI_RESULTS_H
#define S2C_ROI_RESULTS_H
#include <cstdint>
#include <cstring>
#include "roi_models.h"
namespace s2c {
// Four 2-MiB CPU-only task slots (protocol.md section 2.5). Static lifetime;
// never handed to DMA. A fifth healthy START reclaims only the oldest slot.
class ResultStore {
public:
    struct Slot {
        uint32_t session=0,wcrc=0,completed=0;
        uint16_t task=0,x=0,y=0,width=0,height=0,scene_width=400,scene_height=550;
        uint8_t state=0,scene=0,classes=9;
        char tag[16]={};
        uint32_t words[524288];
        unsigned front() const {return y+(width?completed/width:0);}
    };
private:
    Slot slots_[4];unsigned next_=0;
public:
    Slot *find(uint32_t session,uint16_t task) {
        for(auto &s:slots_)if(s.task==task && s.session==session)return &s;
        return nullptr;
    }
    bool begin(uint32_t session,uint16_t task,uint32_t crc,unsigned x,unsigned y,unsigned w,unsigned h,
               unsigned scene=0,const char *tag=nullptr) {
        const auto *spec=scene_contract(scene);
        if(!spec || !task || find(session,task) || x>=spec->width || y>=spec->height || !w || !h ||
           w>spec->width-x || h>spec->height-y || (tag&&std::strlen(tag)>15))return false;
        auto &s=slots_[next_];next_=(next_+1)%4;
        s.session=session;s.task=task;s.wcrc=crc;s.x=x;s.y=y;s.width=w;s.height=h;s.completed=0;s.state=1;
        s.scene=uint8_t(scene);s.classes=spec->classes;s.scene_width=spec->width;s.scene_height=spec->height;
        std::memset(s.tag,0,sizeof(s.tag));if(tag)std::strcpy(s.tag,tag);
        return true; // stale words stay inaccessible behind the committed frontier
    }
    bool append(uint32_t session,uint16_t task,unsigned row,unsigned col,unsigned n,const uint32_t *words) {
        Slot *s=find(session,task);
        if(!s || s->state!=1 || !words || !n || row!=s->y+s->completed/s->width ||
           col!=s->x+s->completed%s->width || row>=s->y+s->height || n>s->x+s->width-col)return false;
        for(unsigned i=0;i<n;++i)if((words[i]&0xff00) || (words[i]&255)>=s->classes)return false;
        for(unsigned i=0;i<n;++i)s->words[row*s->scene_width+col+i]=words[i];
        s->completed+=n;return true;
    }
};
}
#endif
