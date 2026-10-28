// Independent S2c business App; never launched over a running S2b/ROI App.
#include "roi_boot_id.h"
#include "roi_release.h"
#include "roi_protocol.h"
#include "roi_board_log.h"
#include "roi_runtime.h"
#include "roi_model_sd.h"
#include "roi_timing.h"
#include "roi_display.h"
#include "xparameters.h"
#include "xscugic.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xuartps_hw.h"
#include "xsysmonpsu.h"
#include "xgpiops.h"
#include "roi_keys.h"
#include "roi_labels.h"
#include <cmath>
#include "xtime_l.h"
#include "lwip/init.h"
#include "lwip/udp.h"
#include "lwip/etharp.h"
#include "lwip/ip4_frag.h"
#include "lwip/priv/tcp_priv.h"
#include "netif/xadapter.h"
#include <cstdio>
#include <cstring>
#if !defined(__aarch64__)
#error S2c requires the existing AArch64 standalone domain
#endif
#if !NO_SYS || !NO_SYS_NO_TIMERS || LWIP_TIMERS || !LWIP_IPV4 || !LWIP_UDP
#error Reuse the audited raw IPv4 BSP and single main-loop timer owner
#endif
#if LWIP_DHCP || LWIP_AUTOIP || LWIP_IGMP || LWIP_DNS || LWIP_IPV6 || !CONFIG_LINKSPEED1000
#error Do not change BSP features for this minimal integration
#endif
static_assert(XPAR_XEMACPS_0_BASEADDR==0xFF0E0000U,"Expected GEM3");
static_assert(STDOUT_BASEADDRESS==XPAR_XUARTPS_0_BASEADDR,"Expected UART0");
namespace {
XScuGic gic; netif network;
unsigned char mac[6]={0x00,0x0a,0x35,0x00,0x01,0x02};
s2c::ResultStore result_store;
s2c::BoardLog board_log;
bool startup_scanning=false;
s2c::Models model_store;
s2c::ModelSd model_sd;
s2c::RuntimeModelActivation model_engine;
s2c::TaskTiming task_timing;
TTMeasureRecord task_detail;
s2c::DisplayView scene_view(uint32_t boot,uint32_t session,unsigned task,unsigned completed,
                            s2c::ViewState state,int error=0) {
    s2c::DisplayView v{};v.boot=boot;v.session=session;v.task=task;v.completed=completed;v.state=state;v.error=error;
    return v;
}
uint64_t now_us() {
    XTime t; XTime_GetTime(&t);
    return (t/COUNTS_PER_SECOND)*1000000ULL+((t%COUNTS_PER_SECOND)*1000000ULL)/COUNTS_PER_SECOND;
}
// Real board records are retained for Ethernet readback. UART is not an input,
// transport requirement or acceptance dependency; maintenance TX is off.
constexpr bool SERIAL_DEBUG=false;
void log_line(const char *s,uint32_t model_session=0) {
    if(!(model_session?board_log.append_model(model_session,s):board_log.append(s))||!SERIAL_DEBUG)return;
    const uint64_t start=now_us();
    for(unsigned i=0;i<s2c::BoardLog::LINE_BYTES && s[i];++i) {
        while(XUartPs_ReadReg(XPAR_XUARTPS_0_BASEADDR,XUARTPS_SR_OFFSET)&XUARTPS_SR_TXFULL)
            if(now_us()-start>=100000) return;
        if(now_us()-start>=100000) return;
        XUartPs_WriteReg(XPAR_XUARTPS_0_BASEADDR,XUARTPS_FIFO_OFFSET,uint8_t(s[i]));
    }
}
void report_timing(uint32_t session,unsigned task) {
    if(!task_timing.active())return; // terminal snapshot is immutable; no duplicate on later PROBE fault
    s2c::TimingSnapshot timing{};task_timing.finish(now_us());
    (void)task_timing.snapshot(now_us(),timing);char line[160];
    std::snprintf(line,sizeof(line),"S2C TASK_CLOCK session=%08lx task=%u elapsed_us=%llu accounted_us=%llu other_us=%llu valid=%u\r\n",
        (unsigned long)session,task,(unsigned long long)timing.elapsed_us,(unsigned long long)timing.accounted_us,
        (unsigned long long)timing.other_us,unsigned(timing.valid));log_line(line);
    for(unsigned i=0;i<s2c::TIMING_PHASES;++i) {
        std::snprintf(line,sizeof(line),"S2C TASK_PHASE session=%08lx task=%u part=%s calls=%llu us=%llu\r\n",
            (unsigned long)session,task,s2c::timing_phase_name(i),(unsigned long long)timing.calls[i],(unsigned long long)timing.us[i]);log_line(line);
    }
    std::snprintf(line,sizeof(line),"S2C TASK_PHASE session=%08lx task=%u part=wait_service calls=%llu us=%llu\r\n",
        (unsigned long)session,task,(unsigned long long)timing.wait_calls,(unsigned long long)timing.wait_us);log_line(line);
    const char *parts[]={"validate","extract","normalize","embed","cache_prepare","submit","wait","cache_complete"};
    for(unsigned i=0;i<TT_MEASURE_PARTS;++i){
        std::snprintf(line,sizeof(line),"S2C TASK_DETAIL session=%08lx task=%u part=%s calls=%llu us=%llu\r\n",
            (unsigned long)session,task,parts[i],(unsigned long long)task_detail.calls[i],(unsigned long long)task_detail.us[i]);log_line(line);
    }
    std::snprintf(line,sizeof(line),"S2C TASK_DETAIL session=%08lx task=%u part=wait_service calls=%llu us=%llu\r\n",
        (unsigned long)session,task,(unsigned long long)task_detail.wait_service_calls,(unsigned long long)task_detail.wait_service_us);log_line(line);
    std::snprintf(line,sizeof(line),"S2C TASK_ENGINE session=%08lx task=%u pixels=%llu calls=%llu cycles=%llu hz=%lu valid=%u\r\n",
        (unsigned long)session,task,(unsigned long long)task_detail.pixels,(unsigned long long)task_detail.pl_calls,
        (unsigned long long)task_detail.pl_cycles,(unsigned long)TT_M3A_CONFIGURED_PL_HZ,unsigned(task_detail.valid));log_line(line);
}
[[noreturn]] void stop(const char *reason) {
    Xil_ExceptionDisable(); log_line(reason);
    // Never disable caches/free/return/retry while PL DMA may still be active.
    for(;;) {}
}
bool due(uint64_t now,uint64_t &last,uint32_t ms) {
    const uint64_t interval=uint64_t(ms)*1000;
    if(now-last<interval) return false;
    last+=interval; return true;
}
class Timers {
    uint64_t arp_,reass_,tcp_;
public:
    explicit Timers(uint64_t n):arp_(n),reass_(n),tcp_(n) {}
    void poll() {
        const uint64_t n=now_us();
#if LWIP_ARP
        if(due(n,arp_,ARP_TMR_INTERVAL)) etharp_tmr();
#endif
#if IP_REASSEMBLY
        if(due(n,reass_,IP_TMR_INTERVAL)) ip_reass_tmr();
#endif
#if LWIP_TCP
        if(due(n,tcp_,TCP_TMR_INTERVAL)) tcp_tmr();
#endif
    }
};
class Link {
    udp_pcb *pcb_;
    static void receive(void *arg,udp_pcb *,pbuf *p,const ip_addr_t *addr,u16_t port) {
        if(!p) return;
        Link &self=*static_cast<Link *>(arg); const uint64_t now=now_us();
        static uint8_t bytes[1412]; const u16_t n=p->tot_len;
        if(!addr || !IP_IS_V4(addr) || (n<12 || n>sizeof(bytes)) || pbuf_copy_partial(p,bytes,n,0)!=n) {
            self.protocol.bad_input(); pbuf_free(p); return;
        }
        const s2c::Peer from={ip_addr_get_ip4_u32(addr),port}; pbuf_free(p);
        static s2c::Packet reply; // single main-loop callback, avoid stacking 1412B packet
        if(self.protocol.receive(bytes,n,from,now,reply)) self.send(reply);
    }
public:
    s2c::Protocol protocol;
    explicit Link(uint32_t boot):pcb_(nullptr),protocol(boot,true,&result_store,&model_store,S2C_RELEASE_ID,&board_log) {}
    bool open() {
        if(!protocol.release_bound())return false;
        pcb_=udp_new(); if(!pcb_) return false;
        if(udp_bind(pcb_,IP_ADDR_ANY,5010)!=ERR_OK) { udp_remove(pcb_); pcb_=nullptr; return false; }
        udp_recv(pcb_,receive,this); return true;
    }
    void send(s2c::Packet &packet) {
        if(!packet.to.ipv4||!packet.to.port)return; // a local task has no synthetic UDP peer
        pbuf *p=pbuf_alloc(PBUF_TRANSPORT,u16_t(packet.size),PBUF_RAM);
        if(!p) { protocol.sent(packet.size,false); return; }
        s2c::stamp(packet,now_us());
        err_t rc=pbuf_take(p,packet.bytes,u16_t(packet.size));
        if(rc==ERR_OK) {
            ip_addr_t dst; ip_addr_set_ip4_u32(&dst,packet.to.ipv4);
            rc=udp_sendto(pcb_,p,&dst,packet.to.port);
        }
        pbuf_free(p); protocol.sent(packet.size,rc==ERR_OK); // CPU pbuf, NOT PL buffers
    }
    void poll() { if(protocol.local_owner())return;
        static s2c::Packet p; if(protocol.status(now_us(),p)) send(p);
        if(protocol.temperature_packet(now_us(),p))send(p);
        if(protocol.power_packet(now_us(),p))send(p);
        if(protocol.key_packet(now_us(),p))send(p); }
};
XGpioPs key_gpio;s2c::Keys keys;Link *key_link=nullptr;bool keys_ready=false;
void sample_keys() {
    if(!keys_ready||!key_link)return;
    const uint64_t now=now_us();
    static uint64_t sampled=0;if(now-sampled<5000)return;sampled=now;
    const auto event=keys.poll(now,XGpioPs_ReadPin(&key_gpio,26)==0,XGpioPs_ReadPin(&key_gpio,78)==0);
    if(event.key)(void)key_link->protocol.queue_key(event.key,event.gesture,now);
}
// One main-thread network/timer owner, including the driver's optional wait
// callback. BSP standalone xemacpsif_input services at most one frame per call;
// no drain loop, sleeps, UART, numerical calls or DMA-buffer access here.
class NetPump {
    Timers &timers_;Link &link_;
    s2c::TaskTiming &timing_;
    uint64_t last_,max_gap_,max_service_;
    uint32_t wait_calls_,wait_rx_;
    uint32_t scan_bytes_=0;bool scan_reported_=false;
public:
    NetPump(Timers &timers,Link &link,s2c::TaskTiming &timing):timers_(timers),link_(link),timing_(timing),last_(now_us()),
        max_gap_(0),max_service_(0),wait_calls_(0),wait_rx_(0) {}
    void reset_metrics(){last_=now_us();max_gap_=max_service_=0;wait_calls_=wait_rx_=0;}
    void poll(bool in_wait=false) {
        s2c::TimingScope phase(timing_,s2c::TimingPhase::pump,now_us);
        const uint64_t started=now_us(),gap=started-last_;last_=started;
        if(gap>max_gap_)max_gap_=gap;
        const uint32_t rx=link_.protocol.received_count();
        sample_keys();
        (void)xemacif_input(&network);timers_.poll();link_.poll();
        if(in_wait){++wait_calls_;wait_rx_+=link_.protocol.received_count()-rx;}
        const uint64_t ended=now_us(),spent=ended-started;if(spent>max_service_)max_service_=spent;
        if(in_wait)(void)timing_.add_wait(started,ended); // overlapping diagnostic subset, never sum twice
    }
    static void waiting(void *context){static_cast<NetPump *>(context)->poll(true);}
    static void sd_service(void *context){
        auto &pump=*static_cast<NetPump *>(context);const auto &r=model_sd.receipt();
        if(startup_scanning&&(!pump.scan_reported_||r.bytes-pump.scan_bytes_>=4u*1024u*1024u)){
            char line[160];std::snprintf(line,sizeof(line),"S2C STARTUP phase=model_scan bytes=%lu directories=%u registered=%u rejected=%u\r\n",
                (unsigned long)r.bytes,r.directories,r.registered,r.rejected);log_line(line);
            pump.scan_reported_=true;pump.scan_bytes_=r.bytes;
        }
        pump.poll(false);
    }
    void report(const char *scope) const {
        char line[160];
        std::snprintf(line,sizeof(line),"S2C S3 scope=%s session=%08lx task=%u wait_calls=%lu wait_rx=%lu max_gap_us=%llu max_service_us=%llu\r\n",
            scope,(unsigned long)link_.protocol.session(),unsigned(link_.protocol.task()),
            (unsigned long)wait_calls_,(unsigned long)wait_rx_,
            (unsigned long long)max_gap_,(unsigned long long)max_service_);
        log_line(line);
    }
};
}
extern "C" const char gcs_release_identity[] =
    "S2C BUILD app=" S2C_APP_ID " release=" S2C_RELEASE_ID
    " sources=" S2C_SOURCE_SHA256 " xsa=" S2C_XSA_SHA256 "\r\n";
