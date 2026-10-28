#ifndef TT_M3A_SD_H
#define TT_M3A_SD_H
#include <stddef.h>
#include <stdint.h>

// S1b fixed-profile, read-only FatFs loader. No raw sensor preprocessing.
// File order: padded float32 HWC cube, cls float32, pos float32, int16 TTE2.
enum { TT_M3A_SD_FILES = 4 };
enum TTM3aSdStatus {
    TT_M3A_SD_OK = 0, TT_M3A_SD_ARGUMENT = -200, TT_M3A_SD_BUFFER = -201,
    TT_M3A_SD_FORMAT = -202, TT_M3A_SD_IO = -203, TT_M3A_SD_SIZE = -204,
    TT_M3A_SD_SHORT = -205, TT_M3A_SD_CRC = -206, TT_M3A_SD_USED = -207
};
struct TTM3aSdFile { const char *path; size_t bytes; uint32_t crc32; };
struct TTM3aSdProfile {
    uint32_t width, height, bands, pad, classes;
    TTM3aSdFile files[TT_M3A_SD_FILES]; // generated only after host SHA verification
};
struct TTM3aSdBuffer { void *data; size_t capacity; };
struct TTM3aSdStorage { TTM3aSdBuffer files[TT_M3A_SD_FILES]; };
struct TTM3aSdSession {
    bool attempted, loaded; // zero once; NEVER retry a partial load in this session
    int file_index, fatfs_status, cleanup_status;
    size_t bytes_read;     // current file only; never a promise of valid data
};
// No allocation, writes to card, or IP access. Caller exclusively owns buffers;
// profile/storage/session/path strings must live outside all destination spans.
// All four spans validated before mount; partial bytes invalid on ANY failure.
// CRC pins data to the host-verified profile (accidental corruption, NOT security).
int tt_m3a_sd_load(TTM3aSdSession &, const TTM3aSdProfile &, const TTM3aSdStorage &);
#endif
