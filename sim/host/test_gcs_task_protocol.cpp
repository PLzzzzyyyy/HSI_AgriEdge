#include "roi_protocol.h"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <cmath>
static void p16(uint8_t*p,unsigned v){p[0]=v;p[1]=v>>8;}
static void p32(uint8_t*p,unsigned v){for(unsigned i=0;i<4;++i)p[i]=v>>(8*i);}
static void head(uint8_t*b,unsigned type,unsigned task,unsigned seq){std::memset(b,0,32);p16(b,0x4548);b[2]=type;b[3]=1;p16(b+4,task);p16(b+6,seq);}
int main(){
 s2c::Protocol p(0x12345678,true);s2c::Peer peer{1,2};s2c::Packet out;uint8_t b[32];
 head(b,5,0,0);p32(b+12,99);assert(p.receive(b,16,peer,1,out));
 head(b,1,7,1);b[12]=1;p16(b+16,548);p16(b+18,395);p16(b+20,2);p16(b+22,5);p32(b+24,s2c::WCRC);p32(b+28,99);
 assert(p.receive(b,32,peer,2,out)&&!out.bytes[13]);assert(p.x()==395&&p.y()==548&&p.total()==10);assert(p.take_job());
 // INFO cannot steal the live peer; same-session rebind requires timeout.
 uint8_t info[32];head(info,7,0,9);s2c::Peer replacement{1,3};
 assert(p.receive(info,12,replacement,3,out)&&out.bytes[2]==0x86);
 assert(out.size==60&&out.to.port==3&&out.bytes[16]==1&&out.bytes[17]==4&&out.bytes[18]==16);
 for(unsigned i=44;i<60;++i)assert(out.bytes[i]==0); // unbound offline fixture, live App refuses it
 assert(out.bytes[20]==99&&out.bytes[24]==7&&out.bytes[42]==1);
 head(info,5,7,10);p32(info+12,99);
 assert(!p.receive(info,16,replacement,4,out));
 uint8_t start[32];std::memcpy(start,b,32);
 head(b,3,7,2);assert(p.receive(b,12,peer,3,out)&&!out.bytes[13]);assert(!p.paused());
 assert(p.progress(4));assert(!p.apply_control(4,out));assert(p.progress(5));
 assert(p.record_compute(25000,5));assert(p.compute_ms_per_pixel()==5.0f);
 assert(!p.record_compute(24000,5));assert(!p.record_compute(25000,4));
 assert(p.apply_control(5,out));
 assert(p.paused()&&out.bytes[12]==3&&out.bytes[14]==2&&out.bytes[16]==(549&255));
 assert(p.status(5,out));float timing=0;std::memcpy(&timing,out.bytes+20,4);assert(timing==5.0f);
 head(b,4,6,3);assert(p.receive(b,12,peer,6,out)&&out.bytes[13]==9);assert(p.paused());
 head(b,4,7,4);assert(p.receive(b,12,peer,7,out)&&!out.bytes[13]);assert(p.apply_control(8,out)&&!p.paused());
 // Delayed older PAUSE never reverses the acknowledged RESUME.
 head(b,3,7,2);assert(p.receive(b,12,peer,9,out)&&out.bytes[13]!=0);assert(!p.paused());
 // PROBE during a task queues only; repeated in-flight owner is not replaced.
 head(b,9,7,5);p16(b+14,549);p16(b+16,399);p32(b+20,s2c::WCRC);
 assert(!p.receive(b,24,peer,10,out));unsigned row,col;uint16_t seq;assert(p.take_probe(row,col,seq)&&row==549&&col==399);
 p16(b+6,6);assert(p.receive(b,24,peer,11,out)&&out.bytes[13]!=0);
 int32_t logits[9]={};p.probe_reply(0xffff0001,logits,12,out);
 head(b,2,7,7);assert(p.receive(b,12,peer,13,out)&&!out.bytes[13]);assert(p.apply_control(14,out)&&p.stopped());
 // Same START remains idempotent even after STOP, and cannot clear progress.
 assert(p.receive(start,32,peer,15,out)&&!out.bytes[13]);assert(!p.take_job()&&p.stopped());
 p16(start+4,8);p16(start+6,8);assert(p.receive(start,32,peer,16,out)&&!out.bytes[13]);assert(p.take_job()&&!p.stopped());
 assert(std::isnan(p.compute_ms_per_pixel()));assert(p.status(16,out));std::memcpy(&timing,out.bytes+20,4);assert(std::isnan(timing));
 // Old task cannot be brought back by delayed START/control.
 p16(start+4,7);assert(p.receive(start,32,peer,17,out)&&out.bytes[13]==9);
 assert(p.progress(10)&&p.finish(10));
 p.failure(-1,18,out);p16(start+4,9);p16(start+6,9);assert(p.receive(start,32,peer,19,out)&&out.bytes[13]!=0);
 std::puts("task protocol PASS: ROI / boundary controls / stale commands / new task / fault latch");
 static s2c::ResultStore store;static s2c::Protocol q(0x12345678,true,&store);
 head(b,5,0,0);p32(b+12,99);assert(q.receive(b,16,peer,1,out));
 for(unsigned task=1;task<=5;++task) {
   head(b,1,task,task*10);b[12]=1;p16(b+16,549);p16(b+18,399);p16(b+20,1);p16(b+22,1);p32(b+24,s2c::WCRC);p32(b+28,99);
   assert(q.receive(b,32,peer,task*100,out)&&!out.bytes[13]);assert(q.take_job());
   assert(!q.progress(1));uint32_t word=0x80000000|task;
   assert(store.append(99,task,549,399,1,&word));assert(q.progress(1));assert(q.finish(1));
 }
 assert(!store.find(99,1));assert(store.find(99,2)->words[549*400+399]==0x80000002);
 head(b,6,2,60);p16(b+12,1);p16(b+16,549);p16(b+18,1);
 assert(q.receive(b,20,peer,601,out)&&out.bytes[12]==6&&!out.bytes[13]&&out.bytes[16]==1);
 assert(q.replay(602,out)&&out.bytes[4]==2&&out.bytes[18]==1&&out.bytes[20]==2);
 assert(!q.replay(603,out));
 p16(b+4,1);assert(q.receive(b,20,peer,604,out)&&out.bytes[13]==7);
 p16(b+4,2);p16(b+18,2);assert(q.receive(b,20,peer,605,out)&&out.bytes[13]==8);
 std::puts("result slots PASS: 4-slot retention / fifth reclamation / old-task replay / frontier guard");
 head(info,7,0,80);assert(q.receive(info,12,replacement,1000700,out)&&out.bytes[42]==3);
 head(info,5,5,81);p32(info+12,98);assert(!q.receive(info,16,replacement,1000701,out));
 p32(info+12,99);assert(q.receive(info,16,replacement,1000702,out)&&out.bytes[2]==0x84);
 assert(!q.receive(info,16,peer,1000703,out));
 q.failure(-12,1000704,out);head(info,7,0,82);
 assert(q.receive(info,12,replacement,1000705,out)&&out.bytes[2]==0x83&&out.bytes[12]==7&&out.bytes[13]==6);
 std::puts("INFO/rebind PASS: read-only query / offline same-session migration / fault latch");
}
