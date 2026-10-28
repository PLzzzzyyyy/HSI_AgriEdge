#include "roi_boot_id.h"
#include <cassert>
#include <cstdio>
#include <cstring>
using namespace s2c;
struct Memory:BootJournal {
    uint8_t slots[2][64]{};int fail_read=-1,fail_write=-1,writes=0;
    bool partial=false;
    int read(unsigned n,uint8_t *b) override {if(int(n)==fail_read)return 9;std::memcpy(b,slots[n],64);return 0;}
    int write(unsigned n,const uint8_t *b) override {
        ++writes;if(int(n)==fail_write){if(partial)std::memcpy(slots[n],b,17);return 10;}
        std::memcpy(slots[n],b,64);return 0;
    }
    Memory(){for(unsigned n=0;n<2;++n)boot_record(slots[n],n,0x10203040,0,0x12345678,0x87654321);}
};
int main(){
    Memory m;BootIdentity a{};
    assert(!reserve_boot_id(m,a)&&a.boot==0x10203041&&a.generation==1);
    assert(!reserve_boot_id(m,a)&&a.boot==0x10203042&&a.generation==2&&m.writes==2);
    for(int n=0;n<2;++n){Memory b;b.slots[n][40]^=1;assert(reserve_boot_id(b,a)!=0&&a.boot==0&&b.writes==0);}
    Memory r;r.fail_read=0;assert(reserve_boot_id(r,a)!=0&&a.boot==0&&r.writes==0);
    Memory w;w.fail_write=1;w.partial=true;assert(reserve_boot_id(w,a)!=0&&a.boot==0);
    w.fail_write=-1;assert(reserve_boot_id(w,a)!=0&&a.boot==0); // torn record: never fall back
    Memory gap;boot_record(gap.slots[1],1,0x10203040,3,0x12345678,0x87654321);
    assert(reserve_boot_id(gap,a)!=0&&gap.writes==0);
    Memory mix;boot_record(mix.slots[1],1,0x10203040,0,1,2);assert(reserve_boot_id(mix,a)!=0);
    Memory wrap;for(unsigned n=0;n<2;++n)boot_record(wrap.slots[n],n,0xffffffff,0,1,2);
    assert(reserve_boot_id(wrap,a)!=0&&wrap.writes==0);
    // Reservation followed by crash before READY: next boot skips it, no reuse.
    Memory crash;assert(!reserve_boot_id(crash,a));uint32_t lost=a.boot;
    assert(!reserve_boot_id(crash,a)&&a.boot>lost);
    std::puts("BOOT_JOURNAL_PASS memory only: no UART entropy, torn/IO/mix/gap/wrap closed, reserve before READY");
}
