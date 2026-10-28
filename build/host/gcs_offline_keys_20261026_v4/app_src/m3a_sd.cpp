#include "m3a_sd.h"
#include "tt_engine_regs.h"
#include "ff.h"
#include <climits>
#include <cstring>
#include <limits>

namespace {
constexpr UINT CHUNK = 1u << 20; // bounded FatFs reads, also catches short FR_OK
bool span(const TTM3aSdBuffer &b, size_t n) {
    const uintptr_t a = reinterpret_cast<uintptr_t>(b.data);
    return a && !(a & 63u) && b.capacity >= n && n <= UINTPTR_MAX-a;
}
uint32_t crc_update(uint32_t c, const unsigned char *p, size_t n) {
    // One small read-only lookup table, initialized before reading; no new library.
    static uint32_t table[256];
    if (!table[1]) for (unsigned i=0; i<256; ++i) {
        uint32_t v=i;
        for (unsigned j=0; j<8; ++j) v=(v>>1)^((v&1)?0xedb88320u:0u);
        table[i]=v;
    }
    while (n--) c=table[(c^*p++)&255u]^(c>>8);
    return c;
}
int validate(const TTM3aSdProfile &p, const TTM3aSdStorage &b) {
    const uint32_t endian=1;
    if (sizeof(float)!=4 || !std::numeric_limits<float>::is_iec559 ||
        *reinterpret_cast<const unsigned char *>(&endian)!=1) return TT_M3A_SD_FORMAT;
    if (!p.width || !p.height || p.width>INT_MAX-6u || p.height>INT_MAX-6u ||
        p.bands!=270 || p.pad!=3 || !p.classes || p.classes>TT_ENGINE_NCLS_MAX)
        return TT_M3A_SD_FORMAT;
    const uint64_t pixels=(uint64_t(p.width)+6)*(uint64_t(p.height)+6);
    // FAT32 and UINT-limited board I/O. Bound BEFORE multiplying bytes.
    if (pixels>UINT32_MAX/(270u*4u)) return TT_M3A_SD_SIZE;
    const size_t sizes[]={static_cast<size_t>(pixels*270*4),2646*4,15876*4,TT_ENGINE_WPKG16_BYTES};
    for (unsigned i=0; i<TT_M3A_SD_FILES; ++i) {
        if (!p.files[i].path || std::strncmp(p.files[i].path,"1:/",3)) return TT_M3A_SD_ARGUMENT;
        if (p.files[i].bytes!=sizes[i]) return TT_M3A_SD_SIZE;
        if (!span(b.files[i],sizes[i])) return TT_M3A_SD_BUFFER;
        const uintptr_t a=reinterpret_cast<uintptr_t>(b.files[i].data);
        // Keep SD destinations in low DDR as well as M3a weight DMA.
        if (a>=UINT64_C(0x100000000) || sizes[i]>UINT64_C(0x100000000)-a) return TT_M3A_SD_BUFFER;
        for (unsigned j=0; j<i; ++j) {
            const uintptr_t z=reinterpret_cast<uintptr_t>(b.files[j].data);
            if (a<z+sizes[j] && z<a+sizes[i]) return TT_M3A_SD_BUFFER;
        }
    }
    return TT_M3A_SD_OK;
}
}
int tt_m3a_sd_load(TTM3aSdSession &s, const TTM3aSdProfile &p, const TTM3aSdStorage &b) {
    if (s.attempted) return TT_M3A_SD_USED; // before any destination access
    s.attempted=true; s.loaded=false; s.file_index=-1; s.bytes_read=0;
    s.fatfs_status=0; s.cleanup_status=0;
    int status=validate(p,b);
    if (status) return status;
    FATFS fs{};
    s.fatfs_status=static_cast<int>(f_mount(&fs,"1:/",1));
    if (s.fatfs_status!=FR_OK) status=TT_M3A_SD_IO;
    for (unsigned i=0; !status && i<TT_M3A_SD_FILES; ++i) {
        s.file_index=static_cast<int>(i); s.bytes_read=0;
        FIL f{};
        s.fatfs_status=static_cast<int>(f_open(&f,p.files[i].path,FA_READ));
        if (s.fatfs_status!=FR_OK) { status=TT_M3A_SD_IO; break; }
        // No narrowing of FSIZE_t before comparison, trailing bytes rejected too.
        if (f_size(&f)!=p.files[i].bytes) status=TT_M3A_SD_SIZE;
        uint32_t crc=0xffffffffu;
        while (!status && s.bytes_read<p.files[i].bytes) {
            const size_t remain=p.files[i].bytes-s.bytes_read;
            const UINT want=remain<CHUNK?static_cast<UINT>(remain):CHUNK;
            UINT got=0;
            auto *dst=static_cast<unsigned char *>(b.files[i].data)+s.bytes_read;
            s.fatfs_status=static_cast<int>(f_read(&f,dst,want,&got));
            if (got>want) { status=TT_M3A_SD_SHORT; break; }
            s.bytes_read+=got;
            if (s.fatfs_status!=FR_OK) { status=TT_M3A_SD_IO; break; }
            if (got!=want) { status=TT_M3A_SD_SHORT; break; }
            crc=crc_update(crc,dst,got);
        }
        const int close_status=static_cast<int>(f_close(&f));
        if (close_status!=FR_OK) { s.cleanup_status=close_status; if (!status) status=TT_M3A_SD_IO; }
        if (!status && (crc^0xffffffffu)!=p.files[i].crc32) status=TT_M3A_SD_CRC;
    }
    // Unregister even when mount failed: FatFs may have retained &fs. No stack
    // filesystem object escapes. This all completes BEFORE any PL DMA starts.
    const int unmount=static_cast<int>(f_mount(nullptr,"1:/",0));
    if (unmount!=FR_OK) { s.cleanup_status=unmount; if (!status) status=TT_M3A_SD_IO; }
    if (!status) {
        uint32_t head[4]; std::memcpy(head,b.files[3].data,sizeof(head));
        if (head[0]!=TT_ENGINE_WPKG_MAGIC || head[1]!=2 || head[2]!=p.classes || head[3]!=16)
            status=TT_M3A_SD_FORMAT;
    }
    s.loaded=status==TT_M3A_SD_OK;
    return status;
}
