#ifndef M3_STATE_MICRO_H
#define M3_STATE_MICRO_H
#include "s2_internal.h"
#ifndef M3_STATE_OLD
#define M3_STATE_OLD 0
#endif
// Reference is wide only inside this isolated probe, never in the engine.
#if M3_STATE_OLD
#define STATE_TYPE(T) int
#else
#define STATE_TYPE(T) T
#endif
#define STATE_FIELDS(X) \
 X(0,slot,decltype(s2::Job::slot),0,1,2) \
 X(1,stage,decltype(s2::Job::stage),0,16,6) \
 X(2,phase,decltype(s2::Job::phase),0,4002,13) \
 X(3,p,decltype(s2::Job::p),0,7938,14) \
 X(4,t,decltype(s2::Job::t),0,662,11) \
 X(5,a,decltype(s2::Job::a),0,2646,13) \
 X(6,b,decltype(s2::Job::b),0,378,10) \
 X(7,c,decltype(s2::Job::c),0,54,7) \
 X(8,h,decltype(s2::Job::h),0,6,4) \
 X(9,i,decltype(s2::Job::i),0,662,11) \
 X(10,dp,decltype(s2::Job::dp),0,2645,13) \
 X(11,id,decltype(s2::Slot::id),0,63,7) \
 X(12,layer,decltype(s2::Slot::layer),0,11,5) \
 X(13,done,decltype(s2::Slot::done),0,16383,15) \
 X(14,kv_kind,decltype(s2::Slot::kv_kind),-1,6,4) \
 X(15,tok1,decltype(s2::Projection::tok1),-1,5,4) \
 X(16,tok2,decltype(s2::Projection::tok2),-1,5,4) \
 X(17,tok3,decltype(s2::Projection::tok3),-1,5,4) \
 X(18,next,decltype(s2::Projection::next),0,6,4) \
 X(19,g3,decltype(s2::Projection::g3),0,7,4) \
 X(20,j3,decltype(s2::Projection::j3),0,54,7) \
 X(21,flush3,decltype(s2::Projection::flush3),0,1,2) \
 X(22,pending_a,decltype(s2::Projection::pending_a),0,6,4) \
 X(23,tag1_0,s2::State<4>,-3,5,4) \
 X(24,tag1_1,s2::State<4>,-3,5,4) \
 X(25,tag2_0,s2::State<4>,-3,5,4) \
 X(26,tag2_1,s2::State<4>,-3,5,4)
enum { STATE_COUNT=27 };
void m3_state_micro(const int input[STATE_COUNT], unsigned seed, int output[STATE_COUNT], unsigned trace[STATE_COUNT]);
#endif