static_assert(sizeof(gcs_release_identity)<=s2c::BoardLog::LINE_BYTES,"Complete BUILD identity must fit the actual log sink");
int main() {
    Xil_ICacheEnable(); Xil_DCacheEnable();
    if(!S2C_RELEASE_BOUND)stop("S2C STOP unbound release; use the complete reviewed source bundle\r\n");
    log_line(gcs_release_identity);
    char line[160];
    // SD journal reservation is durable BEFORE any GEM/UDP/IP/READY. No UART RX.
    s2c::BootIdentity identity;const int identity_rc=s2c::acquire_sd_boot_id(identity);
    if(identity_rc){std::snprintf(line,sizeof(line),"S2C STOP identity rc=%d; preserve journal, no fallback or auto repair\r\n",identity_rc);stop(line);}
    const uint32_t boot_id=identity.boot;
    std::snprintf(line,sizeof(line),"S2C IDENTITY source=sd-journal boot_id=%08lx generation=%lu nonce=%08lx%08lx abi=4\r\n",
        (unsigned long)boot_id,(unsigned long)identity.generation,(unsigned long)identity.nonce_hi,(unsigned long)identity.nonce_lo);log_line(line);
    if(!s2c::configure_models(model_sd))stop("S2C STOP model owner configuration\r\n");
    log_line("S2C STARTUP phase=network_initialization\r\n");
    Xil_ExceptionDisable();
    XScuGic_Config *config=XScuGic_LookupConfig(XPAR_SCUGIC_0_DEVICE_ID);
    if(!config || XScuGic_CfgInitialize(&gic,config,config->CpuBaseAddress)!=XST_SUCCESS)
        stop("S2C STOP GIC init\r\n");
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,
        reinterpret_cast<Xil_ExceptionHandler>(XScuGic_InterruptHandler),&gic);
    Xil_ExceptionEnable();
    lwip_init(); ip_addr_t ip,mask,gateway;
    IP4_ADDR(&ip,192,168,1,10); IP4_ADDR(&mask,255,255,255,0); IP4_ADDR(&gateway,192,168,1,1);
    if(!xemac_add(&network,&ip,&mask,&gateway,mac,XPAR_XEMACPS_0_BASEADDR)) stop("S2C STOP GEM init\r\n");
    netif_set_default(&network); netif_set_up(&network);
    static Link link(boot_id); if(!link.open()) stop("S2C STOP UDP bind\r\n");
    // KEY7 is the physical reset and is never configured by this application.
