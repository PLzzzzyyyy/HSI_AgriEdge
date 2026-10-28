#ifndef GCS_MODEL_TEST_FF_H
#define GCS_MODEL_TEST_FF_H
// Isolated RAM filesystem double; never used in the production/BSP include path.
#include <cstddef>
#include <cstdint>
typedef unsigned UINT;
typedef int FRESULT;
enum {FR_OK=0,FR_DISK_ERR=1,FR_NO_FILE=4,FR_NO_PATH=5,FR_EXIST=8};
enum {FA_READ=1,FA_WRITE=2,FA_CREATE_ALWAYS=8,AM_DIR=16};
struct FATFS {int unused;};
struct FIL {char path[160];size_t size,offset;bool write;};
struct DIR {char path[160];unsigned index;};
struct FILINFO {uint64_t fsize;unsigned fattrib;char fname[256];};
#define f_size(f) ((f)->size)
FRESULT f_mount(FATFS *,const char *,unsigned);
FRESULT f_open(FIL *,const char *,unsigned);
FRESULT f_close(FIL *);
FRESULT f_read(FIL *,void *,UINT,UINT *);
FRESULT f_write(FIL *,const void *,UINT,UINT *);
FRESULT f_sync(FIL *);
FRESULT f_stat(const char *,FILINFO *);
FRESULT f_mkdir(const char *);
FRESULT f_rename(const char *,const char *);
FRESULT f_opendir(DIR *,const char *);
FRESULT f_closedir(DIR *);
FRESULT f_readdir(DIR *,FILINFO *);
#endif
