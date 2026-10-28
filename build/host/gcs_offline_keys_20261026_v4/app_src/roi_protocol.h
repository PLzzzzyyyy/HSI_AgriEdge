#ifndef S2C_ROI_PROTOCOL_H
#define S2C_ROI_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#include "roi_results.h"
#include "roi_canvas.h"
#include "roi_power.h"
#include "roi_keys.h"
// Private App v1 implementation. Legacy mode preserves one-shot readers/tests.
namespace s2c {
class BoardLog;
constexpr uint32_t WCRC=0x27231983u;
struct Peer { uint32_t ipv4; uint16_t port; };
constexpr unsigned SCENE_W=400, SCENE_H=550, ROW_MAX=348;
struct Packet { Peer to; size_t size; uint8_t bytes[1412]; };
class Protocol {
public:
    explicit Protocol(uint32_t boot_id,bool lifecycle=false,ResultStore *store=nullptr,Models *models=nullptr,const char *release=nullptr,BoardLog *logs=nullptr);
    void mark_startup_ready(){if(release_bound_)startup_ready_=true;}
    bool receive(const uint8_t *,size_t,Peer,uint64_t,Packet &);
    bool take_job(); // exactly once, outside the lwIP callback
    bool finish(size_t completed,uint64_t now=0);
    bool progress(size_t completed);
    bool record_compute(uint64_t cumulative_us,size_t completed);
    float compute_ms_per_pixel() const;
    void failure(int rc,uint64_t,Packet &); // ACK 6 then App parks, no fake DONE
    void reject_job(int rc,uint64_t,Packet &); // pre-DMA failure, no permanent driver-fault claim
    bool model_poll(ModelPersistence &,ModelActivation &,uint64_t,Packet &); // foreground ONLY
    uint32_t model_command_crc() const;
    bool release_bound() const {return release_bound_;}
    bool row(unsigned y,const uint32_t *words,uint64_t,Packet &);
    bool row_segment(unsigned y,unsigned col,unsigned n,const uint32_t *,uint64_t,Packet &);
    bool status(uint64_t,Packet &);
    bool apply_control(uint64_t,Packet &); // foreground, after a committed row ONLY
    bool replay(uint64_t,Packet &); // one packet, foreground only
    unsigned front() const {return y()+completed_/width();}
    bool paused() const {return paused_;}
    bool stopped() const {return stopped_;}
    bool running() const {return taken_ && !done_ && !paused_ && !stopped_ && !failed_;}
    bool take_probe(unsigned &row,unsigned &col,uint16_t &seq);
    unsigned probe_scene() const {return probe_scene_;}
    unsigned probe_classes() const {return scene_contract(probe_scene_)->classes;}
    uint32_t probe_wcrc() const {return probe_crc_;}
    bool probe_wants_attention() const {return probe_attention_requested_;}
    bool cache_attention(const uint32_t *,size_t words);
    bool attention_fragment(uint64_t,Packet &);
    uint32_t attention_crc() const {return probe_attention_crc_;}
    void probe_reply(uint32_t word,const int32_t logits[9],uint64_t,Packet &);
    void probe_failure(int rc,uint64_t,Packet &,bool fatal=true);
    void sent(size_t bytes,bool ok);
    void bad_input() { ++rx_bad_; }
    uint16_t task() const { return task_; }
    uint32_t session() const { return session_; }
    unsigned scene() const {return request_[1];}
    uint32_t wcrc() const;
    uint32_t received_count() const { return rx_pkts_; } // private App S3 diagnostics
    bool full_scene() const { return request_[0]==0; }
    bool peer_seen() const {return have_peer_;}
    bool take_parcel(ParcelView &view);
    void set_temperature(float current,float peak,bool valid,uint64_t sampled_at);
    bool temperature_packet(uint64_t now,Packet &);
    bool power_packet(uint64_t now,Packet &);
    PowerView power_view(uint64_t now) {return power_.view(now);}
    bool take_mirror(uint32_t &request,uint32_t &offset);
    void mirror_reply(uint32_t total,uint32_t crc,const uint8_t *,unsigned count,uint64_t,Packet &);
    bool queue_key(unsigned key,unsigned gesture,uint64_t now);
    bool key_packet(uint64_t now,Packet &);
    bool take_local_key(uint64_t now,KeyEvent &);
    bool begin_local_task(const LocalKeyPlan &,uint32_t crc,uint64_t now);
    bool local_probe_context(unsigned scene) const;
    bool begin_local_probe(unsigned row,unsigned col);
    bool request_local_stop();
    void complete_local_key(bool ok,unsigned code=0,unsigned selected_scene=3);
    bool local_owner() const {return local_owner_;}
    bool local_busy() const;
    DispatchView dispatch_view() const;
    unsigned key_state() const {return key_state_;}
    unsigned key_code() const {return key_code_;}
    unsigned key_scene() const {return key_scene_;}
    uint32_t key_id() const {return key_id_;}
    unsigned key_task() const {return key_task_;}
    bool peer_online(uint64_t now) const {return have_peer_ && online_ && now-last_rx_<1000000;}
    unsigned peer_age_seconds(uint64_t now) const {return have_peer_?unsigned((now-last_rx_)/1000000):0;}
    unsigned x() const {return request_[6]|unsigned(request_[7])<<8;}
    unsigned y() const {return request_[4]|unsigned(request_[5])<<8;}
    unsigned width() const { return lifecycle_ && accepted_?(request_[10]|unsigned(request_[11])<<8):(full_scene()?SCENE_W:5); }
    unsigned height() const { return lifecycle_ && accepted_?(request_[8]|unsigned(request_[9])<<8):(full_scene()?SCENE_H:3); }
    unsigned total() const { return width()*height(); }
private:
    PowerEstimate power_;
    uint64_t power_sent_=0;
    uint32_t power_counter_=0;
    uint32_t key_id_=0;unsigned key_=0,gesture_=0,key_state_=0,key_code_=0,key_scene_=0,key_task_=0;
    uint64_t key_sent_=0,key_started_=0;bool key_pending_=false;
    unsigned selected_scene_=0;bool scene_selected_=false;
    DispatchView dispatch_{};
    DispatchView task_dispatch_{};
    bool local_owner_=false,local_key_claimed_=false,local_probe_=false;
    uint32_t probe_key_event_=0;
    void release_local_owner();
    void command_display(DispatchAction,unsigned task);
    bool receive_parcel(const uint8_t *,size_t,Peer,uint64_t,Packet &);
    ParcelView parcel_{};bool parcel_pending_=false,parcel_seen_=false;
    uint64_t parcel_order_=0,temp_sampled_=0,temp_sent_=0;
    float temp_current_=0,temp_peak_=0;bool temp_valid_=false;
    uint32_t temp_counter_=0;
    uint8_t parcel_request_[1240]={};size_t parcel_size_=0;
    bool mirror_pending_=false;uint32_t mirror_id_=0,mirror_offset_=0;uint16_t mirror_seq_=0;
    uint8_t release_tag_[16]={};bool release_bound_=false;
    void tick(uint64_t);
    void received(uint16_t,uint64_t);
    uint64_t packet_order(uint16_t seq) const;
    void header(Packet &,uint8_t,size_t,uint64_t);
    void ack(Packet &,uint16_t,uint16_t,uint8_t,uint32_t,uint64_t);
    bool receive_model(const uint8_t *,size_t,Peer,uint64_t,Packet &);
    bool receive_log(const uint8_t *,Peer,uint64_t,Packet &);
    uint32_t boot_id_,session_;
    Peer peer_;
    uint16_t task_,tx_seq_,rx_seq_,start_seq_,down_cnt_;
    bool have_peer_,online_,have_rx_,have_status_,accepted_,pending_,taken_,done_;
    uint64_t last_rx_,last_status_,down_since_,down_total_;
    uint32_t tx_pkts_,tx_bytes_,tx_fail_,rx_pkts_,rx_bad_,rx_gap_,rx_dup_;
    uint8_t request_[20];
    uint32_t completed_;
    bool failed_;
    bool probe_seen_,probe_pending_,probe_ready_;
    uint16_t probe_seq_,probe_row_,probe_col_;
    uint32_t probe_word_;
    int32_t probe_logits_[24];
    uint8_t probe_scene_=0;
    uint32_t probe_crc_=WCRC,probe_requested_crc_=WCRC;
    int probe_error_=0,job_error_=0;
    bool probe_attention_requested_=false,probe_attention_valid_=false;
    unsigned probe_fragment_=2;
    uint32_t probe_attention_[432]={},probe_attention_crc_=0;
    bool lifecycle_,paused_,stopped_,control_seen_;
    uint8_t control_,last_control_,used_tasks_[8192];
    uint16_t control_seq_;
    ResultStore *store_;
    bool replay_rows_[MODEL_MAX_HEIGHT];
    uint16_t replay_task_,replay_row_,replay_col_;
    uint32_t tx_retx_;
    uint64_t compute_us_;
    Models *models_;
    BoardLog *logs_;bool startup_ready_;
    bool model_seen_=false,model_pending_=false;
    size_t model_size_=0;
    uint8_t model_request_[1412]={};
    ModelReply model_reply_{0,0};
    uint64_t rx_order_=0,model_order_=0,control_order_=0,probe_order_=0;
};
void stamp(Packet &,uint64_t);
}
#endif
