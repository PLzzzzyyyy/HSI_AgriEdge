#include "roi_model_sd.h"
#include "ff.h"
#include <cstdio>
#include <cstring>
namespace s2c {
namespace {
constexpr int SIZE_ERROR=-300,SHORT_IO=-301,CONTENT_ERROR=-302,CAPACITY_ERROR=-303,REENTRY_ERROR=-304;
constexpr unsigned SCAN_DIRECTORY_LIMIT=96;
const char *const names[]={"weights_all.bin","cls_token.bin","pos_embed.bin","classifier_w.bin","classifier_b.bin","weights_engine.bin"};
size_t part_size(unsigned scene,unsigned i) {
    const auto *s=scene_contract(scene);const size_t n[]={289344,10584,63504,size_t(s->classes)*10584,size_t(s->classes)*4,MODEL_ENGINE_BYTES};
    return n[i];
}
struct Owner {bool &busy;explicit Owner(bool &b):busy(b){busy=true;}~Owner(){busy=false;}};
// Mount has stack lifetime, and ALWAYS unregisters, even when mount fails.
struct Mount {
    FATFS fs{};int mounted,cleanup=0;bool open=true;
    Mount():mounted(int(f_mount(&fs,"1:/",1))) {}
    int close(){if(open){cleanup=int(f_mount(nullptr,"1:/",0));open=false;}return cleanup;}
    ~Mount(){(void)close();}
};
}
void ModelSd::error(int rc){if(rc&&!receipt_.status)receipt_.status=rc;}
bool ModelSd::set_service(Service service,void *context) {
    if(busy_)return false;
    service_=service;service_context_=context;return true;
}
bool ModelSd::read_file(const char *path,uint8_t *dst,size_t size,uint32_t *crc_out) {
    FIL f{};FRESULT rc=f_open(&f,path,FA_READ);if(rc!=FR_OK){error(rc);return false;}
    bool good=f_size(&f)==size;if(!good)error(SIZE_ERROR);
    size_t off=0;uint32_t crc=0xffffffffu;
    while(good&&off<size) {
        const size_t remain=size-off;const UINT want=UINT(remain>(1u<<20)?(1u<<20):remain);UINT got=0;
        rc=f_read(&f,dst+off,want,&got);
        if(rc!=FR_OK||got!=want){error(rc!=FR_OK?int(rc):SHORT_IO);good=false;break;}
        if(crc_out)crc=model_crc_update(crc,dst+off,got);
        if(UINT32_MAX-receipt_.bytes<got){error(CAPACITY_ERROR);good=false;break;}
        receipt_.bytes+=got;off+=got;service();
    }
    rc=f_close(&f);if(rc!=FR_OK){receipt_.cleanup_status=int(rc);error(rc);good=false;}
    if(good&&crc_out)*crc_out=crc^0xffffffffu;
    return good;
}
bool ModelSd::same_file(const char *path,const uint8_t *data,size_t size) {
    FIL f{};FRESULT rc=f_open(&f,path,FA_READ);if(rc!=FR_OK){error(rc);return false;}
    bool good=f_size(&f)==size;if(!good)error(SIZE_ERROR);
    size_t off=0;
    while(good&&off<size) {
        const size_t remain=size-off;const UINT want=UINT(remain>sizeof(io_)?sizeof(io_):remain);UINT got=0;
        rc=f_read(&f,io_,want,&got);
        if(rc!=FR_OK||got!=want){error(rc!=FR_OK?int(rc):SHORT_IO);good=false;break;}
        if(std::memcmp(io_,data+off,got)){error(CONTENT_ERROR);good=false;break;}off+=got;service();
    }
    rc=f_close(&f);if(rc!=FR_OK){receipt_.cleanup_status=int(rc);error(rc);good=false;}
    return good;
}
bool ModelSd::directory(const char *path) {
    const FRESULT rc=f_mkdir(path);
    if(rc==FR_OK)return true;
    if(rc==FR_EXIST){FILINFO info{};const FRESULT stat=f_stat(path,&info);if(stat==FR_OK&&(info.fattrib&AM_DIR))return true;error(stat==FR_OK?CONTENT_ERROR:int(stat));}
    else error(rc);
    return false;
}
bool ModelSd::put_file(const char *path,const uint8_t *data,size_t size) {
    FILINFO info{};FRESULT rc=f_stat(path,&info);
    if(rc==FR_OK) { // immutable final names
        if(info.fattrib&AM_DIR){error(CONTENT_ERROR);return false;}
        return same_file(path,data,size);
    }
    if(rc!=FR_NO_FILE){error(rc);return false;}
    char temp[160];const int n=std::snprintf(temp,sizeof(temp),"%s.tmp",path);
    if(n<0||size_t(n)>=sizeof(temp)){error(CAPACITY_ERROR);return false;}
    FIL f{};rc=f_open(&f,temp,FA_WRITE|FA_CREATE_ALWAYS);if(rc!=FR_OK){error(rc);return false;}
    size_t off=0;bool good=true;
    while(good&&off<size) {
        const size_t remain=size-off;const UINT want=UINT(remain>sizeof(io_)?sizeof(io_):remain);UINT wrote=0;
        rc=f_write(&f,data+off,want,&wrote);
        if(rc!=FR_OK||wrote!=want){error(rc!=FR_OK?int(rc):SHORT_IO);good=false;break;}off+=wrote;service();
    }
    if(good){rc=f_sync(&f);if(rc!=FR_OK){error(rc);good=false;}}
    rc=f_close(&f);if(rc!=FR_OK){receipt_.cleanup_status=int(rc);error(rc);good=false;}
    if(!good)return false; // tmp is NOT a committed package; scan ignores it
    rc=f_rename(temp,path);if(rc!=FR_OK){error(rc);return false;}
    return same_file(path,data,size);
}
bool ModelSd::save(const ModelKey &k,const uint8_t *data) {
    if(busy_){error(REENTRY_ERROR);return false;}
    Owner guard(busy_);receipt_=ModelSdReceipt{};
    if(!model_key(k)||!model_package(k.scene,k.kind,data,k.bytes)||model_crc(data,k.bytes)!=k.crc){error(CONTENT_ERROR);return false;}
    Mount mount;error(mount.mounted);bool good=!receipt_.status;
    char path[160];const auto *scene=scene_contract(k.scene);
    if(good)good=directory("1:/scenes");
    if(good){std::snprintf(path,sizeof(path),"1:/scenes/%s",scene->name);good=directory(path);}
    if(good){std::snprintf(path,sizeof(path),"1:/scenes/%s/weights",scene->name);good=directory(path);}
    if(good){std::snprintf(path,sizeof(path),"1:/scenes/%s/weights/%s",scene->name,k.tag);good=directory(path);}
    size_t off=0;
    for(unsigned i=k.kind?5:0,end=k.kind?6:5;good&&i<end;++i) {
        std::snprintf(path,sizeof(path),"1:/scenes/%s/weights/%s/%s",scene->name,k.tag,names[i]);
        const size_t size=part_size(k.scene,i);good=put_file(path,data+off,size);off+=size;
    }
    const int cleanup=mount.close();if(cleanup){receipt_.cleanup_status=cleanup;error(cleanup);}
    receipt_.complete=good&&!receipt_.status;receipt_.bytes=receipt_.complete?k.bytes:0;receipt_.crc=receipt_.complete?k.crc:0;
    return receipt_.complete;
}
bool ModelSd::scan(Models &models) {
    if(busy_){error(REENTRY_ERROR);return false;}
    Owner guard(busy_);receipt_=ModelSdReceipt{};
    // A cold-start inventory is not an in-place refresh that could leave stale
    // persisted flags in a live registry after a card swap/corruption.
    if(models.count()||models.faulted()){error(REENTRY_ERROR);return false;}
    Mount mount;error(mount.mounted);
    bool good=!receipt_.status;unsigned visited=0;
    for(unsigned s=0;good&&s<3;++s) {
        char root[96];std::snprintf(root,sizeof(root),"1:/scenes/%s/weights",scene_contract(s)->name);
        DIR dir{};FRESULT rc=f_opendir(&dir,root);
        if(rc==FR_NO_PATH||rc==FR_NO_FILE)continue; // absent is not registered
        if(rc!=FR_OK){error(rc);good=false;break;}
        for(;;) {
            FILINFO info{};rc=f_readdir(&dir,&info);
            if(rc!=FR_OK){error(rc);good=false;break;}
            if(!info.fname[0])break;
            if(++visited>SCAN_DIRECTORY_LIMIT){error(CAPACITY_ERROR);good=false;break;}
            if(!(info.fattrib&AM_DIR)||std::strlen(info.fname)>15)continue;
            ModelKey k{};k.scene=uint8_t(s);k.bytes=uint32_t(model_bytes(s,0));k.crc=1;
            std::strcpy(k.tag,info.fname);if(!model_key(k))continue;
            ++receipt_.directories;
            for(unsigned kind=0;kind<2;++kind) {
                k.kind=uint8_t(kind);k.bytes=uint32_t(model_bytes(s,kind));bool read=true;size_t off=0;
                // One damaged/incomplete tag does not advertise its missing
                // files or hide other verified models. Record rejection.
                const int previous=receipt_.status;receipt_.status=0;
                for(unsigned i=kind?5:0,end=kind?6:5;read&&i<end;++i) {
                    char path[160];std::snprintf(path,sizeof(path),"%s/%s/%s",root,k.tag,names[i]);
                    const size_t size=part_size(s,i);read=read_file(path,package_+off,size);off+=size;
                }
                ModelReply result{3,0};
                if(read){k.crc=model_crc(package_,k.bytes);result=models.import(k,package_);}
                if(!read||result.code) {
                    ++receipt_.rejected;receipt_.last_reject_status=receipt_.status;receipt_.last_reject_code=result.code;
                    // Missing/incomplete or malformed packages are rejected
                    // individually. Media/cleanup/capacity faults stop the scan
                    // and remain explicit, not a misleading complete inventory.
                    const bool io_fault=receipt_.status&&receipt_.status!=FR_NO_FILE&&receipt_.status!=FR_NO_PATH&&receipt_.status!=SIZE_ERROR;
                    if(io_fault||receipt_.cleanup_status||result.code==8) {
                        if(!receipt_.status)error(result.code==8?CAPACITY_ERROR:receipt_.cleanup_status);
                        good=false;
                    } else receipt_.status=previous;
                    break;
                }
                ++receipt_.registered;receipt_.status=previous;
            }
            if(!good)break;
        }
        rc=f_closedir(&dir);if(rc!=FR_OK){receipt_.cleanup_status=int(rc);error(rc);good=false;}
    }
    const int cleanup=mount.close();if(cleanup){receipt_.cleanup_status=cleanup;error(cleanup);}
    receipt_.complete=good&&!receipt_.status;return receipt_.complete;
}
bool ModelSd::load_input(unsigned scene,void *dst,size_t capacity) {
    if(busy_){error(REENTRY_ERROR);return false;}
    Owner guard(busy_);receipt_=ModelSdReceipt{};const auto *s=scene_contract(scene);
    if(!s||!dst||capacity<s->cube_bytes){error(CAPACITY_ERROR);return false;}
    Mount mount;error(mount.mounted);char path[96];std::snprintf(path,sizeof(path),"1:/scenes/%s/cube_f32.bin",s->name);
    bool good=!receipt_.status&&read_file(path,static_cast<uint8_t *>(dst),s->cube_bytes,&receipt_.crc);
    if(good&&receipt_.crc!=s->cube_crc){error(CONTENT_ERROR);good=false;}
    const int cleanup=mount.close();if(cleanup){receipt_.cleanup_status=cleanup;error(cleanup);}
    receipt_.complete=good&&!receipt_.status;receipt_.bytes=receipt_.complete?s->cube_bytes:0;return receipt_.complete;
}
}
