#ifndef HSI_S2B_BOOT_ID_H
#define HSI_S2B_BOOT_ID_H
#include <stdint.h>

namespace s2b {
// Private App seam, not a change to the S2a wire/public interface.
// Success must assign a fresh random u32 for this boot from an audited source.
// Failure must leave the output untouched; no constant/timestamp fallback.
bool acquire_boot_id(uint32_t &out);
}
#endif
