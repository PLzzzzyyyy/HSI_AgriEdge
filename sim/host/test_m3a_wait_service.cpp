// Real driver, instrumented register/cache stubs. No board/HLS inference.
// One process per fault lifetime, preserving the driver's no-reset contract.
#include "tt_m3a.h"
#include "xtt_engine.h"
#include "xil_cache.h"
#include "roi_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>

static bool dma_busy=false,never_done=false;
static unsigned starts=0,setters=0,flushes=0,invalidates=0,polls=0,callbacks=0;
static unsigned completion=8;
static uint32_t result=(18u<<24)|(12u<<16)|(TT_ENGINE_VERSION<<8);
static void idle(){assert(!dma_busy);}
int XTt_engine_Initialize(XTt_engine *,int){idle();return XST_SUCCESS;}
void XTt_engine_Start(XTt_engine *){idle();dma_busy=true;polls=0;++starts;}
u32 XTt_engine_IsDone(XTt_engine *){
    assert(dma_busy);++polls;
    if(never_done || polls<completion)return 0;
    dma_busy=false;return 1;
}
u32 XTt_engine_Get_return(XTt_engine *){idle();return result;}
u32 XTt_engine_Get_cycles(XTt_engine *) { return 12345; } // OFFLINE SYNTHETIC CLOCK
#define SET(name) void XTt_engine_Set_##name(XTt_engine *,u32){idle();++setters;}
SET(x_in) SET(cube) SET(x_out) SET(q_out) SET(k_out) SET(v_out) SET(stats_out) SET(w_ddr)
SET(cube_w) SET(seg_row) SET(seg_col) SET(n_patch) SET(layer_lo) SET(layer_hi) SET(proj_mask) SET(mode)
void Xil_DCacheFlush(){assert(false);}
void Xil_DCacheFlushRange(INTPTR,u32){idle();++flushes;}
void Xil_DCacheInvalidateRange(INTPTR,u32){idle();++invalidates;}
alignas(64) static unsigned char weights[TT_ENGINE_WPKG16_BYTES];
alignas(64) static int16_t input[TT_ENGINE_IN_STRIDE/2];
alignas(64) static unsigned char output[128];
static TTM3aJob job={input,sizeof(input),output,sizeof(output),1,0,11,TT_ENGINE_OUT_LOGITS,false};
static int context=123;
static s2c::Protocol protocol(0x12345678);
static s2c::Peer peer{0x0101a8c0,5011};
static void p16(uint8_t *p,unsigned n){p[0]=uint8_t(n);p[1]=uint8_t(n>>8);}
static void p32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=uint8_t(n>>(8*i));}

static void service(void *opaque){
    assert(opaque==&context&&dma_busy);++callbacks;
    const unsigned s=starts,r=setters,f=flushes,i=invalidates;
    // Receive callbacks must never acquire a second engine/cache owner.
    assert(tt_m3a_init()==TT_M3A_BUSY);
    assert(tt_m3a_load_weights(weights,sizeof(weights),10)==TT_M3A_BUSY);
    assert(tt_m3a_run(job,10)==TT_M3A_BUSY);
    assert(tt_m3a_set_wait_service(nullptr,nullptr)==TT_M3A_BUSY);
    assert(s==starts&&r==setters&&f==flushes&&i==invalidates);
    // Real protocol inside the real driver's wait: PING/STATUS are CPU-only,
    // PROBE while the scene is running is rejected rather than reentering PL.
    uint8_t b[24]{};p16(b,0x4548);b[2]=5;b[3]=1;p16(b+4,7);p16(b+6,callbacks+1);p32(b+12,42);
    s2c::Packet reply;
    assert(protocol.receive(b,16,peer,callbacks*1000,reply)&&reply.bytes[2]==0x84);
    b[2]=9;p32(b+12,0);p32(b+20,s2c::WCRC);
    assert(protocol.receive(b,24,peer,callbacks*1000+1,reply)&&reply.bytes[12]==9&&reply.bytes[13]==9);
    unsigned row,col;uint16_t seq;assert(!protocol.take_probe(row,col,seq)&&!protocol.take_job());
    if(protocol.status(callbacks*1000+2,reply))assert(reply.bytes[32]==1);
    assert(s==starts&&r==setters&&f==flushes&&i==invalidates);
}

int main(int argc,char **argv){
    assert(argc==2);const char *mode=argv[1];
    assert((uintptr_t)weights<UINT64_C(0x100000000));
    uint32_t header[]={TT_ENGINE_WPKG_MAGIC,2,9,16};std::memcpy(weights,header,sizeof(header));
    assert(tt_m3a_init()==0);
    uint8_t b[32]{};p16(b,0x4548);b[2]=5;b[3]=1;p32(b+12,42);s2c::Packet reply;
    assert(protocol.receive(b,16,peer,0,reply));b[2]=1;p16(b+4,7);p16(b+6,1);std::memset(b+12,0,20);
    p16(b+20,550);p16(b+22,400);p32(b+24,s2c::WCRC);p32(b+28,42);
    assert(protocol.receive(b,32,peer,1,reply)&&reply.bytes[13]==0&&protocol.take_job());
    if(std::strcmp(mode,"disabled")==0){
        assert(tt_m3a_load_weights(weights,sizeof(weights),10)==0&&callbacks==0);
        assert(tt_m3a_run(job,10)==0&&callbacks==0&&invalidates==1);
    }else{
        assert(tt_m3a_set_wait_service(service,&context,0)==TT_M3A_ARGUMENT);
        assert(tt_m3a_set_wait_service(nullptr,&context,2)==TT_M3A_ARGUMENT);
        assert(tt_m3a_set_wait_service(service,&context,2)==0);
        assert(tt_m3a_load_weights(weights,sizeof(weights),10)==0&&callbacks==3);
        callbacks=0;
        if(std::strcmp(mode,"timeout")==0 || std::strcmp(mode,"contract")==0){
            never_done=std::strcmp(mode,"timeout")==0;
            if(!never_done)result=0;
            assert(tt_m3a_run(job,10)==(never_done?TT_M3A_TIMEOUT:TT_M3A_CONTRACT));
            assert(callbacks==(never_done?5u:3u));
            if(never_done)assert(invalidates==0); // Never touch pending DMA output.
            const unsigned c=callbacks,s=starts,r=setters,f=flushes,i=invalidates;
            assert(tt_m3a_run(job,10)==TT_M3A_RESET_REQUIRED);
            assert(tt_m3a_load_weights(weights,sizeof(weights),10)==TT_M3A_RESET_REQUIRED);
            assert(tt_m3a_init()==TT_M3A_RESET_REQUIRED);
            assert(tt_m3a_set_wait_service(nullptr,nullptr)==TT_M3A_RESET_REQUIRED);
            assert(c==callbacks&&s==starts&&r==setters&&f==flushes&&i==invalidates);
        }else if(std::strcmp(mode,"immediate")==0){
            completion=1;assert(tt_m3a_run(job,10)==0&&callbacks==0&&invalidates==1);
        }else{
            assert(tt_m3a_run(job,10)==0&&callbacks==3&&invalidates==1);
            assert(tt_m3a_set_wait_service(nullptr,nullptr)==0);
            assert(tt_m3a_run(job,10)==0&&callbacks==3&&invalidates==2);
        }
    }
    std::printf("PASS wait service %s: real driver, no register/cache reentry, no board claims\n",mode);
}
