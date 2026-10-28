#include "roi_boot_id.h"
#include "ram_fs.h"
#include <cassert>
#include <cstdio>
#include <cstring>
int main(int argc,char **argv){
    assert(argc==2);using namespace s2c;using namespace model_test_fs;
    reset();dirs.insert("1:/boot");
    for(unsigned i=0;i<2;++i){char p[40];std::snprintf(p,sizeof(p),"1:/boot/jrn%u.bin",i);files[p].resize(64);boot_record(files[p].data(),i,0x10203040,0,1,2);}
    const std::string mode=argv[1];
    if(mode=="missing")files.erase("1:/boot/jrn0.bin");
    else if(mode=="corrupt")files["1:/boot/jrn1.bin"][24]^=1;
    else if(mode!="ok")fail=mode;
    BootIdentity id;const int rc=acquire_sd_boot_id(id);
    if(mode=="ok")assert(!rc&&id.boot==0x10203041&&id.generation==1&&writes==1);
    else assert(rc&&id.boot==0&&id.generation==0);
    assert(mounts==1&&unmounts==1&&renames==0);
    const unsigned old_writes=writes;assert(acquire_sd_boot_id(id)!=0&&id.boot==0&&old_writes==writes);
    std::printf("BOOT_SD_PASS %s RAM FatFs, NOT physical SD/power failure evidence\n",argv[1]);
}
