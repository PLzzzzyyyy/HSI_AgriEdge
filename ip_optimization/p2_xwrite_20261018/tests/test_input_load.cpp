// Exercise the actual IO worker, including row/bank/slot boundaries and
// saturation. No synthesized source is changed for this host-only test.
#include "../src/hls/m3_s2/s2_engine.cpp"
#include <algorithm>
#include <cstring>
#include <cmath>
#include <climits>
int main(){
    using namespace s2;
    static MainMemory memory;
    static Bank expected;
    const int32_t raw_values[]={INT_MIN,-131073,-131072,-129,-128,-127,-1,0,1,127,128,131071,131072,INT_MAX};
    const int32_t packed_values[]={-32768,-32767,-257,-256,-129,-128,-127,-1,0,1,127,128,129,255,256,32767};
    unsigned cases=0;
    for(int sl=0;sl<S2_P;++sl)for(int raw=0;raw<2;++raw)
    for(int first=0;first<6;++first)for(int position:{0,1,2,3,4,2644,2645})
    for(int seed=0;seed<(raw?14:16);++seed){
        std::fill(&memory.x[0][0][0],&memory.x[0][0][0]+sizeof(Bank)/sizeof(Act),Act(37));
        std::memcpy(expected,memory.x,sizeof(Bank));
        const int lanes=raw?2:4;
        uint64_t word=0;int64_t want_sum[6]={};uint64_t want_square[6]={};
        for(int k=0;k<lanes;++k){
            int32_t v=raw?raw_values[(seed+k)%14]:packed_values[(seed+k)%16];
            if(raw)word|=uint64_t(uint32_t(v))<<(32*k);
            else word|=uint64_t(uint16_t(v))<<(16*k);
            if(!raw && S2_NUM==8)v=int32_t(std::floor((double(v)+128.0)/256.0));
            const int32_t limit=1<<(S2_DB-1);
            v=std::max(-limit,std::min(limit-1,v));
            const int linear=position*6+first+k,p=linear/6,t=linear%6;
            expected[t][p%4][sl*662+p/4]=Act(v);
            want_sum[t]+=v;want_square[t]+=uint64_t(int64_t(v)*v);
        }
        Slot slot={};slot.id=0;
        Job job={};job.slot=sl;job.stage=IO_LOAD;job.a=position;job.t=first;
        StatsDelta delta={};uint64_t logits=0,features=0;uint32_t cls=0;
        XWrites writes={},none={};
        S2_ASSERT(!io_step(memory,slot,job,&word,&logits,&cls,&features,1,raw?S2_RAW:0,0,delta,writes));
        commit_xwrites(memory,none,none,writes);
        S2_ASSERT(std::memcmp(expected,memory.x,sizeof(Bank))==0);
        const int end=position*6+first+lanes;
        S2_ASSERT(job.a==end/6 && job.t==end%6 && job.p==1);
        S2_ASSERT(delta.valid && delta.slot==sl);
        for(int t=0;t<6;++t){S2_ASSERT(delta.sum[t]==want_sum[t]);S2_ASSERT(delta.square[t]==want_square[t]);}
        S2_ASSERT(logits==0 && features==0 && cls==0);++cases;
    }
    unsigned port_cases=0;
    for(int t=0;t<6;++t)for(int bank=0;bank<4;++bank)for(int mask=0;mask<7;++mask){
        std::fill(&memory.x[0][0][0],&memory.x[0][0][0]+sizeof(Bank)/sizeof(Act),Act(37));
        std::memcpy(expected,memory.x,sizeof(Bank));
        XWrites context={},residual={},input={};XWrite *requests[]={&context[t][bank],&residual[t][bank],&input[t][bank]};
        for(int producer=0;producer<3;++producer)if(mask&(1<<producer)){
            XWrite &r=*requests[producer];r.valid=true;r.address=producer;r.value=Act(producer+11);
            expected[t][bank][producer]=Act(producer+11);
        }
        commit_xwrites(memory,context,residual,input);
        S2_ASSERT(std::memcmp(expected,memory.x,sizeof(Bank))==0);++port_cases;
    }
    std::printf("INPUT_LOAD_BOUNDARY_PASS cases=%u two_port_cases=%u num=%d P=%d\n",cases,port_cases,S2_NUM,S2_P);
}
