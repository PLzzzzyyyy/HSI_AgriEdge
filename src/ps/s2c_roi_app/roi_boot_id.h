#ifndef S2C_ROI_BOOT_ID_H
#define S2C_ROI_BOOT_ID_H
#include <stdint.h>
namespace s2c {
// Provisioned once OFFLINE. Never recreate files, reseed, repair or use a
// surviving slot on-device after any media/record failure. Not anti-rollback
// storage: replacing/cloning the entire card needs a new explicit installation.
struct BootIdentity {uint32_t boot=0,generation=0,nonce_lo=0,nonce_hi=0;};
class BootJournal {
public:
    virtual ~BootJournal() {}
    virtual int read(unsigned slot,uint8_t bytes[64])=0;
    // Existing, preallocated exact-64-byte file: write, sync, close must succeed.
    virtual int write(unsigned slot,const uint8_t bytes[64])=0;
};
void boot_record(uint8_t bytes[64],unsigned slot,uint32_t base,uint32_t generation,uint32_t nonce_lo,uint32_t nonce_hi);
int reserve_boot_id(BootJournal &,BootIdentity &); // output zero on EVERY failure
int acquire_sd_boot_id(BootIdentity &); // mount/reserve/readback/unmount before READY
}
#endif
