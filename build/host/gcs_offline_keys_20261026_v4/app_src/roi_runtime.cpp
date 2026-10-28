#include "roi_runtime.h"
#include "roi_protocol.h"
#include "s1b_profile.h"
#include <cstring>
namespace s2c {
namespace {
// One maximum-scene CPU cube, never a PL DMA buffer. A failed SD read marks it
// invalid; an explicit later activation must re-read/CRC it before any task.
alignas(64) float cube[491428080u/4],cls[2646],pos[15876];
alignas(64) unsigned char weights[TT_ENGINE_WPKG16_BYTES];
alignas(64) float patch[TT_ENGINE_PATCH_ELEMS];
alignas(64) int16_t input[4*TT_ENGINE_IN_STRIDE/2];
alignas(64) unsigned char output[64];
TTM3aRoiResult results[MODEL_MAX_PIXELS];
TTM3aAppSession state{};
TTM3aRoiSession batch_state{};
bool scene_mode=false;
bool task_mode=false,task_active=false,engine_ready=false,busy=false;
bool model_mode=false,driver_initialized=false;
unsigned resident_scene=0,input_scene=0;
uint32_t resident_crc=WCRC;
ModelInput *model_input=nullptr;
unsigned task_x=0,task_y=0,task_w=0,task_h=0;
struct ExclusiveCall { ExclusiveCall(){busy=true;} ~ExclusiveCall(){busy=false;} };
alignas(64) unsigned char probe_output[TT_ENGINE_ATTN_STRIDE];
TTM3aRoiSession probe_state{};
TTM3aRoiResult probe_result{};
const TTM3aSdStorage storage={{{cube,sizeof(cube)},{cls,sizeof(cls)},
                              {pos,sizeof(pos)},{weights,sizeof(weights)}}};
const TTM3aRoiRequest roi={cube,S1B_CUBE_BYTES,400,550,406,0,0,5,3,cls,2646,pos,15876,
    4,100000000,patch,sizeof(patch),input,sizeof(input),output,sizeof(output),results,15};
TTM3aRoiRequest current_request() {
    TTM3aRoiRequest r=roi;
    if(model_mode){const auto &s=*scene_contract(resident_scene);r.width=s.width;r.height=s.height;r.row_pixels=s.width+6;r.cube_bytes=s.cube_bytes;}
    return r;
}
bool healthy() {return !state.roi.halted&&!batch_state.halted&&!probe_state.halted;}
bool resident(const ModelEntry &e) {
    return model_mode&&engine_ready&&state.sd.loaded&&input_scene==e.key.scene&&resident_scene==e.key.scene&&resident_crc==e.key.crc&&healthy();
}
int load_model(const ModelEntry &a,const ModelEntry &b,bool in_probe=false) {
    if(!model_mode||busy||!healthy()||(task_active&&!in_probe))return TT_M3A_ROI_HALTED;
    if(a.key.scene!=b.key.scene||a.key.kind||b.key.kind!=1||std::memcmp(a.key.tag,b.key.tag,16)||
       !model_pair(b.key.scene,a.data,b.data))return TT_M3A_SD_FORMAT;
    if(resident(b))return 0;
    ExclusiveCall call;
    if(!state.sd.loaded||input_scene!=b.key.scene) {
        // This is the private reloadable input path, not a reset/retry of the
        // public one-shot tt_m3a_sd_load session or any DMA/driver session.
        state.sd.loaded=false;state.sd.bytes_read=0;state.sd.file_index=0;
        if(!model_input->load_input(b.key.scene,cube,sizeof(cube))) {
            state.sd.fatfs_status=model_input->input_error();return TT_M3A_SD_IO;
        }
        input_scene=b.key.scene;state.sd.loaded=true;state.sd.fatfs_status=0;
        state.sd.bytes_read=scene_contract(input_scene)->cube_bytes;
    }
    if(!driver_initialized) {
        state.driver_status=tt_m3a_init(0);
        if(state.driver_status){state.roi.halted=true;return TT_M3A_ROI_DRIVER;}
        driver_initialized=true;
    }
    // Registry/staging memory is never given to the engine. This permanent
    // DMA buffer is overwritten ONLY after all fault/busy/task gates above.
    std::memcpy(cls,a.data+289344,sizeof(cls));std::memcpy(pos,a.data+299928,sizeof(pos));
    std::memcpy(weights,b.data,MODEL_ENGINE_BYTES);
    state.driver_status=tt_m3a_load_weights(weights,sizeof(weights),roi.max_polls);
    if(state.driver_status){state.roi.halted=true;return TT_M3A_ROI_DRIVER;}
    resident_scene=b.key.scene;resident_crc=b.key.crc;engine_ready=true;return 0;
}
}
bool configure_models(ModelInput &inputs) {
    if(model_mode||busy||state.sd.attempted||state.attempted||engine_ready||!healthy())return false;
    model_mode=true;model_input=&inputs;return true;
}
int RuntimeModelActivation::load(const ModelEntry &a,const ModelEntry &b) {
    const int rc=load_model(a,b);return rc&&state.driver_status?state.driver_status:rc;
}
bool RuntimeModelActivation::ready(const ModelEntry &b) const {return resident(b);}
bool RuntimeModelActivation::uncertain() const {return !healthy();}
int load_scene() {
    if(model_mode || busy || state.attempted)return TT_M3A_ROI_HALTED;
    if(S1B_PROFILE.files[3].crc32!=WCRC) return TT_M3A_SD_ARGUMENT;
    return tt_m3a_sd_load(state.sd,S1B_PROFILE,storage);
}
int run_once() {
    if(model_mode || state.attempted || busy) return TT_M3A_ROI_HALTED;
    ExclusiveCall call;
    state.attempted=true;
    if(!state.sd.loaded) return TT_M3A_SD_ARGUMENT;
    state.driver_status=tt_m3a_init(0);
    if(!state.driver_status)
        state.driver_status=tt_m3a_load_weights(weights,sizeof(weights),roi.max_polls);
    if(state.driver_status) {
        state.roi.halted=true; return TT_M3A_ROI_DRIVER;
    }
    const int rc=tt_m3a_roi_run(state.roi,roi);
    state.driver_status=state.roi.driver_status;
    return rc;
}
int begin_scene() {
    if(model_mode || state.attempted || busy)return TT_M3A_ROI_HALTED;
    ExclusiveCall call;
    state.attempted=true;scene_mode=true;
    if(!state.sd.loaded)return TT_M3A_SD_ARGUMENT;
    state.driver_status=tt_m3a_init(0);
    if(!state.driver_status)state.driver_status=tt_m3a_load_weights(weights,sizeof(weights),roi.max_polls);
    if(state.driver_status){state.roi.halted=true;return TT_M3A_ROI_DRIVER;}
    return 0;
}
int step_scene() {
    if(!scene_mode || task_mode || !state.attempted || state.roi.halted || busy)return TT_M3A_ROI_HALTED;
    ExclusiveCall call;
    const size_t i=state.roi.completed;
    if(i>=SCENE_W*SCENE_H)return TT_M3A_ROI_ARGUMENT;
    TTM3aRoiRequest r=roi;
    r.x=uint32_t(i%SCENE_W);r.y=uint32_t(i/SCENE_W);
    r.roi_width=4;r.roi_height=1;r.results=results+i;r.result_count=4;
    const int rc=tt_m3a_roi_run(batch_state,r);
    // Read only the numerical module's committed CPU prefix. Never touch pending DMA output.
    state.roi.completed+=batch_state.completed;
    state.driver_status=state.roi.driver_status=batch_state.driver_status;
    if(rc || batch_state.halted){state.roi.halted=true;return rc?rc:TT_M3A_ROI_DRIVER;}
    if(batch_state.completed!=4){state.roi.halted=true;return TT_M3A_ROI_BUFFER;}
    return 0;
}
const TTM3aAppSession &outcome() { return state; }
int begin_task(unsigned x,unsigned y,unsigned width,unsigned height) {
    if(busy || state.roi.halted || batch_state.halted || probe_state.halted || task_active ||
       (state.attempted && !task_mode))return TT_M3A_ROI_HALTED;
    const auto &spec=*scene_contract(model_mode?resident_scene:0);
    if(x>=spec.width || y>=spec.height || !width || !height || width>spec.width-x || height>spec.height-y)
        return TT_M3A_ROI_ARGUMENT;
    if(!state.sd.loaded || (model_mode&&(!engine_ready||input_scene!=resident_scene)))return TT_M3A_SD_ARGUMENT;
    ExclusiveCall call;
    if(!engine_ready) {
        state.driver_status=tt_m3a_init(0);
        if(!state.driver_status)state.driver_status=tt_m3a_load_weights(weights,sizeof(weights),roi.max_polls);
        if(state.driver_status){state.roi.halted=true;return TT_M3A_ROI_DRIVER;}
        engine_ready=true;
    }
    // This only resets a healthy task's CPU bookkeeping, never the DMA fault
    // latch, numerical driver session, or buffers possibly owned by hardware.
    task_mode=task_active=state.attempted=true;scene_mode=false;
    task_x=x;task_y=y;task_w=width;task_h=height;
    state.roi.completed=0;state.roi.driver_status=state.driver_status=0;
    return 0;
}
int step_task() {
    if(!task_mode || !task_active || busy || state.roi.halted)return TT_M3A_ROI_HALTED;
    ExclusiveCall call;
    const size_t i=state.roi.completed;
    if(i>=size_t(task_w)*task_h)return TT_M3A_ROI_ARGUMENT;
    const unsigned remainder=task_w-unsigned(i%task_w),n=remainder<4?remainder:4;
    TTM3aRoiRequest r=current_request();r.x=task_x+unsigned(i%task_w);r.y=task_y+unsigned(i/task_w);
    r.roi_width=n;r.roi_height=1;r.results=results+i;r.result_count=n;
    const int rc=tt_m3a_roi_run(batch_state,r);
    state.driver_status=state.roi.driver_status=batch_state.driver_status;
    if(batch_state.completed>n){state.roi.halted=true;return TT_M3A_ROI_BUFFER;}
    for(unsigned j=0;j<batch_state.completed;++j) {
        if(results[i+j].x!=r.x+j || results[i+j].y!=r.y || (results[i+j].packed_class&0xff00) ||
           (results[i+j].packed_class&255)>=scene_contract(model_mode?resident_scene:0)->classes)
            {state.roi.halted=true;return TT_M3A_ROI_BUFFER;}
    }
    state.roi.completed+=batch_state.completed; // only the committed CPU prefix
    if(rc || batch_state.halted || batch_state.completed!=n) {
        state.roi.halted=true;return rc?rc:TT_M3A_ROI_BUFFER;
    }
    if(state.roi.completed==size_t(task_w)*task_h)task_active=false;
    return 0;
}
bool stop_task() {
    if(!task_mode || busy || state.roi.halted || batch_state.halted || probe_state.halted)return false;
    task_active=false;return true;
}
bool copy_pixel(unsigned index,uint32_t &word) {
    if(index>=(task_mode?task_w*task_h:scene_mode?SCENE_W*SCENE_H:15) || index>=state.roi.completed) return false;
    const TTM3aRoiResult &r=results[index];
    const unsigned width=task_mode?task_w:scene_mode?SCENE_W:5;
    if(r.x!=(task_mode?task_x:0)+index%width || r.y!=(task_mode?task_y:0)+index/width) return false;
    word=r.packed_class; return true;
}
bool copy_row(unsigned y,uint32_t words[5]) {
    // No output DMA reads here, including when only a success prefix exists.
    if(task_mode || !words || y>=3 || state.roi.completed<(y+1)*5) return false;
    for(unsigned x=0;x<5;++x) {
        const TTM3aRoiResult &r=results[y*5+x];
        if(r.x!=x || r.y!=y) return false;
        words[x]=r.packed_class;
    }
    return true;
}
bool copy_segment(unsigned row,unsigned col,unsigned n,uint32_t *words) {
    if(task_mode) {
        if(!words || row<task_y || row-task_y>=task_h || col<task_x || col-task_x>=task_w ||
           !n || n>ROW_MAX || n>task_w-(col-task_x) || (row-task_y+1)*task_w>state.roi.completed)return false;
        for(unsigned x=0;x<n;++x)if(!copy_pixel((row-task_y)*task_w+col-task_x+x,words[x]))return false;
        return true;
    }
    const unsigned width=scene_mode?SCENE_W:5,height=scene_mode?SCENE_H:3;
    if(!words || row>=height || !n || n>ROW_MAX || col>=width || n>width-col ||
       (row+1)*width>state.roi.completed)return false;
    for(unsigned x=0;x<n;++x)if(!copy_pixel(row*width+col+x,words[x]))return false;
    return true;
}
int probe_once(unsigned row,unsigned col,uint32_t &word,int32_t *logits,size_t capacity,uint32_t *attention,size_t attention_capacity) {
    if(!state.attempted || busy || state.roi.halted || !state.sd.loaded ||
       (!task_mode && state.roi.completed!=(scene_mode?SCENE_W*SCENE_H:15)))return TT_M3A_ROI_HALTED;
    const auto &spec=*scene_contract(model_mode?resident_scene:0);
    if(row>=spec.height||col>=spec.width||!logits||capacity<spec.classes||
       (attention&&attention_capacity<TT_ENGINE_ATTN_WORDS)||(!attention&&attention_capacity))return TT_M3A_ROI_ARGUMENT;
    ExclusiveCall call;
    TTM3aRoiRequest r=current_request();r.x=col;r.y=row;r.roi_width=r.roi_height=1;
    r.results=&probe_result;r.result_count=1;
    // Reuse the full validated extraction/embed/CLASS path; no alternate numeric implementation.
    int rc=tt_m3a_roi_run(probe_state,r);
    if(!rc && (probe_state.halted || probe_state.completed!=1 ||
               probe_result.x!=col || probe_result.y!=row || (probe_result.packed_class&0xff00) ||
               (probe_result.packed_class&255)>=spec.classes))rc=TT_M3A_ROI_BUFFER;
    if(!rc) {
        const unsigned kind=attention?TT_ENGINE_OUT_ATTENTION:TT_ENGINE_OUT_LOGITS;
        const size_t bytes=tt_m3a_output_bytes(1,0,11,kind,false);
        if(bytes>sizeof(probe_output)||!bytes)rc=TT_M3A_ROI_BUFFER;
        else {
            const TTM3aJob j={input,TT_ENGINE_IN_STRIDE,probe_output,sizeof(probe_output),1,0,11,kind,false};
            probe_state.driver_status=tt_m3a_run(j,roi.max_polls);
            if(probe_state.driver_status)rc=TT_M3A_ROI_DRIVER;
        }
    }
    if(!rc&&attention){
        uint32_t h[16];std::memcpy(h,probe_output,64);
        const uint32_t expected[16]={TT_ENGINE_ATTN_MAGIC,4,probe_result.packed_class,spec.classes,12,6,24,432,0,0,0,0,0,0,0,0};
        if(std::memcmp(h,expected,64))rc=TT_M3A_CONTRACT;
        for(unsigned row=0;!rc&&row<72;++row){uint64_t sum=0;
            for(unsigned col=0;col<6;++col){uint32_t v;std::memcpy(&v,probe_output+TT_ENGINE_ATTN_OFFSET+4*(row*6+col),4);
                if(v>(1u<<24))rc=TT_M3A_CONTRACT;
                sum+=v;}
            if(sum<(1u<<24)-64||sum>(1u<<24)+64)rc=TT_M3A_CONTRACT;
        }
    }
    if(rc){state.driver_status=probe_state.driver_status?probe_state.driver_status:rc;state.roi.halted=true;return rc;}
    // Copy only after successful DMA completion. Original task results/progress stay unchanged.
    for(unsigned i=0;i<spec.classes;++i)std::memcpy(logits+i,probe_output+(attention?64:0)+4*i,4);
    if(attention)std::memcpy(attention,probe_output+TT_ENGINE_ATTN_OFFSET,TT_ENGINE_ATTN_WORDS*4);
    word=probe_result.packed_class;return 0;
}
int probe_model(Models &models,unsigned scene,uint32_t crc,unsigned row,unsigned col,
                uint32_t &word,int32_t *logits,size_t capacity,uint32_t *attention,size_t attention_capacity) {
    if(!model_mode||!state.attempted||busy||!healthy()||models.faulted())return TT_M3A_ROI_HALTED;
    const auto *spec=scene_contract(scene);
    if(!spec||row>=spec->height||col>=spec->width||!logits||capacity<spec->classes||
       (attention&&attention_capacity<TT_ENGINE_ATTN_WORDS)||(!attention&&attention_capacity))return TT_M3A_ROI_ARGUMENT;
    const auto *target=models.find(scene,1,crc);const auto *saved=models.find(resident_scene,1,resident_crc);
    const auto *a=target?models.companion(*target):nullptr;const auto *old=saved?models.companion(*saved):nullptr;
    if(!target||!saved||!a||!old)return TT_M3A_SD_ARGUMENT;
    int rc=load_model(*a,*target,true);uint32_t result=0,matrices[TT_ENGINE_ATTN_WORDS];int32_t values[24]={};
    if(!rc)rc=probe_once(row,col,result,values,24,attention?matrices:nullptr,attention?TT_ENGINE_ATTN_WORDS:0);
    // Never overwrite hardware-owned buffers after a failed LOAD_W/FULL. If
    // a pre-DMA SD read failed, restore the original input before resuming.
    if(healthy()&&!resident(*saved)) {
        const int restore=load_model(*old,*saved,true);
        if(restore){state.roi.halted=true;rc=restore;}
    }
    if(!healthy()){models.fault(state.driver_status?state.driver_status:rc);return rc?rc:TT_M3A_ROI_HALTED;}
    if(rc)return rc;
    word=result;std::memcpy(logits,values,spec->classes*sizeof(int32_t));
    if(attention)std::memcpy(attention,matrices,sizeof(matrices));
    return 0;
}
}
