#include "roi_models.h"
#include "roi_results.h"
#include "m3a_roi.h"
#include <cstdio>
static_assert(sizeof(TTM3aRoiResult)==12,"Result array contract must match ELF gate");
static_assert(sizeof(s2c::ResultStore)>=4*2097152u && sizeof(s2c::ResultStore)<=4*2097152u+4096,"Four CPU result slots");
static_assert(sizeof(s2c::Models)>=48*596368u && sizeof(s2c::Models)<=49*596368u+8192,"Registry + upload staging contract");
int main(){
    std::printf("RELEASE_LAYOUT_PASS host sizeof only, not ELF/board: result=%zu slots=%zu models=%zu entry=%zu\n",
        sizeof(TTM3aRoiResult),sizeof(s2c::ResultStore),sizeof(s2c::Models),sizeof(s2c::ModelEntry));
}
