#ifndef S2C_ROI_DISPLAY_H
#define S2C_ROI_DISPLAY_H
#include "roi_canvas.h"
namespace s2c {
// Private C3-derived polled DP adapter. Starts before networking, no IRQ ownership.
// Return0 only means link configured; actual monitor picture still needs user evidence.
int display_init(const DisplayView &view);
bool display_update(const DisplayView &view);
bool display_scene_begin(const DisplayView &view);
bool display_scene_append(unsigned row,unsigned col,unsigned n,const uint32_t *words);
bool display_scene_update(const DisplayView &view);
bool display_scene_probe(const ProbeView &view);
bool display_scene_connection(PeerState,unsigned age_seconds);
bool display_scene_dispatch(const DispatchView &);
bool display_scene_parcel(const ParcelView &,uint64_t);
bool display_scene_parcel_age(uint64_t);
bool display_scene_temperature(float,float,bool);
bool display_scene_power(const PowerView &);
unsigned display_mirror(uint32_t request,uint32_t offset,uint8_t *out,unsigned capacity,uint32_t &total,uint32_t &crc);
void display_key_service(void (*)());
bool display_scene_keys(uint32_t id,unsigned state,unsigned code);
}
#endif
