#ifndef S1B_TEST_FF_H
#define S1B_TEST_FF_H
// Host-only FatFs surface. NOT a filesystem, SD driver or BSP ABI validation.
#include <stdint.h>
typedef unsigned int UINT;
typedef unsigned char BYTE;
typedef uint64_t FSIZE_t;
enum FRESULT { FR_OK=0, FR_DISK_ERR=1, FR_NO_FILE=4 };
struct FATFS { int unused; };
struct FIL { FSIZE_t size, position; int index; };
#define FA_READ 1
#define f_size(f) ((f)->size)
FRESULT f_mount(FATFS *,const char *,BYTE);
FRESULT f_open(FIL *,const char *,BYTE);
FRESULT f_read(FIL *,void *,UINT,UINT *);
FRESULT f_close(FIL *);
#endif
