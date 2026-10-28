#ifndef S2C_ROI_MODEL_SD_H
#define S2C_ROI_MODEL_SD_H
#include "roi_models.h"
namespace s2c {
struct ModelSdReceipt {
    int status=0,cleanup_status=0,last_reject_status=0;
    unsigned last_reject_code=0;
    unsigned directories=0,registered=0,rejected=0;
    uint32_t bytes=0,crc=0;
    bool complete=false;
};
// Uses the existing writable FatFs API only. One foreground owner; never call
// from UDP/wait-service, ISR, while a task/PROBE owns buffers, or after DMA fault.
// A persisted claim requires exact readback AND successful filesystem cleanup.
class ModelSd: public ModelPersistence,public ModelInput {
public:
    // Private foreground network/timer service BETWEEN completed FatFs calls.
    // No recursive SD/IP/task work or access to this object's scratch/dest spans.
    // Not an ISR, driver ABI extension, or a promise about physical SD latency.
    using Service=void (*)(void *);
    bool set_service(Service,void *);
    bool save(const ModelKey &,const uint8_t *) override;
    bool scan(Models &); // bounded real SD reads; no file-name-only registration
    bool load_input(unsigned scene,void *destination,size_t capacity) override;
    int input_error() const override {return receipt_.status;}
    const ModelSdReceipt &receipt() const {return receipt_;}
private:
    bool busy_=false;
    ModelSdReceipt receipt_{};
    Service service_=nullptr;void *service_context_=nullptr;
    uint8_t package_[MODEL_MAX_PART_BYTES],io_[4096]; // CPU only
    bool read_file(const char *,uint8_t *,size_t,uint32_t *crc=nullptr);
    bool same_file(const char *,const uint8_t *,size_t);
    bool put_file(const char *,const uint8_t *,size_t);
    bool directory(const char *);
    void error(int);
    void service(){if(service_)service_(service_context_);}
};
}
#endif
