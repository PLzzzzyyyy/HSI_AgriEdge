#include "roi_keys.h"
#include <cassert>
#include <vector>
struct Sim {
    s2c::Keys keys;uint64_t t=0;std::vector<s2c::KeyEvent> events;
    void step(unsigned ms,bool a=false,bool b=false){
        for(unsigned i=0;i<ms;i+=5,t+=5000){const auto e=keys.poll(t,a,b);if(e.key)events.push_back(e);}
    }
    Sim(){step(50);}
};
int main(){
    {Sim s;s.step(80,true);s.step(300);assert(s.events.empty());s.step(100);assert(s.events.size()==1&&s.events[0].key==5&&s.events[0].gesture==1);}
    {Sim s;s.step(70,true);s.step(120);s.step(70,true);s.step(400);assert(s.events.size()==1&&s.events[0].gesture==2);}
    {Sim s;s.step(5,true);s.step(5);s.step(10,true);s.step(500);assert(s.events.empty());}
    {Sim s;s.step(1995,true);assert(s.events.empty());s.step(100,true);assert(s.events.size()==1&&s.events[0].gesture==3);s.step(5000,true);s.step(500);assert(s.events.size()==1);}
    {Sim s;s.step(1990,true);s.step(500);assert(s.events.size()==1&&s.events[0].gesture==1);}
    {Sim s;s.step(70,true);s.step(120);s.step(2200,true);s.step(500);assert(s.events.size()==1&&s.events[0].gesture==3);}
    {Sim s;for(unsigned i=0;i<3;++i){s.step(70,false,true);s.step(100);}s.step(500);assert(s.events.empty());}
    {Sim s;s.step(2200,true,true);s.step(500);assert(s.events.empty());s.step(80,false,true);s.step(400);assert(s.events.size()==1&&s.events[0].key==6&&s.events[0].gesture==1);}
    {s2c::Keys keys;std::vector<s2c::KeyEvent> events;for(uint64_t t=0;t<3000000;t+=5000){auto e=keys.poll(t,true,false);if(e.key)events.push_back(e);}assert(events.empty());}
}
