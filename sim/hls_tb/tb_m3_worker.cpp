#include "../../src/hls/m3_s2/s2_worker.h"
#include <cstring>
using namespace s2;
static CoreWorker worker;
static void check(bool x) { S2_ASSERT(x); }
int main(int argc,char **argv) {
    worker.reset_session();
    for(int p=0;p<48;p++) for(int k=0;k<3;k++) worker.mem.exponent[p][k]=S2_NUM==16?14:0;
    CoreRequest r={};CoreResponse y={};
    // Weight FIFO endpoint decoding, including W16 group13 and signed data.
    r.kind=CORE_W12;r.pid=47;r.c=97;r.word=uint64_t(int64_t(-123));
    check(!worker.accept(r,y));check(worker.mem.wm12[97][47]==-123);
    r.kind=CORE_W3;r.a=WGROUP-1;r.c=53;r.word=UINT64_C(0xfedcba9876543210);
    check(!worker.accept(r,y));check(worker.mem.wm3[WGROUP-1][2591]==r.word);
    worker.mem.wm12[97][47]=0;worker.mem.wm3[WGROUP-1][2591]=0;
    r={};
    r.kind=CORE_START;r.slot=0;r.stage=Q;r.pid=47;
    check(!worker.accept(r,y));check(worker.active && worker.owned);
    if(argc>1 && !strcmp(argv[1],"duplicate")) {worker.accept(r,y);return 1;}
    if(argc>1 && !strcmp(argv[1],"early_read")) {r.kind=CORE_READ;r.stage=CQ;worker.accept(r,y);return 1;}
    unsigned ticks=0;while(!worker.advance(y)) {check(worker.owned);check(++ticks<10000);}
    check(y.kind==CORE_START && y.stage==Q && !worker.active && worker.owned);
    for(int t=0;t<6;t++) for(int a=0;a<2;a++) for(int b=0;b<7;b++) for(int c=0;c<216;c++)
        worker.mem.ob[t][a][b][c]=Act((t*17+a*19+b*23+c*7)%101-50);
    r.kind=CORE_READ;r.stage=CQ;
    if(argc>1 && !strcmp(argv[1],"wrong_owner")) {r.slot=1;worker.accept(r,y);return 1;}
    if(argc>1 && !strcmp(argv[1],"early_release")) {r.kind=CORE_RELEASE;worker.accept(r,y);return 1;}
    unsigned checks=0;
    for(int p=0;p<2646;p+=2) {
        r.a=p/378;r.b=(p/54)%7;r.c=(p/378/2)*54+p%54;
        check(worker.accept(r,y));check(y.kind==CORE_READ && y.stage==CQ);
        for(int t=0;t<6;t++) for(int lane=0;lane<2;lane++) {
            check(y.value[t][lane]==worker.mem.ob[t][int(r.a)&1][r.b][int(r.c)+lane]);checks++;
        }
        check(worker.owned);
    }
    r.kind=CORE_RELEASE;check(!worker.accept(r,y));check(!worker.owned);
    // Finite response FIFO backpressure: no request is accepted while full;
    // the final response is retained and never duplicated on an empty input.
    CoreRequests requests;CoreResponses responses;core_sim_begin();
    CoreResponse sentinel={};sentinel.kind=CORE_LOAD;
    responses.write(sentinel);responses.write(sentinel);
    r={};r.kind=CORE_START;r.slot=0;r.stage=Q;r.pid=0;requests.write(r);
    for(int n=0;n<80;n++) core_sim_tick(requests,responses);
    check(requests.size()==1 && responses.size()==2);
    responses.read();responses.read();core_sim_tick(requests,responses);
    check(requests.empty());
    responses.write(sentinel);responses.write(sentinel);
    for(int n=0;n<80;n++) core_sim_tick(requests,responses);
    check(responses.size()==2);responses.read();responses.read();
    unsigned wait=0;while(responses.empty()) {core_sim_tick(requests,responses);check(++wait<10000);}
    check(wait==ticks+1); // stalled ticks did not advance projection
    for(int n=0;n<80;n++) core_sim_tick(requests,responses);
    check(responses.size()==1);check(responses.read().kind==CORE_START);
    r.kind=CORE_STOP;requests.write(r);core_sim_tick(requests,responses);
    check(requests.empty() && responses.empty());
    r.kind=CORE_START;r.stage=M;r.pid=3;check(!worker.accept(r,y));
    while(!worker.advance(y)) {}
    r.kind=CORE_READ;r.stage=R;
    for(int p=0;p<2646;p++) {r.a=p/378;r.b=(p/54)%7;r.c=(p/378/2)*54+p%54;check(worker.accept(r,y));check(worker.owned);}
    r.kind=CORE_RELEASE;check(!worker.accept(r,y));check(!worker.owned);
    // Also execute the exact synthesis service/run entry in sequential C.
    // Preloaded test streams are unbounded here; the finite test is above.
    CoreRequests service_in;CoreResponses service_out;
    for(int pid=0;pid<48;pid++) {
        for(int k=0;k<3;k++) {r={};r.kind=CORE_EXP;r.pid=pid;r.c=k;r.word=S2_NUM==16?14:0;service_in.write(r);}
        for(int e=0;e<98;e++) {r={};r.kind=CORE_W12;r.pid=pid;r.c=e;service_in.write(r);}
        for(int g=0;g<WGROUP;g++) for(int j=0;j<54;j++) {r={};r.kind=CORE_W3;r.pid=pid;r.a=g;r.c=j;service_in.write(r);}
    }
    r={};r.kind=CORE_LOAD;service_in.write(r);
    r.kind=CORE_START;r.stage=Q;service_in.write(r);
    r.kind=CORE_READ;r.stage=CQ;
    for(int p=0;p<2646;p+=2) {r.a=p/378;r.b=(p/54)%7;r.c=(p/378/2)*54+p%54;service_in.write(r);}
    r.kind=CORE_RELEASE;service_in.write(r);r.kind=CORE_STOP;service_in.write(r);
    core_service(service_in,service_out);
    check(service_in.empty() && service_out.size()==1325);
    check(service_out.read().kind==CORE_LOAD);check(service_out.read().kind==CORE_START);
    for(int p=0;p<1323;p++) {CoreResponse z=service_out.read();check(z.kind==CORE_READ);for(int t=0;t<6;t++) for(int k=0;k<2;k++) check(z.value[t][k]==0);}
    check(service_out.empty());
    printf("M3_WORKER_PASS checks=%u projection_ticks=%u W%d service_responses=1325\n",checks,ticks,S2_NUM);
}
