#ifndef S2_WORKER_H
#define S2_WORKER_H
#include "s2_internal.h"
#include <array>
#include <hls_stream.h>
namespace s2 {
enum CoreKind { CORE_LOAD, CORE_XB, CORE_START, CORE_READ, CORE_RELEASE, CORE_STOP,
                CORE_W12, CORE_W3, CORE_EXP };
struct CoreRequest {
    State<5> kind;State<2> slot;State<6> stage;State<7> pid;
    State<5> a;State<4> b;State<10> c; // a also holds W16 WGROUP index13
    uint64_t word;
    Act value[6];
    CoreRequest():kind(0),slot(0),stage(0),pid(0),a(0),b(0),c(0),word(0) {
        for(int t=0;t<6;t++) value[t]=0;
    }
};
struct CoreResponse {
    State<5> kind;State<2> slot;State<6> stage;
    Act value[6][2];
    CoreResponse():kind(0),slot(0),stage(0) {
        for(int t=0;t<6;t++) for(int k=0;k<2;k++) value[t][k]=0;
    }
};
typedef hls::stream<CoreRequest> CoreRequests;
typedef hls::stream<CoreResponse> CoreResponses;
struct CoreOffer {CoreRequest item;bool valid,ready;};
struct CoreWorker {
    CoreMemory mem;Projection projection;
    bool active,owned;State<2> owner;State<6> stage;State<7> pid;
#ifndef __SYNTHESIS__
    unsigned reads; // assertion instrumentation, not a new hardware counter
#endif
    void reset_session() {active=owned=false;
#ifndef __SYNTHESIS__
        reads=0;
#endif
    }
    bool accept(const CoreRequest &,CoreResponse &);
    bool advance(CoreResponse &);
    void run(CoreResponse &);
};
void core_service(CoreRequests &,CoreResponses &);
// Only the engine reads wmem. Weights travel over the existing command FIFO;
// the worker has no AXI reader and still owns exactly one weight memory.
void core_send_weights(const uint64_t *,CoreRequests &,CoreResponses &);
// Native/CSim executes exactly one worker tick per scheduler iteration. It
// models finite FIFOs, but is not a cycle-accurate RTL timing claim.
void core_sim_begin();
void core_sim_tick(CoreRequests &,CoreResponses &);
bool core_reply_kind(int kind);
}
#endif
