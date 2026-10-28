#include "roi_protocol.h"
#include "roi_board_log.h"
#include <cstring>
#include <limits>
#include <cmath>
namespace s2c {
namespace {
uint16_t u16(const uint8_t *p) { return uint16_t(p[0]|uint16_t(p[1])<<8); }
uint32_t u32(const uint8_t *p) { return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24; }
void p16(uint8_t *p,uint16_t v) { p[0]=uint8_t(v); p[1]=uint8_t(v>>8); }
void p32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;++i) p[i]=uint8_t(v>>(8*i)); }
bool same(Peer a,Peer b) { return a.ipv4==b.ipv4 && a.port==b.port; }
}
Protocol::Protocol(uint32_t boot_id,bool lifecycle,ResultStore *store,Models *models,const char *release,BoardLog *logs):boot_id_(boot_id),session_(0),peer_{0,0},
    task_(0),tx_seq_(0),rx_seq_(0),start_seq_(0),down_cnt_(0),have_peer_(false),
    online_(false),have_rx_(false),have_status_(false),accepted_(false),pending_(false),
    taken_(false),done_(false),last_rx_(0),last_status_(0),down_since_(0),down_total_(0),
    tx_pkts_(0),tx_bytes_(0),tx_fail_(0),rx_pkts_(0),rx_bad_(0),rx_gap_(0),rx_dup_(0),request_{},completed_(0),failed_(false),
    probe_seen_(false),probe_pending_(false),probe_ready_(false),probe_seq_(0),probe_row_(0),probe_col_(0),probe_word_(0),probe_logits_{},
    lifecycle_(lifecycle),paused_(false),stopped_(false),control_seen_(false),control_(0),last_control_(0),used_tasks_{},control_seq_(0),
    store_(store),replay_rows_{},replay_task_(0),replay_row_(0),replay_col_(0),tx_retx_(0),compute_us_(0),models_(models),logs_(logs),startup_ready_(logs==nullptr) {
    if(!release || std::strlen(release)!=64)return;
    for(unsigned i=0;i<64;++i) {
        const char c=release[i];const int value=c>='0'&&c<='9'?c-'0':(c>='a'&&c<='f'?c-'a'+10:-1);
        if(value<0){std::memset(release_tag_,0,sizeof(release_tag_));return;}
        if(i<32)release_tag_[i/2]|=uint8_t(value<<((1-i%2)*4));
    }
    release_bound_=true;
}
uint32_t Protocol::wcrc() const {
    if(accepted_)return u32(request_+12);
    return models_?(models_->active()?models_->active()->key.crc:0):WCRC;
}
void stamp(Packet &p,uint64_t now) { p32(p.bytes+8,uint32_t(now)); }
void Protocol::tick(uint64_t now) {
    if(online_ && now-last_rx_>=1000000) {
        online_=false; have_rx_=false; down_since_=last_rx_+1000000; ++down_cnt_;
    }
}
uint64_t Protocol::packet_order(uint16_t seq) const {
    if(!have_rx_)return rx_order_+65536; // new observed sequence baseline
    const uint16_t forward=uint16_t(seq-rx_seq_);
    if(forward<0x8000)return rx_order_+forward;
    const uint16_t back=uint16_t(rx_seq_-seq);return back<=rx_order_?rx_order_-back:0;
}
void Protocol::received(uint16_t seq,uint64_t now) {
    if(have_rx_) {
        const uint16_t delta=uint16_t(seq-rx_seq_);
        if(delta && delta<0x8000) { rx_gap_+=delta-1; rx_seq_=seq;rx_order_+=delta; }
    } else { have_rx_=true; rx_seq_=seq;rx_order_+=65536; }
    if(have_peer_ && !online_) down_total_+=now-down_since_;
    online_=true; last_rx_=now; ++rx_pkts_;
}
void Protocol::header(Packet &p,uint8_t type,size_t size,uint64_t now) {
    std::memset(p.bytes,0,sizeof(p.bytes)); p.to=peer_; p.size=size;
    p16(p.bytes,0x4548); p.bytes[2]=type; p.bytes[3]=1;
    p16(p.bytes+4,task_); p16(p.bytes+6,tx_seq_++); stamp(p,now);
}
void Protocol::ack(Packet &p,uint16_t task,uint16_t seq,uint8_t code,uint32_t value,uint64_t now) {
    header(p,0x83,20,now); p16(p.bytes+4,task); p.bytes[12]=1; p.bytes[13]=code;
    p16(p.bytes+14,seq); p32(p.bytes+16,value);
}
bool Protocol::receive_model(const uint8_t *b,size_t n,Peer from,uint64_t now,Packet &p) {
    if(!models_ || !have_peer_ || !same(from,peer_)){bad_input();return false;}
    const uint16_t seq=u16(b+6),task=u16(b+4);const uint64_t order=packet_order(seq);received(seq,now);
    auto reply=[&](ModelReply r){ack(p,task,seq,r.code,r.value,now);p.bytes[12]=b[2];return true;};
    if(failed_||models_->faulted())return reply({6,0});
    if(model_seen_) {
        const uint16_t delta=uint16_t(seq-u16(model_request_+6));
        if((order==model_order_) || (!delta && model_pending_)) {
            // Retransmission may refresh only its timestamp. Never allow a
            // same-sequence payload replacement to mutate the staged object.
            if(n!=model_size_||std::memcmp(b,model_request_,8)||std::memcmp(b+12,model_request_+12,n-12))return reply({8,0});
            if(model_pending_)return false;
            return reply(model_reply_);
        }
        if(model_pending_||order<model_order_)return reply({8,0});
    }
    std::memcpy(model_request_,b,n);model_size_=n;model_seen_=true;model_order_=order;model_reply_={8,0};
    if(b[2]==0x11 && !u16(b+14)) {
        ModelKey key{};key.scene=b[12];key.kind=b[13];key.bytes=u32(b+16);key.crc=u32(b+20);std::memcpy(key.tag,b+24,16);
        model_reply_=models_->begin(key);
    } else if(b[2]==0x10 && !u16(b+14)) {
        model_reply_=models_->chunk(b[12],b[13],u32(b+20),u32(b+24),u32(b+16),b+28,n-28);
    } else if(b[2]==0x12 && u32(b+12)) {
        model_pending_=true;return false;
    } else if(b[2]==0x13 && !b[13] && !u16(b+14) && scene_contract(b[12])) {
        const auto *e=models_->find(b[12],1,u32(b+16));
        if(!e||!models_->companion(*e))model_reply_={5,0};
        else {model_pending_=true;return false;}
    }
    return reply(model_reply_);
}
uint32_t Protocol::model_command_crc() const {
    return model_request_[2]==0x13?u32(model_request_+16):u32(model_request_+12);
}
bool Protocol::model_poll(ModelPersistence &disk,ModelActivation &engine,uint64_t now,Packet &p) {
    p.size=0;
    if(!models_||failed_||models_->faulted())return false;
    const bool idle=(!accepted_||done_||stopped_)&&!pending_&&!control_&&!(probe_seen_&&!probe_ready_);
    if(!model_pending_) {if(idle)(void)models_->flush_one(disk);return false;}
    const uint8_t type=model_request_[2];
    if(type==0x13&&!idle)return false; // single bank: NOT pause or a live row boundary
    model_reply_=type==0x12?models_->commit(u32(model_request_+12),idle,&disk):
        models_->activate(model_request_[12],u32(model_request_+16),model_request_[13],idle,engine);
    model_pending_=false;
    if(type==0x13&&!model_reply_.code)scene_selected_=false;
    ack(p,u16(model_request_+4),u16(model_request_+6),model_reply_.code,model_reply_.value,now);p.bytes[12]=type;
    return true;
}
bool Protocol::receive_log(const uint8_t *b,Peer from,uint64_t now,Packet &p) {
    const uint16_t task=u16(b+4),seq=u16(b+6);const uint32_t session=u32(b+16);
    // Discovery reads the boot stream without binding a peer. Task streams use
    // the already owned socket; queries never refresh heartbeat/sequence state.
    if(session&&(!have_peer_||!same(from,peer_))){bad_input();return false;}
    auto reject=[&](uint8_t code){ack(p,task,seq,code,0,now);p.bytes[12]=0x14;p.to=from;return true;};
    const bool boot_discovery=!task&&!session&&!u32(b+12);
    if(!release_bound_||!logs_||(!boot_discovery&&u32(b+12)!=boot_id_)||(task&&!session)||(session&&session!=session_))return reject(8);
    const LogView view=logs_->view(session,task);
    if(!view.valid||(task&&(!store_||!store_->find(session,task))))return reject(7);
    const uint32_t offset=u32(b+20),requested=u32(b+24);
    const size_t total=requested?requested:view.size;
    if(total>view.size||offset>total||(!requested&&offset))return reject(8);
    const size_t count=total-offset>1372?1372:total-offset;
    header(p,0x88,40+count,now);p.to=from;p16(p.bytes+4,task);
    p32(p.bytes+12,boot_id_);p32(p.bytes+16,session);p16(p.bytes+20,seq);
    p.bytes[22]=1;p.bytes[23]=uint8_t(view.overflow);p32(p.bytes+24,offset);
    p32(p.bytes+28,uint32_t(total));p32(p.bytes+32,model_crc(view.data,total));p16(p.bytes+36,uint16_t(count));
    if(count)std::memcpy(p.bytes+40,view.data+offset,count);
    return true;
}
bool Protocol::receive_parcel(const uint8_t *b,size_t n,Peer from,uint64_t now,Packet &p) {
    if(!have_peer_||!same(from,peer_)){bad_input();return false;}
    const uint16_t seq=u16(b+6);const uint64_t order=packet_order(seq);
    received(seq,now);
    auto reply=[&](unsigned code){ack(p,u16(b+4),seq,uint8_t(code),u32(b+32),now);p.bytes[12]=0x15;return true;};
    if(!accepted_||u16(b+4)!=task_||u32(b+12)!=boot_id_||u32(b+16)!=session_||u32(b+20)!=wcrc()||b[50]!=scene())return reply(8);
    if(parcel_seen_&&order<=parcel_order_) {
        if(order!=parcel_order_||n!=parcel_size_||std::memcmp(b,parcel_request_,8)||std::memcmp(b+12,parcel_request_+12,n-12))return reply(8);
        return reply(0);
    }
    const auto *spec=scene_contract(scene());
    const unsigned points=b[52],mode=b[53];
    if(!spec||b[51]!=spec->classes||points>128||mode>1||u16(b+54)||n!=728+4*points||!u32(b+32))return reply(8);
    const uint32_t pixels=u32(b+36),received=u32(b+40),low=u32(b+44);
    if(pixels>unsigned(spec->width)*spec->height||received>pixels||received>completed_||low>received||
       (mode&&(points<3||!pixels))||(!mode&&(points||pixels||received||low)))return reply(8);
    uint64_t sum=0;for(unsigned i=0;i<24;++i){const uint32_t count=u32(b+56+4*i);if(i>=spec->classes&&count)return reply(8);sum+=count;}
    if(sum!=received)return reply(8);
    ParcelView v{};v.boot=boot_id_;v.session=session_;v.task=task_;v.wcrc=wcrc();v.scene=scene();v.classes=spec->classes;
    v.revision=u32(b+24);v.id=u32(b+28);v.serial=u32(b+32);v.pixels=pixels;v.received=received;v.low=low;
    v.threshold=u16(b+48);v.points=points;v.selected=mode!=0;
    for(unsigned i=0;i<24;++i)v.counts[i]=u32(b+56+4*i);
    for(unsigned i=0;i<points;++i){v.xy[i][0]=u16(b+152+4*i);v.xy[i][1]=u16(b+154+4*i);}
    std::memcpy(v.name_bits,b+152+4*points,576);
    parcel_=v;parcel_pending_=parcel_seen_=true;parcel_order_=order;parcel_size_=n;std::memcpy(parcel_request_,b,n);
    return reply(0);
}
bool Protocol::take_parcel(ParcelView &v) {if(!parcel_pending_)return false;parcel_pending_=false;v=parcel_;return true;}
void Protocol::set_temperature(float current,float peak,bool valid,uint64_t at) {
    temp_valid_=valid&&std::isfinite(current)&&std::isfinite(peak)&&current>=-40&&current<=125&&peak>=current&&peak<=125;
    temp_current_=current;temp_peak_=peak;temp_sampled_=at;++temp_counter_;
    power_.temperature(current,temp_valid_,at);
}
bool Protocol::power_packet(uint64_t now,Packet &p) {
    if(!have_peer_||now-power_sent_<1000000)return false;
    power_sent_=now;const auto value=power_.view(now);
    header(p,0x8c,80,now);p32(p.bytes+12,boot_id_);p32(p.bytes+16,session_);
    p32(p.bytes+20,power_profile::MODEL_ID);p32(p.bytes+24,++power_counter_);p32(p.bytes+28,0);
    p16(p.bytes+32,uint16_t(value.task));
    p16(p.bytes+34,1|(value.temperature_valid?2:0)|(value.active?4:0)|(value.task?8:0));
    p32(p.bytes+36,value.task?completed_:0);
    std::memcpy(p.bytes+40,&value.watts,4);std::memcpy(p.bytes+44,&value.temperature,4);
    std::memcpy(p.bytes+48,&value.joules,8);
    for(unsigned i=0;i<8;++i){p.bytes[56+i]=uint8_t(value.duration_us>>(8*i));p.bytes[64+i]=uint8_t(value.fallback_us>>(8*i));}
    p32(p.bytes+72,value.task?total():0);p32(p.bytes+76,0);return true;
}
bool Protocol::temperature_packet(uint64_t now,Packet &p) {
    if(!have_peer_||now-temp_sent_<1000000)return false;
    temp_sent_=now;header(p,0x89,40,now);p32(p.bytes+12,boot_id_);p32(p.bytes+16,session_);
    p32(p.bytes+20,temp_counter_);p32(p.bytes+24,uint32_t((now-temp_sampled_)/1000));
    std::memcpy(p.bytes+28,&temp_current_,4);std::memcpy(p.bytes+32,&temp_peak_,4);
    p32(p.bytes+36,temp_valid_&&now-temp_sampled_<3000000?1:0);return true;
}
bool Protocol::take_mirror(uint32_t &request,uint32_t &offset) {
    if(!mirror_pending_)return false;
    mirror_pending_=false;request=mirror_id_;offset=mirror_offset_;return true;
}
bool Protocol::queue_key(unsigned key,unsigned gesture,uint64_t now) {
    if(!startup_ready_||(key!=5&&key!=6)||gesture<1||gesture>3||key_pending_||local_key_claimed_)return false;
    ++key_id_;if(!key_id_)++key_id_;
    key_=key;gesture_=gesture;key_state_=1;key_code_=0;key_sent_=0;key_started_=now;
    key_task_=task_;
    key_scene_=scene_selected_?selected_scene_:models_&&models_->active()?models_->active()->key.scene:scene();
    dispatch_.source=key;dispatch_.gesture=gesture;dispatch_.event=key_id_;dispatch_.task=task_;
    dispatch_.action=gesture==3?DispatchAction::scene:key==5?(gesture==1?DispatchAction::point:DispatchAction::scan):
        gesture==1?DispatchAction::region:DispatchAction::parcel;
    dispatch_.phase=DispatchPhase::waiting;
    key_pending_=true;return true;
}
bool Protocol::local_busy() const {
    return pending_||(accepted_&&!done_&&!stopped_)||control_||model_pending_||(probe_seen_&&!probe_ready_);
}
bool Protocol::take_local_key(uint64_t now,KeyEvent &event) {
    tick(now);
    if(!key_pending_||local_key_claimed_||(!local_owner_&&peer_online(now))||model_pending_)return false;
    // If the PC already STARTed this gesture, continuing the accepted job is
    // sufficient. Never create a second task after losing its final receipt.
    if(!local_owner_&&gesture_!=3&&dispatch_.event==key_id_&&
       (task_!=key_task_||(probe_key_event_&&probe_key_event_==key_id_))) {
        key_pending_=false;key_state_=3;key_code_=0;return false;
    }
    key_pending_=false;local_key_claimed_=true;local_owner_=true;
    key_state_=2;key_code_=13;event={key_,gesture_};
    dispatch_.source=key_;dispatch_.gesture=gesture_;dispatch_.event=key_id_;
    dispatch_.phase=DispatchPhase::received;return true;
}
bool Protocol::request_local_stop() {
    if(!local_owner_||failed_||model_pending_||pending_||(probe_seen_&&!probe_ready_))return false;
    if(accepted_&&!done_&&!stopped_){control_=last_control_=2;control_seq_=0;}
    return true;
}
bool Protocol::local_probe_context(unsigned selected) const {
    return local_owner_&&local_key_claimed_&&taken_&&!pending_&&!model_pending_&&!control_&&!failed_&&!job_error_&&
        !(probe_seen_&&!probe_ready_)&&selected==scene()&&(!scene_selected_||selected_scene_==scene());
}
bool Protocol::begin_local_probe(unsigned row,unsigned col) {
    if(!local_probe_context(key_scene_))return false;
    const auto *spec=scene_contract(scene());if(!spec||row>=spec->height||col>=spec->width)return false;
    local_probe_=true;probe_seen_=probe_pending_=true;probe_ready_=false;probe_error_=0;
    probe_row_=uint16_t(row);probe_col_=uint16_t(col);probe_seq_=uint16_t(key_id_);
    probe_scene_=uint8_t(scene());probe_crc_=probe_requested_crc_=wcrc();
    probe_key_event_=key_id_;
    probe_attention_requested_=probe_attention_valid_=false;probe_fragment_=2;
    dispatch_.task=task_;dispatch_.action=DispatchAction::point;dispatch_.phase=DispatchPhase::running;return true;
}
bool Protocol::begin_local_task(const LocalKeyPlan &plan,uint32_t crc,uint64_t now) {
    if(!local_owner_||!local_key_claimed_||local_busy()||failed_||!models_||models_->faulted())return false;
    const auto *spec=scene_contract(plan.scene);const auto *model=models_->find(plan.scene,1,crc);
    if(!spec||!model||!models_->companion(*model)||!plan.width||!plan.height||
       plan.x>=spec->width||plan.y>=spec->height||plan.width>spec->width-plan.x||plan.height>spec->height-plan.y)return false;
    uint16_t task=task_;unsigned attempts=0;
    do{++task;if(!task)++task;}while((used_tasks_[task/8]&(1u<<(task%8)))&&++attempts<65535);
    if(attempts>=65535)return false;
    if(!session_)session_=(boot_id_^0xa53c4e21u)?(boot_id_^0xa53c4e21u):1;
    if(store_&&!store_->begin(session_,task,crc,plan.x,plan.y,plan.width,plan.height,plan.scene,model->key.tag))return false;
    if(logs_&&!logs_->begin(session_,task))return false;
    std::memset(request_,0,sizeof(request_));request_[0]=plan.action==DispatchAction::scan?0:1;request_[1]=uint8_t(plan.scene);
    p16(request_+4,uint16_t(plan.y));p16(request_+6,uint16_t(plan.x));
    p16(request_+8,uint16_t(plan.height));p16(request_+10,uint16_t(plan.width));p32(request_+12,crc);p32(request_+16,session_);
    task_=task;start_seq_=0;accepted_=pending_=true;taken_=done_=paused_=stopped_=false;
    local_probe_=false;
    have_status_=false;completed_=0;compute_us_=0;job_error_=0;control_=last_control_=0;
    probe_seen_=probe_pending_=probe_ready_=control_seen_=false;parcel_seen_=parcel_pending_=false;
    scene_selected_=false;used_tasks_[task/8]|=uint8_t(1u<<(task%8));power_.begin(task,now);
    dispatch_.task=task;dispatch_.action=plan.action;dispatch_.phase=DispatchPhase::preparing;task_dispatch_=dispatch_;return true;
}
void Protocol::complete_local_key(bool ok,unsigned code,unsigned selected_scene) {
    if(!local_key_claimed_)return;
    local_key_claimed_=false;key_state_=ok?3:4;key_code_=code;
    if(ok&&selected_scene<3){key_scene_=selected_scene;selected_scene_=selected_scene;scene_selected_=true;key_task_=task_;dispatch_.phase=DispatchPhase::selected;}
    else if(!ok)dispatch_.phase=DispatchPhase::failed;
}
void Protocol::release_local_owner() {
    // Explicit PC reconnect only, after local completion. Keep result slots,
    // model residency, selected scene and display pixels; no implicit START.
    // Retain the terminal descriptor as well as the power integral. Clearing
    // only task_/completed_ produces a task-0 header around task-N telemetry.
    // The explicit host handoff already records N and chooses N+1 for START.
    local_owner_=false;
    local_probe_=false;
    probe_seen_=probe_pending_=probe_ready_=false;parcel_seen_=parcel_pending_=false;
    mirror_pending_=false;replay_task_=0;
    have_rx_=have_status_=false;
    if(dispatch_.action!=DispatchAction::scene)dispatch_.phase=DispatchPhase::done;
}
void Protocol::command_display(DispatchAction action,unsigned task) {
    const bool physical=key_pending_&&key_state_<=2&&gesture_!=3;
    dispatch_.source=physical?key_:0;dispatch_.gesture=physical?gesture_:0;
    dispatch_.event=physical?key_id_:0;dispatch_.task=task;
    dispatch_.action=physical?(key_==5?(gesture_==1?DispatchAction::point:DispatchAction::scan):
        gesture_==1?DispatchAction::region:DispatchAction::parcel):action;
    dispatch_.phase=DispatchPhase::received;
}
DispatchView Protocol::dispatch_view() const {
    auto v=dispatch_;
    // A rejected extra key or a completed probe must not hide the still-active
    // scan underneath it, including its original PC/terminal ownership.
    if(accepted_&&!done_&&!stopped_&&!failed_&&!job_error_&&
       ((key_state_==4&&v.event==key_id_)||(v.action==DispatchAction::point&&probe_ready_&&(!local_owner_||local_probe_))))v=task_dispatch_;
    if(key_pending_) {
        v.source=key_;v.gesture=gesture_;v.event=key_id_;
        v.action=gesture_==3?DispatchAction::scene:key_==5?(gesture_==1?DispatchAction::point:DispatchAction::scan):
            gesture_==1?DispatchAction::region:DispatchAction::parcel;
        v.phase=key_state_==1?DispatchPhase::waiting:gesture_==3?DispatchPhase::received:DispatchPhase::preparing;
    } else if(v.task==task_&&v.action!=DispatchAction::none&&v.action!=DispatchAction::scene) {
        if(failed_||job_error_)v.phase=DispatchPhase::failed;
        else if(v.action==DispatchAction::point) {
            // Explicit terminal handoff closes the old observation channel;
            // lack of a pending probe is not a new running point command.
            if(v.phase!=DispatchPhase::done||probe_seen_)
                v.phase=local_owner_&&!local_probe_?(done_?DispatchPhase::done:DispatchPhase::running):
                    probe_ready_?(probe_error_?DispatchPhase::failed:DispatchPhase::done):DispatchPhase::running;
        }
        else if(control_)v.phase=DispatchPhase::received;
        else if(stopped_)v.phase=DispatchPhase::stopped;
        else if(paused_)v.phase=DispatchPhase::paused;
        else if(done_)v.phase=DispatchPhase::done;
        else v.phase=completed_?DispatchPhase::running:DispatchPhase::preparing;
    }
    if(v.event==key_id_&&key_state_==4)v.phase=DispatchPhase::failed;
    return v;
}
bool Protocol::key_packet(uint64_t now,Packet &p) {
    if(!key_pending_||local_owner_)return false;
    if(!peer_online(now))return false; // foreground local fallback owns offline timeout handling
    if(now-key_started_>(key_state_==1?5000000ULL:180000000ULL)){
        key_pending_=false;key_code_=key_state_==1?1:4;key_state_=4;return false;
    }
    if(!peer_online(now)||now-key_sent_<250000)return false;
    key_sent_=now;header(p,0x8b,28,now);p32(p.bytes+12,boot_id_);p32(p.bytes+16,session_);
    p32(p.bytes+20,key_id_);p.bytes[24]=uint8_t(key_);p.bytes[25]=uint8_t(gesture_);p.bytes[26]=uint8_t(key_scene_);return true;
}
void Protocol::mirror_reply(uint32_t total,uint32_t crc,const uint8_t *data,unsigned count,uint64_t now,Packet &p) {
    if(!data||!count||count>1372){ack(p,task_,mirror_seq_,8,mirror_id_,now);p.bytes[12]=0x16;return;}
    header(p,0x8a,40+count,now);p32(p.bytes+12,boot_id_);p32(p.bytes+16,session_);p32(p.bytes+20,mirror_id_);
    p32(p.bytes+24,total);p32(p.bytes+28,mirror_offset_);p32(p.bytes+32,crc);p16(p.bytes+36,1920);p16(p.bytes+38,1080);
    std::memcpy(p.bytes+40,data,count);
}
bool Protocol::receive(const uint8_t *b,size_t n,Peer from,uint64_t now,Packet &p) {
    p.size=0; tick(now);
    if(!b || n<12 || u16(b)!=0x4548 || b[3]!=1 || !from.ipv4 || !from.port ||
       !((b[2]==5 && n==16)||(b[2]==1 && n==32)||(b[2]==9 && n==24)||
         (lifecycle_ && b[2]>=2 && b[2]<=4 && n==12)||
         (lifecycle_ && b[2]==6 && n>=16 && n<=1412)||
         (lifecycle_ && b[2]==7 && n==12)||
         (lifecycle_ && logs_ && b[2]==0x14 && n==28)||
         (lifecycle_ && b[2]==0x15 && n>=728 && n<=1240)||
         (lifecycle_ && b[2]==0x16 && n==28)||
         (lifecycle_ && b[2]==0x17 && n==28)||
         (lifecycle_ && models_ && ((b[2]==0x10 && n>28 && n<=1412)||(b[2]==0x11 && n==40)||
                                  (b[2]==0x12 && n==16)||(b[2]==0x13 && n==20))))) { bad_input(); return false; }
    const uint16_t seq=u16(b+6);
    if(b[2]==0x14)return receive_log(b,from,now,p);
    if(logs_&&!startup_ready_&&b[2]!=7){ack(p,u16(b+4),seq,9,0,now);p.bytes[12]=b[2];p.to=from;return true;}
    // Late PC receipts, STARTs or model/control packets cannot duplicate or
    // overwrite an offline key action. INFO remains genuinely read-only.
    if(local_owner_&&b[2]!=7&&b[2]!=5&&b[2]!=0x16){ack(p,u16(b+4),seq,9,0,now);p.bytes[12]=b[2];p.to=from;return true;}
    if(b[2]>=0x10&&b[2]<=0x13)return receive_model(b,n,from,now,p);
    if(b[2]==0x15)return receive_parcel(b,n,from,now,p);
    if(b[2]==0x17) {
        if(!have_peer_||!same(from,peer_)){bad_input();return false;}
        received(seq,now);
        if(u32(b+12)!=boot_id_||u32(b+16)!=session_||u32(b+20)!=key_id_||
           b[24]<2||b[24]>4||b[26]>2||b[27])return false;
        if(key_state_>=3&&b[24]==2)return false; // delayed receipt cannot undo a terminal result
        if(key_state_>=3&&b[24]==key_state_&&b[25]==key_code_&&b[26]==key_scene_)return false;
        if(b[24]==3&&b[25]==10) {
            key_task_=u16(b+4); // task actually stopped by the shared host owner
            selected_scene_=b[26];scene_selected_=true; // select now, load input on the next real START
        }
        // Physical gestures are delivered once; later result receipts never start a task.
        key_pending_=b[24]==2;key_state_=b[24];key_code_=b[25];key_scene_=b[26];
        if(dispatch_.event==key_id_)dispatch_.phase=b[24]==4?DispatchPhase::failed:
            b[24]==2?DispatchPhase::received:b[25]==10?DispatchPhase::selected:DispatchPhase::done;
        return false;
    }
    if(b[2]==0x16) {
        if(!have_peer_||!same(from,peer_)){bad_input();return false;}
        received(seq,now);
        if(u32(b+12)!=boot_id_||u32(b+16)!=session_||!u32(b+20)||u32(b+24)>=1920u*1080u*4u||u16(b+4)!=task_){ack(p,u16(b+4),seq,8,0,now);p.bytes[12]=0x16;return true;}
        mirror_id_=u32(b+20);mirror_offset_=u32(b+24);mirror_seq_=seq;mirror_pending_=true;return false;
    }
    if(b[2]==7) {
        // Existing v1 INFO layout; queries do not establish a peer, reset the
        // heartbeat, clear a fault, or schedule computation. Only actual
        // validated registry entries are listed, not host/local candidates.
        if(failed_ || (models_&&models_->faulted())) {ack(p,task_,seq,6,0,now);p.bytes[12]=7;p.to=from;return true;}
        const unsigned entries=models_?models_->count():0;
        // ABI4 INFO adds the first 128 bits of the full release SHA256 after
        // the registry. 48 entries remain supported: 60+28*48=1404 <=1412.
        header(p,0x86,60+28*entries,now);p.to=from;p.bytes[19]=uint8_t(entries);
        std::memcpy(p.bytes+44+28*entries,release_tag_,sizeof(release_tag_));
        p32(p.bytes+12,boot_id_);p.bytes[16]=1;p.bytes[17]=4;p.bytes[18]=16;
        p32(p.bytes+20,session_);p16(p.bytes+24,task_);
        p.bytes[43]=local_owner_?1:0; // ABI4 capability: retained terminal task ownership
        if(accepted_) {
            p.bytes[26]=request_[0];p.bytes[27]=request_[1];
            std::memcpy(p.bytes+28,request_+4,8);p32(p.bytes+36,wcrc());
            p16(p.bytes+40,uint16_t(front()));p.bytes[42]=done_?3:(stopped_?0:(paused_?2:1));
        }
        for(unsigned i=0;i<entries;++i) {
            const auto &key=models_->entry(i)->key;uint8_t *e=p.bytes+44+28*i;
            e[0]=key.scene;e[1]=key.kind;p32(e+4,key.bytes);p32(e+8,key.crc);std::memcpy(e+12,key.tag,16);
        }
        return true;
    }
    if(models_&&models_->faulted()) {
        if(!have_peer_||!same(from,peer_)){bad_input();return false;}
        received(seq,now);ack(p,u16(b+4),seq,6,0,now);p.bytes[12]=b[2];return true;
    }
    if(b[2]==6) {
        if(!have_peer_ || !same(from,peer_)){bad_input();return false;}
        received(seq,now);const unsigned ranges=u16(b+12);uint8_t code=0;
        if(!ranges || ranges>349 || u16(b+14) || n!=16+4*ranges)code=8;
        ResultStore::Slot *s=store_?store_->find(session_,u16(b+4)):nullptr;
        if(!code && (!s || failed_))code=7;
        if(!code)for(unsigned i=0;i<ranges;++i) {
            const unsigned row=u16(b+16+4*i),count=u16(b+18+4*i);
            if(!count || row>=s->scene_height || count>s->scene_height-row)code=8;
        }
        unsigned count=0;
        if(!code) {
            std::memset(replay_rows_,0,sizeof(replay_rows_));replay_task_=s->task;replay_row_=s->y;replay_col_=s->x;
            for(unsigned i=0;i<ranges;++i)for(unsigned row=u16(b+16+4*i),end=row+u16(b+18+4*i);row<end;++row)
                if(row>=s->y && row<s->front() && !replay_rows_[row]){replay_rows_[row]=true;++count;}
        }
        ack(p,u16(b+4),seq,code,count,now);p.bytes[12]=6;return true;
    }
    if(b[2]>=2 && b[2]<=4) {
        if(!have_peer_ || !same(from,peer_)){bad_input();return false;}
        const uint64_t order=packet_order(seq);received(seq,now);
        uint8_t code=0;
        if(!taken_ || failed_ || u16(b+4)!=task_)code=9;
        else if(control_seen_ && (order<control_order_ || (order==control_order_ && b[2]!=last_control_)))code=8;
        else if(control_ && b[2]!=control_)code=8;
        if(code){ack(p,u16(b+4),seq,code,0,now);p.bytes[12]=b[2];return true;}
        // Duplicate command after application only replies, never changes state.
        if(control_seen_ && order==control_order_ && !control_) {
            ack(p,task_,seq,0,front(),now);p.bytes[12]=b[2];return true;
        }
        control_=last_control_=b[2];control_seq_=seq;control_seen_=true;control_order_=order;
        // A long key hold stops the old task as part of scene selection; it
        // must not be relabelled as a separate PC instruction.
        if(!(key_pending_&&gesture_==3))command_display(b[2]==2?DispatchAction::stop:b[2]==3?DispatchAction::pause:DispatchAction::resume,task_);
        // ACK acknowledges scheduling; actual state changes only at the safe
        // row boundary. GCS must reconcile STATUS, never optimistically pause.
        ack(p,task_,seq,0,front(),now);p.bytes[12]=b[2];return true;
    }
    if(b[2]==9) {
        if(!have_peer_ || !same(from,peer_)){bad_input();return false;}
        const uint64_t order=packet_order(seq);received(seq,now);
        uint8_t code=0;
        if((!done_ && !(lifecycle_ && taken_)) || failed_ || u16(b+4)!=task_)code=9;
        const auto *spec=scene_contract(b[12]);
        if(!code && (!spec || (!models_ && b[12]) || (b[13]&~(lifecycle_?1:0)) || u16(b+18) ||
           u16(b+14)>=spec->height || u16(b+16)>=spec->width || model_pending_))code=8;
        if(code){ack(p,u16(b+4),seq,code,0,now);p.bytes[12]=9;return true;}
        if(probe_seen_ && (order==probe_order_ || (seq==probe_seq_ && !probe_ready_))) {
            if(probe_row_!=u16(b+14)||probe_col_!=u16(b+16)||probe_scene_!=b[12]||probe_requested_crc_!=u32(b+20)||probe_attention_requested_!=bool(b[13]&1))
                {ack(p,task_,seq,8,0,now);p.bytes[12]=9;return true;}
            if(probe_ready_) {
                if(probe_error_){ack(p,task_,seq,6,uint32_t(probe_error_),now);p.bytes[12]=9;}
                else probe_reply(probe_word_,probe_logits_,now,p);
                return true;
            }
            return false; // same in-flight request never reruns
        }
        // take_probe clears the queue bit, NOT the exclusive in-flight owner.
        // Compare request sequence numbers modulo 16 bits, including wrap.
        if(probe_seen_ && (!probe_ready_ || order<probe_order_)) {
            ack(p,task_,seq,8,0,now);p.bytes[12]=9;return true;
        }
        uint32_t crc=u32(b+20);
        if(models_) {
            if(!crc&&models_->active()&&models_->active()->key.scene==b[12])crc=models_->active()->key.crc;
            const auto *e=models_->find(b[12],1,crc);
            if(!e||!models_->companion(*e))code=5;
        } else if(crc!=WCRC)code=5;
        if(code){ack(p,task_,seq,code,0,now);p.bytes[12]=9;return true;}
        probe_seen_=probe_pending_=true;probe_ready_=false;probe_seq_=seq;probe_row_=u16(b+14);probe_col_=u16(b+16);
        command_display(DispatchAction::point,task_);
        probe_key_event_=dispatch_.event;
        probe_attention_requested_=bool(b[13]&1);probe_attention_valid_=false;probe_fragment_=2;probe_attention_crc_=0;
        probe_scene_=b[12];probe_crc_=crc;probe_requested_crc_=u32(b+20);probe_error_=0;probe_order_=order;
        return false;
    }
    const uint32_t session=u32(b+(b[2]==5?12:28));
    if(b[2]==5) {
        if(local_owner_) {
            if(u16(b+4)!=65535||local_busy()||local_key_claimed_){ack(p,u16(b+4),seq,9,0,now);p.bytes[12]=5;p.to=from;return true;}
            release_local_owner();
        }
        // Explicit host recovery first verifies INFO's boot/task/CRC, then
        // reuses its persisted session. Never steal a live peer or change the
        // task identity. A stale old owner cannot reclaim an online channel.
        if(accepted_ && (failed_ || session!=session_ || (!same(from,peer_) && (!lifecycle_ || online_)))) { bad_input(); return false; }
        if(models_ && have_peer_ && model_seen_ && (session!=session_ || !same(from,peer_)) &&
           (online_ || (session!=session_ && model_pending_))){bad_input();return false;}
        const bool changed=!have_peer_ || !same(from,peer_) || session!=session_;
        if(changed) { have_rx_=false; have_status_=false; }
        if(changed && session!=session_){model_seen_=false;model_size_=0;}
        if(logs_&&!logs_->begin_model(session)){bad_input();return false;}
        received(seq,now); peer_=from; session_=session; have_peer_=true;
        header(p,0x84,24,now); p16(p.bytes+12,seq); p32(p.bytes+16,u32(b+8)); p32(p.bytes+20,uint32_t(now));
        return true;
    }
    if(!have_peer_ || !same(from,peer_) || session!=session_) { bad_input(); return false; }
    received(seq,now);
    const uint16_t task=u16(b+4);
    if(accepted_ && (!lifecycle_ || task==task_)) {
        const uint8_t code=task!=task_?9:(std::memcmp(b+12,request_,20)?8:(job_error_?6:0));
        if(!code) ++rx_dup_;
        ack(p,task,seq,code,code==6?uint32_t(job_error_):0,now); return true;
    }
    if(lifecycle_ && accepted_ && (failed_ || (!done_ && !stopped_) || control_ ||
       (probe_seen_ && !probe_ready_) || (used_tasks_[task/8]&(1u<<(task%8))))) {
        ack(p,task,seq,9,0,now);return true;
    }
    // Model-enabled App uses the immutable scene contract and registered pair.
    // Legacy one-shot readers retain their exact LongKou subset. No slot fallback.
    uint8_t code=0;
    const unsigned y=u16(b+16),x=u16(b+18),h=u16(b+20),w=u16(b+22);
    const auto *spec=scene_contract(models_?b[13]:0);const uint32_t crc=u32(b+24);
    const bool small=spec && b[12]==1 && (lifecycle_?(x<spec->width && y<spec->height && w && h && w<=spec->width-x && h<=spec->height-y):(h==3 && w==5 && !x && !y));
    const bool scan=spec && b[12]==0 && h==spec->height && w==spec->width && !x && !y;
    const ModelEntry *model=models_?models_->find(b[13],1,crc):nullptr;
    if(!task || (!small && !scan) || (!models_ && b[13]) || b[15] || model_pending_) code=8;
    else if(models_?(!model || !models_->companion(*model)):(crc!=WCRC))code=5;
    if(!code && logs_ && logs_->view(session_,task).valid)code=7;
    if(!code && lifecycle_ && store_ && !store_->begin(session_,task,crc,x,y,w,h,b[13],model?model->key.tag:nullptr))code=7;
    if(!code && logs_ && !logs_->begin(session_,task))code=7;
    if(!code) {
        accepted_=pending_=true; task_=task; start_seq_=seq; have_status_=false;
        power_.begin(task,now);
        command_display(b[12]==0?DispatchAction::scan:DispatchAction::region,task);
        task_dispatch_=dispatch_;
        scene_selected_=false;
        parcel_seen_=parcel_pending_=false;
        if(lifecycle_) {
            used_tasks_[task/8]|=uint8_t(1u<<(task%8));taken_=done_=paused_=stopped_=false;completed_=0;
            compute_us_=0;job_error_=0;
            probe_seen_=probe_pending_=probe_ready_=control_seen_=false;control_=last_control_=0;
        }
        std::memcpy(request_,b+12,20);
    }
    ack(p,task,seq,code,0,now); return true;
}
bool Protocol::take_job() {
    if(!pending_) return false;
    pending_=false; taken_=true; return true;
}
bool Protocol::finish(size_t completed,uint64_t now) {
    if(!taken_ || done_ || failed_ || completed!=total()) return false;
    completed_=uint32_t(completed);
    done_=true; have_status_=false;
    power_.finish(now);
    if(store_)store_->find(session_,task_)->state=3;
    return true;
}
bool Protocol::progress(size_t completed) {
    if(!taken_ || done_ || failed_ || completed<completed_ || completed>total())return false;
    if(store_ && store_->find(session_,task_)->completed!=completed)return false;
    completed_=uint32_t(completed);return true;
}
bool Protocol::record_compute(uint64_t us,size_t completed) {
    if(!lifecycle_ || !taken_ || failed_ || !completed || completed!=completed_ || !us || us<compute_us_)return false;
    compute_us_=us;return true;
}
float Protocol::compute_ms_per_pixel() const {
    return lifecycle_ && completed_ && compute_us_ && !failed_?
        float(double(compute_us_)/(1000.0*completed_)):std::numeric_limits<float>::quiet_NaN();
}
bool Protocol::apply_control(uint64_t now,Packet &p) {
    p.size=0;
    if(!control_ || failed_ || completed_%width())return false;
    if(!done_ && !stopped_) {
        if(control_==2){stopped_=true;paused_=false;power_.finish(now);}
        else paused_=control_==3;
    }
    ack(p,task_,control_seq_,0,front(),now);p.bytes[12]=control_;
    if(store_)store_->find(session_,task_)->state=done_?3:stopped_?0:paused_?2:1;
    control_=0;have_status_=false;return true;
}
bool Protocol::replay(uint64_t now,Packet &p) {
    tick(now);p.size=0;
    if(!store_ || !online_ || failed_)return false;
    auto *s=store_->find(session_,replay_task_);if(!s)return false;
    while(replay_row_<s->front() && !replay_rows_[replay_row_]){++replay_row_;replay_col_=s->x;}
    if(replay_row_>=s->front())return false;
    const unsigned remaining=s->x+s->width-replay_col_,n=remaining<ROW_MAX?remaining:ROW_MAX;
    header(p,0x81,20+4*n,now);p16(p.bytes+4,s->task);p16(p.bytes+12,replay_row_);p16(p.bytes+14,replay_col_);
    p16(p.bytes+16,n);p16(p.bytes+18,1);
    for(unsigned i=0;i<n;++i)p32(p.bytes+20+4*i,s->words[replay_row_*s->scene_width+replay_col_+i]);
    replay_col_+=n;if(replay_col_==s->x+s->width){replay_rows_[replay_row_]=false;++replay_row_;replay_col_=s->x;}
    ++tx_retx_;return true;
}
void Protocol::failure(int rc,uint64_t now,Packet &p) {
    power_.finish(now);
    pending_=false;failed_=true;job_error_=rc;if(models_)models_->fault(rc);ack(p,task_,start_seq_,6,uint32_t(rc),now);
}
void Protocol::reject_job(int rc,uint64_t now,Packet &p) {
    power_.finish(now);
    pending_=false;taken_=false;stopped_=true;paused_=false;job_error_=rc;have_status_=false;
    if(store_) {auto *s=store_->find(session_,task_);if(s)s->state=0;}
    ack(p,task_,start_seq_,6,uint32_t(rc),now);
}
bool Protocol::row(unsigned y,const uint32_t *words,uint64_t now,Packet &p) {
    return row_segment(y,0,width(),words,now,p);
}
bool Protocol::row_segment(unsigned y,unsigned col,unsigned n,const uint32_t *words,uint64_t now,Packet &p) {
    tick(now); p.size=0;
    if(!taken_ || failed_ || !online_ || !words || y<this->y() || y-this->y()>=height() || !n || n>ROW_MAX ||
       col<x() || col-x()>=width() || n>width()-(col-x()) || (y-this->y()+1)*width()>completed_) return false;
    header(p,0x81,20+4*n,now); p16(p.bytes+12,uint16_t(y));
    p16(p.bytes+14,uint16_t(col)); p16(p.bytes+16,uint16_t(n));
    for(unsigned x=0;x<n;++x) p32(p.bytes+20+x*4,words[x]);
    return true;
}
bool Protocol::status(uint64_t now,Packet &p) {
    tick(now); p.size=0;
    if(!have_peer_ || (have_status_ && now-last_status_<(online_?250000u:1000000u))) return false;
    have_status_=true; last_status_=now; header(p,0x82,92,now);
    p32(p.bytes+12,completed_); p32(p.bytes+16,accepted_?total():0);
    for(unsigned i=20;i<=28;i+=4) p32(p.bytes+i,0x7fc00000u); // explicitly unmeasured
    const float ms=compute_ms_per_pixel();std::memcpy(p.bytes+20,&ms,sizeof(ms));
    p.bytes[32]=done_?3:stopped_?0:paused_?2:(accepted_?1:0); // existing v1 state values
    uint8_t *t=p.bytes+36; p32(t,boot_id_); p32(t+4,session_); p32(t+8,wcrc());
    p16(t+12,uint16_t(front())); t[14]=online_?1:0;
    p32(t+16,tx_pkts_); p32(t+20,tx_bytes_); p32(t+24,tx_fail_);
    p32(t+28,tx_retx_);
    p32(t+32,rx_pkts_); p32(t+36,rx_bad_); p32(t+40,rx_gap_); p32(t+44,rx_dup_);
    p16(t+48,down_cnt_); p32(t+52,uint32_t((down_total_+(online_?0:now-down_since_))/1000));
    return true;
}
void Protocol::sent(size_t bytes,bool ok) {
    if(ok) { ++tx_pkts_; tx_bytes_+=uint32_t(bytes); } else ++tx_fail_;
}
bool Protocol::take_probe(unsigned &row,unsigned &col,uint16_t &seq) {
    if(!probe_pending_)return false;
    probe_pending_=false;row=probe_row_;col=probe_col_;seq=probe_seq_;return true;
}
bool Protocol::cache_attention(const uint32_t *words,size_t n) {
    if(!probe_seen_||probe_ready_||!probe_attention_requested_||!words||n!=432)return false;
    for(unsigned row=0;row<72;++row){uint64_t sum=0;
        for(unsigned col=0;col<6;++col){uint32_t v=words[row*6+col];if(v>(1u<<24))return false;sum+=v;}
        if(sum<(1u<<24)-64||sum>(1u<<24)+64)return false;
    }
    std::memcpy(probe_attention_,words,sizeof(probe_attention_));
    probe_attention_crc_=model_crc(reinterpret_cast<const uint8_t *>(probe_attention_),sizeof(probe_attention_));
    probe_attention_valid_=true;return true;
}
bool Protocol::attention_fragment(uint64_t now,Packet &p) {
    if(!probe_seen_||!probe_ready_||!probe_attention_valid_||probe_error_||failed_||probe_fragment_>=2)return false;
    const unsigned fragment=probe_fragment_++,offset=fragment*216;
    header(p,0x87,48+216*4,now);
    p16(p.bytes+12,probe_seq_);p.bytes[14]=probe_scene_;p.bytes[15]=uint8_t(probe_classes());
    p16(p.bytes+16,probe_row_);p16(p.bytes+18,probe_col_);p32(p.bytes+20,probe_crc_);
    p32(p.bytes+24,boot_id_);p32(p.bytes+28,session_);p32(p.bytes+32,probe_attention_crc_);
    p16(p.bytes+36,432);p.bytes[38]=uint8_t(fragment);p.bytes[39]=2;p16(p.bytes+40,uint16_t(offset));p16(p.bytes+42,216);
    p.bytes[44]=12;p.bytes[45]=6;p.bytes[46]=24;
    for(unsigned n=0;n<216;++n)p32(p.bytes+48+4*n,probe_attention_[offset+n]);
    return true;
}
void Protocol::probe_reply(uint32_t word,const int32_t logits[9],uint64_t now,Packet &p) {
    if(probe_attention_requested_&&!probe_attention_valid_){probe_failure(-420,now,p);return;}
    if(probe_attention_valid_)probe_fragment_=0;
    const unsigned classes=probe_classes();
    probe_word_=word;for(unsigned i=0;i<classes;++i)probe_logits_[i]=logits[i];probe_ready_=true;probe_error_=0;
    header(p,0x85,28+4*classes,now);p16(p.bytes+12,probe_seq_);p.bytes[14]=probe_scene_;p.bytes[15]=uint8_t(classes);
    p16(p.bytes+16,probe_row_);p16(p.bytes+18,probe_col_);p32(p.bytes+20,probe_crc_);p32(p.bytes+24,word);
    for(unsigned i=0;i<classes;++i)p32(p.bytes+28+4*i,uint32_t(logits[i]));
}
void Protocol::probe_failure(int rc,uint64_t now,Packet &p,bool fatal) {
    probe_attention_valid_=false;probe_fragment_=2;probe_attention_crc_=0;
    probe_ready_=true;probe_error_=rc;
    if(fatal){failed_=true;if(models_)models_->fault(rc);}
    ack(p,task_,probe_seq_,6,uint32_t(rc),now);p.bytes[12]=9;
}
}
