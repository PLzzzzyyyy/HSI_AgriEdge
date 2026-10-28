#ifndef S2C_ROI_KEYS_H
#define S2C_ROI_KEYS_H
#include <cstdint>
#include <cmath>
#include "roi_models.h"
#include "roi_canvas.h"
namespace s2c {
// Pure time-based recognizer. No sleeps, GPIO, networking or inference here.
struct KeyEvent { unsigned key=0,gesture=0; }; // gesture: 1 single, 2 double, 3 hold
class Keys {
    struct Button {
        bool raw=false,down=false,armed=false,held=false;
        unsigned clicks=0;uint64_t changed=0,pressed=0,released=0;
        void cancel(){clicks=0;held=true;armed=false;}
        KeyEvent step(uint64_t now,bool input,unsigned key) {
            if(input!=raw){raw=input;changed=now;}
            if(raw!=down&&now-changed>=25000) {
                down=raw;
                if(down){pressed=changed;held=false;}
                else {
                    if(armed&&!held)++clicks;
                    armed=true;released=now;
                }
            }
            if(!down&&!raw&&!armed&&now-changed>=25000)armed=true;
            if(armed&&down&&raw&&!held&&now-pressed>=2000000) {
                held=true;clicks=0;return {key,3};
            }
            if(armed&&!down&&!raw&&clicks&&now-released>=350000) {
                const unsigned n=clicks;clicks=0;
                return n<=2?KeyEvent{key,n}:KeyEvent{};
            }
            return {};
        }
    } buttons_[2];
    bool chord_=false;uint64_t last_=0;
public:
    KeyEvent poll(uint64_t now,bool key5,bool key6) {
        if(last_&&now-last_<5000)return {};
        last_=now;
        if(key5&&key6){chord_=true;buttons_[0].cancel();buttons_[1].cancel();}
        if(chord_) {
            (void)buttons_[0].step(now,key5,5);(void)buttons_[1].step(now,key6,6);
            buttons_[0].clicks=buttons_[1].clicks=0;
            if(!key5&&!key6&&!buttons_[0].down&&!buttons_[1].down)chord_=false;
            return {};
        }
        const KeyEvent a=buttons_[0].step(now,key5,5),b=buttons_[1].step(now,key6,6);
        return a.key?a:b;
    }
};

// Board-only plan generator: no PC, truth labels, sleeps or alternate inference.
struct LocalKeyPlan {
    DispatchAction action=DispatchAction::none;
    unsigned scene=0,x=0,y=0,width=1,height=1,points=0;
    double xy[5][2]={};
    bool contains(unsigned row,unsigned col) const {
        bool inside=false;const double x0=col+.5,y0=row+.5;
        for(unsigned i=0,j=points?points-1:0;i<points;j=i++) {
            const double ax=xy[i][0],ay=xy[i][1],bx=xy[j][0],by=xy[j][1];
            if((ay>y0)!=(by>y0) && x0<(bx-ax)*(y0-ay)/(by-ay)+ax)inside=!inside;
        }
        return inside;
    }
};
inline const ModelEntry *default_key_model(const Models &models,unsigned scene) {
    // V2 is the documented LongKou self-trained pair, never a cross-scene fallback.
    const auto *v2=scene==0?models.find(0,1,0x27231983u):nullptr;
    if(scene==0)return v2&&models.companion(*v2)?v2:nullptr;
    const auto *active=models.active();
    if(active&&active->key.scene==scene&&models.companion(*active))return active;
    for(unsigned i=0;i<models.count();++i){const auto *e=models.entry(i);
        if(e->key.scene==scene&&e->key.kind==1&&models.companion(*e))return e;}
    return nullptr;
}
inline bool make_local_key_plan(unsigned key,unsigned gesture,unsigned scene,uint32_t seed,LocalKeyPlan &p) {
    const auto *s=scene_contract(scene);if(!s||(key!=5&&key!=6)||gesture<1||gesture>3)return false;
    p=LocalKeyPlan{};p.scene=scene;
    uint32_t random=seed?seed:0x6d2b79f5u;
    auto next=[&](){random^=random<<13;random^=random>>17;random^=random<<5;return random;};
    auto pick=[&](unsigned lo,unsigned hi){return lo+next()%(hi-lo+1);};
    if(gesture==3){p.action=DispatchAction::scene;return true;}
    if(key==5&&gesture==1){p.action=DispatchAction::point;p.x=pick(0,s->width-1);p.y=pick(0,s->height-1);return true;}
    if(key==5){p.action=DispatchAction::scan;p.width=s->width;p.height=s->height;return true;}
    p.action=gesture==1?DispatchAction::region:DispatchAction::parcel;
    const unsigned mm=scene==0?463:scene==1?43:109;
    unsigned cap=unsigned(6000000000ULL/(mm*mm));if(cap>4096)cap=4096;
    const unsigned maxw=s->width<128?s->width:128;
    p.width=pick(16,maxw);unsigned maxh=cap/p.width;if(maxh>s->height)maxh=s->height;
    p.height=pick(16,maxh);p.x=pick(0,s->width-p.width);p.y=pick(0,s->height-p.height);
    if(p.action==DispatchAction::parcel) {
        p.points=pick(3,5);const double rotation=(next()/4294967296.0)*6.283185307179586;
        double minx=s->width,miny=s->height,maxx=0,maxy=0;
        for(unsigned i=0;i<p.points;++i){const double a=rotation+6.283185307179586*i/p.points;
            const double x=p.x+p.width/2.0+(p.width/2.0-.5)*std::cos(a);
            const double y=p.y+p.height/2.0+(p.height/2.0-.5)*std::sin(a);
            p.xy[i][0]=x;p.xy[i][1]=y;
            if(x<minx)minx=x;
            if(x>maxx)maxx=x;
            if(y<miny)miny=y;
            if(y>maxy)maxy=y;
        }
        p.x=unsigned(std::floor(minx));p.y=unsigned(std::floor(miny));
        p.width=unsigned(std::ceil(maxx))-p.x;p.height=unsigned(std::ceil(maxy))-p.y;
    }
    return true;
}
}
#endif
