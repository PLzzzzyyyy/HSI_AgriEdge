#ifndef GCS_MODEL_RAM_FS_H
#define GCS_MODEL_RAM_FS_H
// In-memory FatFs API fixture ONLY; never part of the standalone BSP.
#include <map>
#include <set>
#include <string>
#include <vector>
#include <cstdint>
namespace model_test_fs {
extern std::map<std::string,std::vector<uint8_t>> files;
extern std::set<std::string> dirs;
extern std::string fail,always_fail;
extern unsigned writes,renames,mounts,unmounts;
bool hit(const char *);
void reset();
std::string parent(const std::string &);
}
#endif
