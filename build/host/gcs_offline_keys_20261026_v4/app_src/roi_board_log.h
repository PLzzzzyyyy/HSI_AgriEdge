#ifndef S2C_ROI_BOARD_LOG_H
#define S2C_ROI_BOARD_LOG_H
// Actual App-emitted records, independent of UART. CPU-only static storage.
// A bounded retained prefix is exported read-only; loss is explicit, never wrap.
#include <cstddef>
#include <cstdint>
#include <cstring>
namespace s2c {
struct LogView {
    const uint8_t *data;size_t size;bool valid,overflow;
    LogView(const uint8_t *p=nullptr,size_t n=0,bool ok=false,bool bad=false):data(p),size(n),valid(ok),overflow(bad){}
};
template<size_t Capacity> class LogBuffer {
    uint8_t bytes_[Capacity];size_t size_=0;bool bad_=false;
public:
    void reset(){size_=0;bad_=false;}
    bool append(const char *line,size_t size,bool complete) {
        if(bad_)return false;
        if(!complete||size>Capacity-size_){bad_=true;return false;}
        std::memcpy(bytes_+size_,line,size);size_+=size;return true;
    }
    LogView view() const{return LogView(bytes_,size_,true,bad_);}
};
class BoardLog {
public:
    static constexpr size_t BOOT_BYTES=4096,TASK_BYTES=65536,LINE_BYTES=384;
private:
    struct Slot {uint32_t session=0;uint16_t task=0;LogBuffer<TASK_BYTES> log;};
    LogBuffer<BOOT_BYTES> boot_;LogBuffer<TASK_BYTES> model_;uint32_t model_session_=0;
    Slot slots_[4];unsigned next_=0;
    uint32_t session_=0;uint16_t task_=0;
public:
    LogView view(uint32_t session,uint16_t task) const {
        if(!session&&!task)return boot_.view();
        if(session&&!task)return session==model_session_?model_.view():LogView();
        if(!session)return LogView();
        for(const auto &slot:slots_)if(slot.session==session&&slot.task==task)return slot.log.view();
        return LogView();
    }
    bool begin_model(uint32_t session) {
        if(!session||(model_session_&&session!=model_session_))return false;
        model_session_=session;return true; // same-session recovery never clears records
    }
    bool append_model(uint32_t session,const char *line) {
        if(!session||session!=model_session_)return false;
        size_t n=0;if(line)while(n<LINE_BYTES&&line[n])++n;
        const bool complete=line&&n<LINE_BYTES&&n>=2&&line[n-2]=='\r'&&line[n-1]=='\n';
        return model_.append(line,n,complete);
    }
    bool begin(uint32_t session,uint16_t task) {
        if(!session||!task||view(session,task).valid)return false;
        Slot &slot=slots_[next_];next_=(next_+1)%4;slot.session=session;slot.task=task;slot.log.reset();
        session_=session;task_=task;return true;
    }
    bool append(const char *line) {
        size_t n=0;if(line)while(n<LINE_BYTES&&line[n])++n;
        const bool complete=line&&n<LINE_BYTES&&n>=2&&line[n-2]=='\r'&&line[n-1]=='\n';
        if(!task_)return boot_.append(line,n,complete);
        for(auto &slot:slots_)if(slot.session==session_&&slot.task==task_)return slot.log.append(line,n,complete);
        return false;
    }
};
}
#endif