#ifdef SDT
    XGpioPs_Config *key_cfg=XGpioPs_LookupConfig(XPAR_XGPIOPS_0_BASEADDR);
#else
    XGpioPs_Config *key_cfg=XGpioPs_LookupConfig(XPAR_XGPIOPS_0_DEVICE_ID);
#endif
    keys_ready=key_cfg&&XGpioPs_CfgInitialize(&key_gpio,key_cfg,key_cfg->BaseAddr)==XST_SUCCESS;
    if(keys_ready){XGpioPs_SetDirectionPin(&key_gpio,26,0);XGpioPs_SetDirectionPin(&key_gpio,78,0);key_link=&link;}
    s2c::display_key_service(sample_keys);
    log_line(keys_ready?"S2C KEYS ready KEY5=MIO26 KEY6=EMIO0/GPIO78 KEY7=RESET debounce_ms=25 double_ms=350 hold_ms=2000\r\n":
                         "S2C KEYS unavailable GPIO initialization failed\r\n");
    Timers timers(now_us());
    NetPump pump(timers,link,task_timing);
    if(!model_sd.set_service(NetPump::sd_service,&pump))stop("S2C STOP SD service owner configuration\r\n");
    if(tt_m3a_set_wait_service(NetPump::waiting,&pump,256)!=TT_M3A_OK)
        stop("S2C STOP S3 registration failed; no task allowed\r\n");
    // Network diagnostics are available while scanning; Protocol rejects all
    // non-observational commands until the complete READY record is captured.
    startup_scanning=true;
    std::snprintf(line,sizeof(line),"S2C boot_id=%08lx MODEL_SCAN int16; no inference yet\r\n",(unsigned long)boot_id);log_line(line);
    const bool scan_ok=model_sd.scan(model_store);startup_scanning=false;
    const auto scan=model_sd.receipt();const TTM3aAppSession &s=s2c::outcome();
    std::snprintf(line,sizeof(line),"S2C MODEL_SCAN complete=%u entries=%u rejected=%u rc=%d cleanup=%d reject_rc=%d reject_code=%u\r\n",
        unsigned(scan_ok),model_store.count(),scan.rejected,scan.status,scan.cleanup_status,scan.last_reject_status,scan.last_reject_code);log_line(line);
    log_line("S2C STARTUP phase=display_initialization\r\n");pump.poll();
    auto initial_view=scene_view(boot_id,0,0,0,s2c::ViewState::ready);
    initial_view.preview_scene=true;
    const auto *default_model=s2c::default_key_model(model_store,0);
    if(default_model)std::memcpy(initial_view.tag,default_model->key.tag,16);
    const int dp_rc=s2c::display_init(initial_view);
    std::snprintf(line,sizeof(line),"S2C DP init_rc=%d 1920x1080; picture requires user check; no SD assets\r\n",dp_rc);log_line(line);
    std::snprintf(line,sizeof(line),"S2C READY boot_id=%08lx registry=%u scan_ok=%u scenes=3 roi=any banks=1 UDP=5010 app=" S2C_APP_ID "\r\n",
        (unsigned long)boot_id,model_store.count(),unsigned(scan_ok));
    log_line(line);
    link.protocol.mark_startup_ready();
    bool dp_live=false;
    uint64_t compute_us=0;
    uint32_t whole_crc=0xffffffffu;
    bool stop_logged=false;
    uint64_t dp_connection_at=0;
    uint64_t temperature_at=0;float temperature_peak=-40.0f;
    static s2c::Packet packet;
    s2c::KeyEvent local_event{};bool local_waiting=false,local_stop_requested=false;
    s2c::LocalKeyPlan local_plan{};unsigned local_plan_task=0;
    static s2c::ParcelView local_parcel;bool local_parcel_active=false;
    auto view=[&](s2c::ViewState state,int error=0) {
        auto v=scene_view(boot_id,link.protocol.session(),link.protocol.task(),unsigned(s.roi.completed),state,error);
        v.x=link.protocol.x();v.y=link.protocol.y();v.width=link.protocol.width();v.height=link.protocol.height();
        v.scene=link.protocol.scene();v.wcrc=link.protocol.wcrc();
        v.kind=link.protocol.full_scene()?s2c::TaskKind::full_scene:s2c::TaskKind::region;
        const auto *slot=result_store.find(link.protocol.session(),link.protocol.task());if(slot)std::memcpy(v.tag,slot->tag,16);
        v.compute_ms_per_pixel=link.protocol.compute_ms_per_pixel();return v;
    };
    for(;;) {
        pump.poll();
        if(!local_waiting&&link.protocol.take_local_key(now_us(),local_event)) {
            local_waiting=true;local_stop_requested=false;
            std::snprintf(line,sizeof(line),"S2C LOCAL_KEY id=%lu key=%u gesture=%u scene=%u\r\n",
                (unsigned long)link.protocol.key_id(),local_event.key,local_event.gesture,link.protocol.key_scene());log_line(line);
        }
        if(local_waiting) {
            if(local_event.gesture==3) {
                if(!local_stop_requested)local_stop_requested=link.protocol.request_local_stop();
                if(local_stop_requested&&!link.protocol.local_busy()) {
                    const unsigned next=(link.protocol.key_scene()+1)%3;
                    const bool available=s2c::default_key_model(model_store,next)!=nullptr;
                    link.protocol.complete_local_key(available,available?10:3,next);local_waiting=false;
                    std::snprintf(line,sizeof(line),"S2C LOCAL_SCENE id=%lu scene=%u ready=%u input_deferred=1\r\n",
                        (unsigned long)link.protocol.key_id(),next,unsigned(available));log_line(line);
                }
            } else if(local_event.key==5&&local_event.gesture==1&&link.protocol.local_probe_context(link.protocol.key_scene())) {
                s2c::LocalKeyPlan point;
                const bool planned=s2c::make_local_key_plan(5,1,link.protocol.key_scene(),uint32_t(now_us())^boot_id^link.protocol.key_id(),point);
                const bool begun=planned&&link.protocol.begin_local_probe(point.y,point.x);
                link.protocol.complete_local_key(begun,begun?13:3);local_waiting=false;
            } else if(link.protocol.local_busy()) {
                link.protocol.complete_local_key(false,2);local_waiting=false;
            } else {
                const unsigned scene=link.protocol.key_scene();const auto *model=s2c::default_key_model(model_store,scene);
                const bool planned=s2c::make_local_key_plan(local_event.key,local_event.gesture,scene,
                    uint32_t(now_us())^boot_id^link.protocol.key_id(),local_plan);
                const bool begun=model&&planned&&link.protocol.begin_local_task(local_plan,model->key.crc,now_us());
                if(begun)local_plan_task=link.protocol.task();
                link.protocol.complete_local_key(begun,begun?13:3);local_waiting=false;
            }
            if(dp_rc==0)(void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
        }
        const uint64_t display_now=now_us();
        if(display_now-temperature_at>=1000000) {
            temperature_at=display_now;
            // Read the existing PS SYSMON temperature channel. No reset,
            // alarm disable, rail programming or PL sequencer reconfiguration.
            const uint32_t raw=XSysmonPsu_ReadReg(XPAR_XSYSMONPSU_0_BASEADDR+XPS_BA_OFFSET)&0xffff;
            const float value=XSysMonPsu_RawToTemperature_OnChip(raw);
            const bool valid=raw&&raw!=0xffff&&std::isfinite(value)&&value>=-40&&value<=125;
            if(valid&&value>temperature_peak)temperature_peak=value;
            link.protocol.set_temperature(value,temperature_peak,valid,display_now);
            if(dp_rc==0)(void)s2c::display_scene_temperature(value,temperature_peak,valid);
            if(dp_rc==0)(void)s2c::display_scene_power(link.protocol.power_view(display_now));
        }
        if(dp_rc==0&&display_now-dp_connection_at>=500000) {
            dp_connection_at=display_now;
            const auto peer=!link.protocol.peer_seen()?s2c::PeerState::waiting:
                link.protocol.peer_online(display_now)?s2c::PeerState::online:s2c::PeerState::timeout;
            (void)s2c::display_scene_connection(peer,link.protocol.peer_age_seconds(display_now));
            (void)s2c::display_scene_parcel_age(display_now);
            (void)s2c::display_scene_keys(link.protocol.key_id(),link.protocol.key_state(),link.protocol.key_code());
            (void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
        }
        static uint32_t key_preview=0;
        if(link.protocol.key_id()!=key_preview&&link.protocol.key_state()==3&&link.protocol.key_code()==10) {
            key_preview=link.protocol.key_id();
            if(link.protocol.task()!=link.protocol.key_task()||link.protocol.running())continue;
            const auto *spec=s2c::scene_contract(link.protocol.key_scene());
            auto ready=scene_view(boot_id,link.protocol.session(),0,0,s2c::ViewState::ready);
            ready.scene=link.protocol.key_scene();ready.width=spec->width;ready.height=spec->height;
            ready.preview_scene=true;
            // Scene selection does not claim that its weights/input have been
            // loaded. START still performs the existing full activation/CRC.
            const auto *selected=s2c::default_key_model(model_store,ready.scene);
            if(selected)std::memcpy(ready.tag,selected->key.tag,16);
            if(dp_rc==0)(void)s2c::display_scene_begin(ready);
            dp_live=false;
        }
        bool model_reply;
        {s2c::TimingScope phase(task_timing,s2c::TimingPhase::model,now_us);
            model_reply=link.protocol.model_poll(model_sd,model_engine,now_us(),packet);}
        if(model_reply) {
            link.send(packet);
            uint32_t value=0;for(unsigned i=0;i<4;++i)value|=uint32_t(packet.bytes[16+i])<<(8*i);
            const auto *active=model_store.active();
            std::snprintf(line,sizeof(line),"S2C MODELCMD session=%08lx type=%u seq=%u code=%u value=%08lx crc=%08lx active_scene=%d active_crc=%08lx sd_rc=%d\r\n",
                (unsigned long)link.protocol.session(),unsigned(packet.bytes[12]),unsigned(packet.bytes[14]|unsigned(packet.bytes[15])<<8),unsigned(packet.bytes[13]),
                (unsigned long)value,(unsigned long)link.protocol.model_command_crc(),active?int(active->key.scene):-1,
                (unsigned long)(active?active->key.crc:0),model_sd.receipt().status);
            log_line(line,link.protocol.session());
            if(model_store.faulted())stop("S2C HALTED: model DMA fault; retain buffers, external PL reset required\r\n");
        }
        if(link.protocol.take_job()) {
            local_parcel_active=false;
            task_detail=TTMeasureRecord{};
            task_timing.begin(now_us());
            s2c::TimingScope setup_phase(task_timing,s2c::TimingPhase::setup,now_us);
            pump.reset_metrics();compute_us=0;whole_crc=0xffffffffu;stop_logged=false;
            // Loading the scene cube from SD can take seconds. Show the newly
            // accepted identity before activation, not the previous task frame.
            auto preparing=view(s2c::ViewState::preparing);preparing.completed=0;
            {s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);
                dp_live=dp_rc==0 && s2c::display_scene_begin(preparing);}
            if(dp_rc==0)(void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
            const auto activated=model_store.activate(link.protocol.scene(),link.protocol.wcrc(),0,true,model_engine);
            if(activated.code) {
                const int error=activated.value?int32_t(activated.value):TT_M3A_SD_ARGUMENT;
                if(model_store.faulted()){link.protocol.failure(error,now_us(),packet);link.send(packet);
                    (void)setup_phase.finish();report_timing(link.protocol.session(),link.protocol.task());
                    stop("S2C HALTED: START model DMA fault; retain buffers, external PL reset required\r\n");}
                link.protocol.reject_job(error,now_us(),packet);link.send(packet);
                (void)setup_phase.finish();
                auto rejected=view(s2c::ViewState::running);rejected.completed=0;
                {s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);
                    if(dp_rc==0&&s2c::display_scene_begin(rejected)) {
                        rejected.state=s2c::ViewState::failed;rejected.error=error;rejected.fault_requires_reset=false;
                        (void)s2c::display_scene_update(rejected);
                    }
                }
                dp_live=false;stop_logged=true; // no old task count in a fake TASK_STOP
                std::snprintf(line,sizeof(line),"S2C TASK_REJECT session=%08lx task=%u scene=%u wcrc=%08lx rc=%d pre_dma=1\r\n",
                    (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),link.protocol.scene(),(unsigned long)link.protocol.wcrc(),error);
                log_line(line);report_timing(link.protocol.session(),link.protocol.task());continue;
            }
            const int rc=s2c::begin_task(link.protocol.x(),link.protocol.y(),link.protocol.width(),link.protocol.height());
            if(rc){link.protocol.failure(s.driver_status?s.driver_status:rc,now_us(),packet);link.send(packet);
                (void)setup_phase.finish();report_timing(link.protocol.session(),link.protocol.task());
                stop("S2C HALTED: task init; retain DMA, external PL reset required\r\n");}
            (void)setup_phase.finish();
            {s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);
                if(dp_live)dp_live=s2c::display_scene_update(view(s2c::ViewState::running));}
            const auto *model=model_store.active();
            std::snprintf(line,sizeof(line),"S2C TASK_BEGIN session=%08lx task=%u scene=%u model=%s wcrc=%08lx x=%u y=%u w=%u h=%u classes=%u\r\n",
                (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),link.protocol.scene(),model->key.tag,(unsigned long)model->key.crc,
                link.protocol.x(),link.protocol.y(),link.protocol.width(),link.protocol.height(),unsigned(s2c::scene_contract(link.protocol.scene())->classes));log_line(line);
            if(link.protocol.local_owner()&&local_plan_task==link.protocol.task()&&local_plan.action==s2c::DispatchAction::parcel) {
                local_parcel=s2c::ParcelView{};local_parcel.local=local_parcel.selected=true;
                local_parcel.boot=boot_id;local_parcel.session=link.protocol.session();local_parcel.task=link.protocol.task();
                local_parcel.scene=link.protocol.scene();local_parcel.wcrc=link.protocol.wcrc();local_parcel.classes=s2c::scene_contract(local_parcel.scene)->classes;
                local_parcel.points=local_plan.points;local_parcel.revision=local_parcel.id=local_parcel.serial=link.protocol.key_id();
                local_parcel.threshold=39321;
                const auto &name=s2c::labels::PARCEL_LOCAL_NAME;
                for(unsigned y=0;y<name.h&&y<24;++y)for(unsigned x=0;x<name.w&&x<192;++x) {
                    const unsigned bit=y*name.w+x,to=y*192+x;
                    if(name.bits[bit/8]&(1u<<(7-bit%8)))local_parcel.name_bits[to/8]|=uint8_t(1u<<(7-to%8));
                }
                const auto *spec=s2c::scene_contract(local_plan.scene);
                for(unsigned i=0;i<local_plan.points;++i){local_parcel.xy[i][0]=uint16_t(local_plan.xy[i][0]*65535/spec->width+.5);
                    local_parcel.xy[i][1]=uint16_t(local_plan.xy[i][1]*65535/spec->height+.5);}
                for(unsigned y=local_plan.y;y<local_plan.y+local_plan.height;++y)
                    for(unsigned x=local_plan.x;x<local_plan.x+local_plan.width;++x)
                        if(local_plan.contains(y,x))++local_parcel.pixels;
                local_parcel_active=local_parcel.pixels>0;
                if(dp_rc==0&&local_parcel_active)(void)s2c::display_scene_parcel(local_parcel,now_us());
            }
        }
        // The lwIP/wait-service callback queues only; foreground applies at a row boundary.
        bool control_reply;
        {s2c::TimingScope phase(task_timing,s2c::TimingPhase::control,now_us);
            control_reply=link.protocol.apply_control(now_us(),packet);}
        if(control_reply) {
            if(link.protocol.stopped() && !s2c::stop_task())stop("S2C HALTED: stop rejected, fault remains latched\r\n");
            link.send(packet);
            if(dp_live){s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);
                dp_live=s2c::display_scene_update(view(link.protocol.stopped()?s2c::ViewState::stopped:
                    link.protocol.paused()?s2c::ViewState::paused:s.roi.completed==link.protocol.total()?s2c::ViewState::done:s2c::ViewState::running));}
            std::snprintf(line,sizeof(line),"S2C CONTROL session=%08lx task=%u type=%u seq=%u completed=%lu\r\n",
                (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),unsigned(packet.bytes[12]),
                unsigned(packet.bytes[14]|unsigned(packet.bytes[15])<<8),(unsigned long)s.roi.completed);log_line(line);
            if(link.protocol.stopped() && !stop_logged) {
                stop_logged=true;report_timing(link.protocol.session(),link.protocol.task());pump.report("task");
                std::snprintf(line,sizeof(line),"S2C TASK_STOP session=%08lx task=%u completed=%lu compute_us=%llu crc32=%08lx\r\n",
                    (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),(unsigned long)s.roi.completed,
                    (unsigned long long)compute_us,(unsigned long)(whole_crc^0xffffffffu));log_line(line);
            }
        }
        static s2c::ParcelView parcel_view;
        if(link.protocol.take_parcel(parcel_view)&&dp_rc==0)
            (void)s2c::display_scene_parcel(parcel_view,now_us());
        uint32_t mirror_id,mirror_offset;
        if(link.protocol.take_mirror(mirror_id,mirror_offset)) {
            static uint8_t mirror_bytes[1372];uint32_t total=0,crc=0;
            const unsigned count=s2c::display_mirror(mirror_id,mirror_offset,mirror_bytes,sizeof(mirror_bytes),total,crc);
            link.protocol.mirror_reply(total,crc,mirror_bytes,count,now_us(),packet);link.send(packet);
        }
        unsigned probe_row,probe_col;uint16_t probe_seq;
        if(link.protocol.take_probe(probe_row,probe_col,probe_seq)) {
            // Fast probes can finish between the periodic status refreshes.
            if(dp_rc==0)(void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
            uint32_t word=0;int32_t logits[24];static uint32_t attention[432];
            const bool wants_attention=link.protocol.probe_wants_attention();
            s2c::ProbeView probe_view{};probe_view.boot=boot_id;probe_view.session=link.protocol.session();probe_view.task=link.protocol.task();
            probe_view.scene=link.protocol.probe_scene();probe_view.wcrc=link.protocol.probe_wcrc();
            const auto *probe_model=model_store.find(probe_view.scene,1,probe_view.wcrc);
            if(probe_model)std::memcpy(probe_view.tag,probe_model->key.tag,16);
            probe_view.row=probe_row;probe_view.col=probe_col;probe_view.state=s2c::ProbeState::running;
            if(dp_live)(void)s2c::display_scene_probe(probe_view);
            int rc;
            {s2c::TimingScope phase(task_timing,s2c::TimingPhase::probe,now_us);
                rc=s2c::probe_model(model_store,link.protocol.probe_scene(),link.protocol.probe_wcrc(),probe_row,probe_col,word,logits,24,
                    wants_attention?attention:nullptr,wants_attention?432:0);}
            if(!rc&&wants_attention&&!link.protocol.cache_attention(attention,432)){rc=TT_M3A_CONTRACT;model_store.fault(rc);}
            if(rc) {
                const bool fatal=model_store.faulted()||s.roi.halted;
                probe_view.state=s2c::ProbeState::failed;probe_view.error=s.driver_status?s.driver_status:rc;
                if(dp_live)(void)s2c::display_scene_probe(probe_view);
                link.protocol.probe_failure(s.driver_status?s.driver_status:rc,now_us(),packet,fatal);link.send(packet);
                if(dp_rc==0)(void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
                if(fatal){report_timing(link.protocol.session(),link.protocol.task());stop("S2C PROBE HALTED: preserve DMA; external PL reset + App restart required\r\n");}
                std::snprintf(line,sizeof(line),"S2C PROBE_REJECT session=%08lx task=%u seq=%u rc=%d pre_dma=1\r\n",
                    (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),unsigned(probe_seq),rc);log_line(line);continue;
            }
            link.protocol.probe_reply(word,logits,now_us(),packet);link.send(packet);
            if(dp_rc==0)(void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
            if(dp_live) {
                const auto *probed=model_store.find(link.protocol.probe_scene(),1,link.protocol.probe_wcrc());
                if(probed) {
                    auto p=probe_view;p.word=word;p.attention=wants_attention;p.state=s2c::ProbeState::done;
                    s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);
                    (void)s2c::display_scene_probe(p); // no scan append/progress or state transition
                }
            }
            std::snprintf(line,sizeof(line),"S2C PROBE session=%08lx task=%u seq=%u scene=%u wcrc=%08lx ncls=%u x=%u y=%u class_word=%08lx\r\n",
                (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),unsigned(probe_seq),link.protocol.probe_scene(),
                (unsigned long)link.protocol.probe_wcrc(),link.protocol.probe_classes(),probe_col,probe_row,(unsigned long)word);log_line(line);
            for(unsigned i=0;i<link.protocol.probe_classes();++i){std::snprintf(line,sizeof(line),"S2C LOGIT session=%08lx task=%u seq=%u class=%u q16=%ld\r\n",
                (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),unsigned(probe_seq),i,(long)logits[i]);log_line(line);}
            if(wants_attention){
                std::snprintf(line,sizeof(line),"S2C ATTN session=%08lx task=%u seq=%u layers=12 n=6 frac=24 crc32=%08lx\r\n",
                    (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),unsigned(probe_seq),(unsigned long)link.protocol.attention_crc());log_line(line);
                for(unsigned layer=0;layer<12;++layer){const uint32_t crc=s2c::model_crc(reinterpret_cast<const uint8_t *>(attention+layer*36),144);
                    std::snprintf(line,sizeof(line),"S2C ATTN_LAYER session=%08lx task=%u seq=%u layer=%u crc32=%08lx\r\n",
                        (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),unsigned(probe_seq),layer,(unsigned long)crc);log_line(line);}
            }
        }
        if(link.protocol.attention_fragment(now_us(),packet))link.send(packet);
        if(link.protocol.running()) {
            const unsigned before=unsigned(s.roi.completed),width=link.protocol.width();
            s2c::TimingScope step_phase(task_timing,s2c::TimingPhase::step,now_us);
            int rc;{TTMeasureUse detailed(task_detail,now_us);rc=s2c::step_task();}compute_us+=step_phase.finish();
            // CPU-committed prefix only, even on fault. No DMA reads/free/cancel.
            for(unsigned i=before;i<s.roi.completed;++i) {
                uint32_t word;const unsigned row=link.protocol.y()+i/width,col=link.protocol.x()+i%width;
                {s2c::TimingScope phase(task_timing,s2c::TimingPhase::results,now_us);
                    if(!s2c::copy_pixel(i,word) || !result_store.append(link.protocol.session(),link.protocol.task(),row,col,1,&word)){rc=TT_M3A_ROI_BUFFER;break;}
                    for(unsigned byte=0;byte<4;++byte){whole_crc^=uint8_t(word>>(8*byte));for(unsigned bit=0;bit<8;++bit)whole_crc=(whole_crc>>1)^((whole_crc&1)?0xedb88320u:0u);}
                    if(local_parcel_active&&local_parcel.task==link.protocol.task()&&local_plan.contains(row,col)) {
                        ++local_parcel.received;++local_parcel.counts[word&255];
                        if((word>>16)<39322)++local_parcel.low;
                    }
                }
                if(dp_live){s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);dp_live=s2c::display_scene_append(row,col,1,&word);}
            }
            if(!link.protocol.progress(s.roi.completed) && !rc)rc=TT_M3A_ROI_BUFFER;
            // Cumulative successful task-step time: PS extraction/embed + PL
            // invocation/wait (including wait-service), not pure PL latency.
            // LOAD_W, PROBE, foreground DP/UDP, pauses and idle are excluded.
            if(!rc && !link.protocol.record_compute(compute_us,s.roi.completed))rc=TT_M3A_ROI_BUFFER;
            // Every task has a bounded pixel count and each driver call has
            // max_polls. Do not silently truncate larger scenes at the old
            // LongKou-only 30-minute accumulated-compute limit.
            if(rc || s.roi.halted) {
                task_detail.valid=false;
                if(dp_live)(void)s2c::display_scene_update(view(s2c::ViewState::failed,s.driver_status?s.driver_status:rc));
                link.protocol.failure(s.driver_status?s.driver_status:rc,now_us(),packet);link.send(packet);
                report_timing(link.protocol.session(),link.protocol.task());
                stop("S2C HALTED: retain all DMA + committed prefix; external PL reset required\r\n");
            }
            if(s.roi.completed%width==0) {
                const unsigned row=link.protocol.y()+unsigned(s.roi.completed)/width-1;
                auto *slot=result_store.find(link.protocol.session(),link.protocol.task());
                {s2c::TimingScope phase(task_timing,s2c::TimingPhase::rows,now_us);
                    for(unsigned col=link.protocol.x();col<link.protocol.x()+width;col+=s2c::ROW_MAX) {
                        const unsigned remain=link.protocol.x()+width-col,n=remain<s2c::ROW_MAX?remain:s2c::ROW_MAX;
                        if(link.protocol.row_segment(row,col,n,slot->words+row*slot->scene_width+col,now_us(),packet))link.send(packet);
                    }
                }
                if(dp_live){s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);dp_live=s2c::display_scene_update(view(s2c::ViewState::running));}
                if(dp_live&&local_parcel_active)(void)s2c::display_scene_parcel(local_parcel,now_us());
            }
            if(s.roi.completed==link.protocol.total()) {
                if(!link.protocol.finish(s.roi.completed,now_us()))stop("S2C HALTED: invalid task completion\r\n");
                if(dp_live){s2c::TimingScope phase(task_timing,s2c::TimingPhase::display,now_us);dp_live=s2c::display_scene_update(view(s2c::ViewState::done));}
                if(dp_live&&link.protocol.local_owner()&&local_plan_task==link.protocol.task()&&local_plan.action==s2c::DispatchAction::point) {
                    auto p=s2c::ProbeView{};p.boot=boot_id;p.session=link.protocol.session();p.task=link.protocol.task();
                    p.scene=link.protocol.scene();p.wcrc=link.protocol.wcrc();p.row=local_plan.y;p.col=local_plan.x;
                    const auto *slot=result_store.find(p.session,p.task);std::memcpy(p.tag,slot->tag,16);
                    p.word=slot->words[p.row*slot->scene_width+p.col];p.state=s2c::ProbeState::done;
                    (void)s2c::display_scene_probe(p);
                }
                if(dp_rc==0)(void)s2c::display_scene_dispatch(link.protocol.dispatch_view());
                report_timing(link.protocol.session(),link.protocol.task());
                pump.report("task");
                std::snprintf(line,sizeof(line),"S2C TASK_DONE session=%08lx task=%u completed=%lu compute_us=%llu crc32=%08lx\r\n",
                    (unsigned long)link.protocol.session(),unsigned(link.protocol.task()),(unsigned long)s.roi.completed,
                    (unsigned long long)compute_us,(unsigned long)(whole_crc^0xffffffffu));log_line(line);
            }
        }
        // Lower priority than live results, at most eight packets per turn.
        {s2c::TimingScope phase(task_timing,s2c::TimingPhase::rows,now_us);
            for(unsigned i=0;i<8 && link.protocol.replay(now_us(),packet);++i)link.send(packet);}
    }
}
