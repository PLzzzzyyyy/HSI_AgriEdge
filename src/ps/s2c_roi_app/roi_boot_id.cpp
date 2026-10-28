#include "roi_boot_id.h"
#include <cstring>
namespace s2c {
namespace {
uint32_t get(const uint8_t *p){return uint32_t(p[0])|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
void put(uint8_t *p,uint32_t v){for(unsigned n=0;n<4;++n)p[n]=uint8_t(v>>(8*n));}
uint32_t crc(const uint8_t *p,unsigned size){uint32_t c=0xffffffffu;for(unsigned i=0;i<size;++i){c^=p[i];for(unsigned n=0;n<8;++n)c=(c>>1)^((0u-(c&1u))&0xedb88320u);}return c^0xffffffffu;}
bool valid(const uint8_t *b,unsigned slot){
    if(get(b)!=0x34444942u||get(b+4)!=1||get(b+20)!=slot||!get(b+8)||
       !(get(b+24)|get(b+28))||get(b+32)!=4)return false;
    const uint64_t id=uint64_t(get(b+8))+get(b+12);
    if(id>0xffffffffu||get(b+16)!=id)return false;
    for(unsigned i=9;i<14;++i)if(get(b+4*i))return false;
    return get(b+56)==crc(b,56)&&get(b+60)==~get(b+56);
}
}
void boot_record(uint8_t *b,unsigned slot,uint32_t base,uint32_t gen,uint32_t lo,uint32_t hi){
    std::memset(b,0,64);put(b,0x34444942u);put(b+4,1);put(b+8,base);put(b+12,gen);put(b+16,base+gen);
    put(b+20,slot);put(b+24,lo);put(b+28,hi);put(b+32,4);put(b+56,crc(b,56));put(b+60,~get(b+56));
}
int reserve_boot_id(BootJournal &io,BootIdentity &out){
    out=BootIdentity{};uint8_t b[2][64],next[64],check[64];
    for(unsigned n=0;n<2;++n){const int rc=io.read(n,b[n]);if(rc)return rc;if(!valid(b[n],n))return -401;}
    const unsigned identity_offsets[]={8,24,28};
    for(unsigned off:identity_offsets)if(get(b[0]+off)!=get(b[1]+off))return -402;
    const uint32_t a=get(b[0]+12),c=get(b[1]+12);
    if((a==c&&a!=0)||(a>c&&a-c!=1)||(c>a&&c-a!=1))return -403;
    const unsigned target=a>=c?1:0;const uint32_t prev=a>c?a:c;
    const uint64_t id=uint64_t(get(b[0]+8))+uint64_t(prev)+1;
    if(prev==0xffffffffu||id>0xffffffffu||id==0||id==0xbb6bd8e3u)return -404;
    boot_record(next,target,get(b[0]+8),prev+1,get(b[0]+24),get(b[0]+28));
    int rc=io.write(target,next);if(rc)return rc;
    // Reopen and compare BOTH: do not trust write, in-memory journal or CRC alone.
    for(unsigned n=0;n<2;++n){rc=io.read(n,check);if(rc)return rc;
        if(std::memcmp(check,n==target?next:b[n],64))return -405;}
    out.boot=uint32_t(id);out.generation=prev+1;out.nonce_lo=get(b[0]+24);out.nonce_hi=get(b[0]+28);return 0;
}
}
