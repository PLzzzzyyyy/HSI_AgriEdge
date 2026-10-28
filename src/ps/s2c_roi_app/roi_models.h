#ifndef S2C_ROI_MODELS_H
#define S2C_ROI_MODELS_H
#include <cstddef>
#include <cstdint>
namespace s2c {
// Private App contracts. No change to PS/PL ABI, numeric implementation, or BSP.
constexpr unsigned MODEL_MAX_ENTRIES=48,MODEL_TAG_BYTES=16;
constexpr size_t MODEL_ENGINE_BYTES=480576,MODEL_MAX_PART_BYTES=596368;
constexpr unsigned MODEL_MAX_WIDTH=475,MODEL_MAX_HEIGHT=1217,MODEL_MAX_PIXELS=446500;
struct SceneContract {
    const char *name;uint16_t width,height;uint8_t classes,bands_unused;
    uint16_t bands,pad;uint32_t cube_bytes,cube_crc;
};
const SceneContract *scene_contract(unsigned scene);
size_t model_bytes(unsigned scene,unsigned kind);
uint32_t model_crc(const uint8_t *,size_t);
uint32_t model_crc_update(uint32_t running,const uint8_t *,size_t); // initial/final XOR = 0xffffffff
bool model_package(unsigned scene,unsigned kind,const uint8_t *,size_t);
bool model_pair(unsigned scene,const uint8_t *companion,const uint8_t *engine);
struct ModelKey {uint8_t scene,kind;uint32_t bytes,crc;char tag[MODEL_TAG_BYTES];};
bool model_key(const ModelKey &);
struct ModelReply {uint8_t code;uint32_t value;}; // existing v1 ACK meanings
struct ModelEntry {
    ModelKey key{};bool persisted=false,persist_pending=false;
    // CPU ONLY. Never pass this memory to LOAD_W or any DMA owner.
    uint8_t data[MODEL_MAX_PART_BYTES];
};
struct ModelPersistence {
    virtual bool save(const ModelKey &,const uint8_t *)=0;
    virtual ~ModelPersistence() {}
};
struct ModelActivation {
    // Foreground healthy task boundary only. Callee copies to its own permanent
    // DMA buffer and uses the existing driver; failure cannot free/reuse it.
    virtual int load(const ModelEntry &companion,const ModelEntry &engine)=0;
    virtual bool ready(const ModelEntry &) const {return true;}
    // Pre-DMA input/SD failures may be retried explicitly. A driver/DMA failure
    // must remain irreversible, even when switching back to a known model.
    virtual bool uncertain() const {return true;}
    virtual ~ModelActivation() {}
};
struct ModelInput {
    virtual bool load_input(unsigned scene,void *destination,size_t capacity)=0;
    virtual int input_error() const=0;
    virtual ~ModelInput() {}
};
class Models {
public:
    ModelReply begin(const ModelKey &); // bounded callback-safe CPU work
    ModelReply chunk(unsigned scene,unsigned kind,uint32_t total,uint32_t crc,
                     uint32_t offset,const uint8_t *,size_t);
    // Foreground only: whole-package validation/SD never run in UDP callback.
    ModelReply commit(uint32_t crc,bool idle,ModelPersistence *);
    ModelReply import(const ModelKey &,const uint8_t *); // exact SD read, revalidates CRC + pair
    bool flush_one(ModelPersistence &); // one deferred save; failure is NOT auto-retried
    ModelReply activate(unsigned scene,uint32_t crc,unsigned when,bool idle,ModelActivation &);
    void fault(int rc); // irreversible until a new App/PL boot
    bool faulted() const {return faulted_;}
    unsigned count() const {return count_;}
    const ModelEntry *entry(unsigned i) const {return i<count_?entries_+i:nullptr;}
    const ModelEntry *find(unsigned scene,unsigned kind,uint32_t crc) const;
    const ModelEntry *companion(const ModelEntry &) const;
    const ModelEntry *active() const {return active_<0?nullptr:entries_+active_;}
private:
    ModelEntry entries_[MODEL_MAX_ENTRIES];
    uint8_t staging_[MODEL_MAX_PART_BYTES];
    ModelKey pending_{};
    unsigned count_=0;uint32_t received_=0,last_offset_=0,last_size_=0;
    int committed_=-1,active_=-1,fault_code_=0;bool have_pending_=false,faulted_=false;
    int by_tag(const ModelKey &) const;
    ModelReply install(const ModelKey &,const uint8_t *,bool persisted);
    ModelReply persist(unsigned,bool,ModelPersistence *);
};
}
#endif
