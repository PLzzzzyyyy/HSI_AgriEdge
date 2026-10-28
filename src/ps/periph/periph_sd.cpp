// C3a：FatFs 从 SD 卡（SD1，盘符 1:）把立方体整文件读进 DDR，测读速，算 CRC32 与 PC 值比对。
// 卡的目录按 PLAN §14.2：/scenes/<景>/...，由 data/scenes/<景>/ 整目录拷过去；卡须 FAT32（以后 SD 启动的 FSBL 只认 FAT）。
#include "periph.h"
#include <stdio.h>
#include "ff.h"

namespace {

// 最大的文件 HongHu cube_f32 491 MB，一次读进一块 512 MiB 缓冲。.bss 不占 ELF 体积，启动时清零约零点几秒。
constexpr u32 BUF_BYTES = 512u << 20;
constexpr UINT CHUNK = 8u << 20;   // 每次 f_read 8 MiB；FatFs 内部按簇拆成多次 CMD18
u8 g_buf[BUF_BYTES] __attribute__((aligned(64)));
FATFS g_fs;
u32 g_crc_table[256];

struct SdFile {
    const char *path;
    u32 size;
    u32 crc;     // zlib.crc32，python tools/periph_pc.py crc 重算；export_scene.py 重导后要跟着改
    bool quick;  // s 只读 quick 项，S 读全部
};

const SdFile FILES[] = {
    {"1:/scenes/longkou/cube_i16.bin", 122800384u, 0x378F4ADFu, true},
    {"1:/scenes/longkou/weights/v2/weights_engine.bin", 480576u, 0x27231983u, true},   // 长文件名，验 LFN
    {"1:/scenes/longkou/cube_f32.bin", 243794880u, 0xBF3B60C5u, false},
    {"1:/scenes/honghu/cube_i16.bin", 247534144u, 0x7C9370BCu, false},
    {"1:/scenes/hanchuan/cube_i16.bin", 205581408u, 0xDB9FE0B6u, false},
};

const char *fr_name(FRESULT r) {
    switch (r) {
    case FR_OK: return "FR_OK";
    case FR_DISK_ERR: return "FR_DISK_ERR (SD read failed)";
    case FR_NOT_READY: return "FR_NOT_READY (no card or card init failed)";
    case FR_NO_FILE: return "FR_NO_FILE";
    case FR_NO_PATH: return "FR_NO_PATH";
    case FR_NO_FILESYSTEM: return "FR_NO_FILESYSTEM (not FAT; exFAT card? format FAT32)";
    default: return "FRESULT error";
    }
}

u32 crc32(const u8 *p, u32 n) {
    if (g_crc_table[1] == 0) {
        for (u32 i = 0; i < 256; i++) {
            u32 c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            g_crc_table[i] = c;
        }
    }
    u32 c = 0xFFFFFFFFu;
    for (u32 i = 0; i < n; i++) c = g_crc_table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

// 返回 1 = PASS，0 = FAIL，-1 = 卡上没有该文件（跳过）
int read_one(const SdFile &f) {
    static FIL fil;
    const u64 t0 = now_ticks();
    FRESULT r = f_open(&fil, f.path, FA_READ);
    if (r == FR_NO_FILE || r == FR_NO_PATH) {
        printf("  %-48s SKIP (not on card)\n", f.path);
        return -1;
    }
    if (r != FR_OK) {
        printf("  %-48s FAIL open: %s (%d)\n", f.path, fr_name(r), (int)r);
        return 0;
    }
    const u32 size = (u32)f_size(&fil);
    if (size > BUF_BYTES) {
        printf("  %-48s FAIL size %lu > buffer %lu\n", f.path, (unsigned long)size, (unsigned long)BUF_BYTES);
        f_close(&fil);
        return 0;
    }
    u32 got = 0;
    while (got < size) {
        const UINT want = (size - got < CHUNK) ? (UINT)(size - got) : CHUNK;
        UINT br = 0;
        r = f_read(&fil, g_buf + got, want, &br);
        got += br;
        if (r != FR_OK || br != want) break;
    }
    f_close(&fil);
    const u64 us = ticks_us(now_ticks() - t0);
    if (r != FR_OK || got != size) {
        printf("  %-48s FAIL read %lu/%lu B: %s (%d)\n", f.path, (unsigned long)got, (unsigned long)size, fr_name(r), (int)r);
        return 0;
    }
    const u32 crc = crc32(g_buf, size);
    const bool ok = size == f.size && crc == f.crc;
    printf("  %-48s %10lu B %8.1f ms %6.2f MB/s crc32 %08lX (expect %08lX, %lu B) %s\n", f.path,
           (unsigned long)size, us / 1000.0, us ? size / (double)us : 0.0, (unsigned long)crc,
           (unsigned long)f.crc, (unsigned long)f.size, ok ? "OK" : "MISMATCH");
    return ok ? 1 : 0;
}

}  // namespace

bool sd_test(bool full) {
    printf("\n--- C3a SD read (%s): FatFs on SD1 \"1:/\", buffer %lu MiB, timing = f_open .. last f_read, 1 MB = 10^6 B ---\n",
           full ? "full list" : "quick", (unsigned long)(BUF_BYTES >> 20));
    const u64 t0 = now_ticks();
    const FRESULT r = f_mount(&g_fs, "1:/", 1);
    if (r != FR_OK) {
        printf("C3a SD FAIL: f_mount: %s (%d)\n", fr_name(r), (int)r);
        return false;
    }
    printf("  mounted in %.1f ms: %s, cluster %lu B\n", ticks_us(now_ticks() - t0) / 1000.0,
           g_fs.fs_type == FS_FAT32 ? "FAT32" : g_fs.fs_type == FS_FAT16 ? "FAT16" : "FAT12/other",
           (unsigned long)g_fs.csize * 512ul);
    bool pass = true;
    int done = 0, first = 0;
    for (unsigned i = 0; i < sizeof FILES / sizeof FILES[0]; i++) {
        if (!full && !FILES[i].quick) continue;
        const int res = read_one(FILES[i]);
        if (i == 0) first = res;
        if (res == 0) pass = false;
        if (res > 0) done++;
    }
    // 第一项（LongKou int16 立方体）是 E1 上板的必需文件，跳过也算失败
    pass = pass && first == 1;
    f_mount(nullptr, "1:/", 0);
    printf("C3a SD %s: %d file(s) read and matched%s\n", pass ? "PASS" : "FAIL", done,
           pass ? "" : " (need longkou/cube_i16.bin present and every present file matching)");
    return pass;
}
