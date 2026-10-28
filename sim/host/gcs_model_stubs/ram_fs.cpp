#include "ram_fs.h"
#include "ff.h"
#include <cassert>
#include <cstring>
namespace model_test_fs {
std::map<std::string,std::vector<uint8_t>> files;
std::set<std::string> dirs;
std::string fail,always_fail;
unsigned writes=0,renames=0,mounts=0,unmounts=0;
bool hit(const char *op){
    if(writes&&((fail=="write_close"&&std::string(op)=="close")||(fail=="readback"&&std::string(op)=="read"))){fail.clear();return true;}
    if(always_fail==op)return true;
    if(fail==op){fail.clear();return true;}
    return false;
}
void reset(){files.clear();dirs.clear();fail.clear();always_fail.clear();writes=renames=mounts=unmounts=0;}
std::string parent(const std::string &p){return p.substr(0,p.rfind('/'));}
}
using namespace model_test_fs;
FRESULT f_mount(FATFS *fs,const char *path,unsigned){assert(std::string(path)=="1:/");if(fs){++mounts;return hit("mount")?FR_DISK_ERR:FR_OK;}++unmounts;return hit("unmount")?FR_DISK_ERR:FR_OK;}
FRESULT f_open(FIL *f,const char *path,unsigned mode) {
    if(hit("open"))return FR_DISK_ERR;
    if(mode&FA_WRITE){if(!dirs.count(parent(path)))return FR_NO_PATH;
        if(mode&FA_CREATE_ALWAYS)files[path].clear();else if(!files.count(path))return FR_NO_FILE;}
    else if(!files.count(path))return FR_NO_FILE;
    assert(std::strlen(path)<sizeof(f->path));std::strcpy(f->path,path);f->offset=0;f->size=files[path].size();f->write=bool(mode&FA_WRITE);return FR_OK;
}
FRESULT f_close(FIL *){return hit("close")?FR_DISK_ERR:FR_OK;}
FRESULT f_read(FIL *f,void *dst,UINT n,UINT *got) {
    *got=0;if(hit("read"))return FR_DISK_ERR;const auto &b=files.at(f->path);
    size_t count=b.size()-f->offset;if(count>n)count=n;if(hit("short_read")&&count)--count;
    std::memcpy(dst,b.data()+f->offset,count);f->offset+=count;*got=UINT(count);return FR_OK;
}
FRESULT f_write(FIL *f,const void *data,UINT n,UINT *wrote) {
    assert(f->write);++writes;*wrote=0;if(hit("write"))return FR_DISK_ERR;if(hit("short_write")&&n)--n;
    auto &b=files.at(f->path);if(b.size()<f->offset+n)b.resize(f->offset+n);std::memcpy(b.data()+f->offset,data,n);f->offset+=n;f->size=b.size();*wrote=n;return FR_OK;
}
FRESULT f_sync(FIL *){return hit("sync")?FR_DISK_ERR:FR_OK;}
FRESULT f_stat(const char *p,FILINFO *info) {
    if(hit("stat"))return FR_DISK_ERR;
    std::memset(info,0,sizeof(*info));
    if(dirs.count(p)){info->fattrib=AM_DIR;return FR_OK;}if(!files.count(p))return FR_NO_FILE;
    info->fsize=files[p].size();return FR_OK;
}
FRESULT f_mkdir(const char *p){if(hit("mkdir"))return FR_DISK_ERR;return dirs.insert(p).second?FR_OK:FR_EXIST;}
FRESULT f_rename(const char *from,const char *to) {
    ++renames;if(hit("rename"))return FR_DISK_ERR;if(files.count(to)||dirs.count(to))return FR_EXIST;
    if(!files.count(from))return FR_NO_FILE;
    files[to]=std::move(files.at(from));files.erase(from);return FR_OK;
}
FRESULT f_opendir(DIR *d,const char *p) {
    if(hit("opendir"))return FR_DISK_ERR;
    if(!dirs.count(p))return FR_NO_PATH;
    std::strcpy(d->path,p);d->index=0;return FR_OK;
}
FRESULT f_closedir(DIR *){return hit("closedir")?FR_DISK_ERR:FR_OK;}
FRESULT f_readdir(DIR *d,FILINFO *info) {
    if(hit("readdir"))return FR_DISK_ERR;
    std::memset(info,0,sizeof(*info));std::vector<std::string> paths;
    for(const auto &p:dirs)if(parent(p)==d->path)paths.push_back(p);
    if(d->index==paths.size())return FR_OK;
    const auto &p=paths[d->index++];const auto name=p.substr(p.rfind('/')+1);assert(name.size()<sizeof(info->fname));
    std::strcpy(info->fname,name.c_str());info->fattrib=AM_DIR;return FR_OK;
}
