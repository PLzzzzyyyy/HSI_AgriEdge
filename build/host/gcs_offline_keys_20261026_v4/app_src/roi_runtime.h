#ifndef S2C_ROI_RUNTIME_H
#define S2C_ROI_RUNTIME_H
#include "m3a_app.h"
#include "roi_models.h"
namespace s2c {
// All buffers have static lifetime, including on DMA fault/permanent park.
int load_scene(); // existing read-only SD loader, once, before UDP readiness
int run_once();   // init + LOAD_W + existing ROI/embed/FULL, only after START
const TTM3aAppSession &outcome();
bool copy_row(unsigned y,uint32_t words[5]); // committed CPU results ONLY
bool copy_pixel(unsigned index, uint32_t &word); // also preserves sub-row success prefix
int begin_scene(); // same SD/weights, one exclusive task owner, no new numeric implementation
int step_scene();  // at most four pixels via unchanged tt_m3a_roi_run, main pumps between calls
bool copy_segment(unsigned row,unsigned col,unsigned n,uint32_t *words);
int probe_once(unsigned row,unsigned col,uint32_t &word,int32_t *logits,size_t capacity=9,
               uint32_t *attention=nullptr,size_t attention_capacity=0);
// Lifecycle candidate entry points. Main/UI enable together only after the
// paired lifecycle transport integration; old one-shot entry points stay gated.
int begin_task(unsigned x,unsigned y,unsigned width,unsigned height);
int step_task(); // <=4 pixels, never crosses a task-row boundary
bool stop_task(); // safe foreground boundary only; does NOT clear any fault
bool configure_models(ModelInput &); // once before any SD/IP/task ownership
class RuntimeModelActivation: public ModelActivation {
public:
    int load(const ModelEntry &,const ModelEntry &) override;
    bool ready(const ModelEntry &) const override;
    bool uncertain() const override;
};
int probe_model(Models &,unsigned scene,uint32_t crc,unsigned row,unsigned col,
                uint32_t &word,int32_t *logits,size_t capacity,uint32_t *attention=nullptr,size_t attention_capacity=0);
}
#endif
