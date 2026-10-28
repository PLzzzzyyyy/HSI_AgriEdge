#include "roi_boot_id.h"
#include "ff.h"
namespace s2c {
namespace {
const char *const paths[]={"1:/boot/jrn0.bin","1:/boot/jrn1.bin"};
class SdJournal:public BootJournal {
public:
    int read(unsigned n,uint8_t *b) override {
        FIL f{};FRESULT rc=f_open(&f,paths[n],FA_READ);if(rc!=FR_OK)return int(rc);
        int error=f_size(&f)==64?0:-410;UINT got=0;
        if(!error){rc=f_read(&f,b,64,&got);if(rc!=FR_OK||got!=64)error=rc!=FR_OK?int(rc):-411;}
        rc=f_close(&f);if(rc!=FR_OK&&!error)error=int(rc);return error;
    }
    int write(unsigned n,const uint8_t *b) override {
        FIL f{};FRESULT rc=f_open(&f,paths[n],FA_WRITE);if(rc!=FR_OK)return int(rc); // OPEN_EXISTING, no truncate/create
        int error=f_size(&f)==64?0:-410;UINT wrote=0;
        if(!error){rc=f_write(&f,b,64,&wrote);if(rc!=FR_OK||wrote!=64)error=rc!=FR_OK?int(rc):-411;}
        if(!error){rc=f_sync(&f);if(rc!=FR_OK)error=int(rc);}
        rc=f_close(&f);if(rc!=FR_OK&&!error)error=int(rc);return error;
    }
};
}
int acquire_sd_boot_id(BootIdentity &out){
    static bool attempted=false;
    out=BootIdentity{};if(attempted)return -412;attempted=true;
    FATFS fs{};int rc=int(f_mount(&fs,"1:/",1));BootIdentity reserved{};SdJournal journal;
    if(!rc)rc=reserve_boot_id(journal,reserved);
    const int cleanup=int(f_mount(nullptr,"1:/",0));if(!rc)rc=cleanup;
    if(!rc)out=reserved;
    return rc; // No READY or network after cleanup failure.
}
}
