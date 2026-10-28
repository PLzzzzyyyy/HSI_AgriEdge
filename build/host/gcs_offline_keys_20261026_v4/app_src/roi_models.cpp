#include "roi_models.h"
#include <cmath>
#include <cstring>
#include <limits>
namespace s2c {
namespace {
const SceneContract scenes[]={
    {"longkou",400,550,9,0,270,3,243794880,0xbf3b60c5},
    {"honghu",475,940,22,0,270,3,491428080,0x857ba1a6},
    {"hanchuan",303,1217,16,4,270,3,408139560,0x66ed4ccc}
};
uint32_t u32(const uint8_t *p){return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
bool zero(const uint8_t *p,size_t n){while(n--)if(*p++)return false;return true;}
double f32(const uint8_t *p){float v;std::memcpy(&v,p,4);return v;}
bool same(const ModelKey &a,const ModelKey &b) {
    return a.scene==b.scene&&a.kind==b.kind&&a.bytes==b.bytes&&a.crc==b.crc&&!std::memcmp(a.tag,b.tag,16);
}
}
const SceneContract *scene_contract(unsigned s){return s<3?scenes+s:nullptr;}
size_t model_bytes(unsigned s,unsigned kind) {
    const auto *c=scene_contract(s);return !c||kind>1?0:kind?MODEL_ENGINE_BYTES:363432+size_t(c->classes)*10588;
}
uint32_t model_crc_update(uint32_t c,const uint8_t *p,size_t n) {
    static uint32_t table[256];
    if(!table[1])for(unsigned i=0;i<256;++i) {
        uint32_t v=i;for(unsigned j=0;j<8;++j)v=(v>>1)^((v&1)?0xedb88320u:0u);table[i]=v;
    }
    while(n--)c=table[(c^*p++)&255]^(c>>8);
    return c;
}
uint32_t model_crc(const uint8_t *p,size_t n){return model_crc_update(0xffffffff,p,n)^0xffffffff;}
bool model_key(const ModelKey &k) {
    if(!k.crc||!model_bytes(k.scene,k.kind)||k.bytes!=model_bytes(k.scene,k.kind))return false;
    unsigned len=0;
    while(len<16&&k.tag[len]) {
        const char c=k.tag[len];if(!((c>='a'&&c<='z')||(c>='0'&&c<='9')||(len&&(c=='_'||c=='-'))))return false;
        ++len;
    }
    return len&&len<=15&&zero(reinterpret_cast<const uint8_t *>(k.tag)+len,16-len);
}
bool model_package(unsigned s,unsigned kind,const uint8_t *b,size_t n) {
    static_assert(sizeof(float)==4&&std::numeric_limits<float>::is_iec559,"IEEE float32 required");
    const uint32_t endian=1;
    if(*reinterpret_cast<const uint8_t *>(&endian)!=1||!b||!model_bytes(s,kind)||n!=model_bytes(s,kind))return false;
    const unsigned classes=scene_contract(s)->classes;
    if(kind==0) {
        for(size_t off=289344;off<n;off+=4)if((u32(b+off)&0x7f800000)==0x7f800000)return false;
        return true;
    }
    if(u32(b)!=0x32455454||u32(b+4)!=2||u32(b+8)!=classes||u32(b+12)!=16||
       !zero(b+16,16)||!zero(b+32+classes,32-classes)||!zero(b+63568,48)||
       !zero(b+63616+classes*4,128-classes*4))return false;
    for(unsigned c=0;c<24;++c) {
        const size_t used=c<classes?5292:0;
        if(!zero(b+63744+c*5312+used,5312-used))return false;
    }
    return true;
}
bool model_pair(unsigned s,const uint8_t *a,const uint8_t *b) {
    if(!model_package(s,0,a,model_bytes(s,0))||!model_package(s,1,b,MODEL_ENGINE_BYTES)||
       std::memcmp(a,b+191232,289344))return false;
    // This validates exported EMB, not an alternative inference implementation.
    // Match export_scene/D1: add exactly represented float32 values in double,
    // floor(x*2^24 + .5), and reject overflow before any integer conversion.
    for(unsigned p=0;p<2646;++p)for(unsigned t=0;t<6;++t) {
        double value=f32(a+299928+4*(p*6+t));if(!t)value+=f32(a+289344+4*p);
        value=std::floor(value*16777216.0+0.5);
        if(!std::isfinite(value)||value<-2147483648.0||value>=2147483648.0||
           uint32_t(int32_t(value))!=u32(b+64+4*(p*6+t)))return false;
    }
    return true;
}
int Models::by_tag(const ModelKey &k) const {
    for(unsigned i=0;i<count_;++i)if(entries_[i].key.scene==k.scene&&entries_[i].key.kind==k.kind&&
        !std::memcmp(entries_[i].key.tag,k.tag,16))return int(i);
    return -1;
}
const ModelEntry *Models::find(unsigned scene,unsigned kind,uint32_t crc) const {
    for(unsigned i=0;i<count_;++i)if(entries_[i].key.scene==scene&&entries_[i].key.kind==kind&&entries_[i].key.crc==crc)
        return entries_+i;
    return nullptr;
}
const ModelEntry *Models::companion(const ModelEntry &e) const {
    ModelKey k=e.key;k.kind=0;const int i=by_tag(k);return i<0?nullptr:entries_+i;
}
ModelReply Models::begin(const ModelKey &k) {
    if(faulted_)return {6,uint32_t(fault_code_)};
    if(!model_key(k))return {8,received_};
    const int existing=by_tag(k);const auto *alias=find(k.scene,k.kind,k.crc);
    if((existing>=0&&!same(k,entries_[existing].key))||(alias&&!same(alias->key,k)))return {3,received_};
    if(have_pending_&&same(k,pending_))return {0,received_};
    if(existing<0&&count_==MODEL_MAX_ENTRIES)return {8,received_};
    pending_=k;have_pending_=true;committed_=existing;last_offset_=last_size_=0;
    received_=existing<0?0:k.bytes;return {0,received_};
}
ModelReply Models::chunk(unsigned s,unsigned kind,uint32_t total,uint32_t crc,uint32_t off,const uint8_t *p,size_t n) {
    if(faulted_)return {6,uint32_t(fault_code_)};
    if(!have_pending_||s!=pending_.scene||kind!=pending_.kind||total!=pending_.bytes||crc!=pending_.crc||
       !p||!n||n>1384||off>total||n>total-off)return {8,received_};
    const uint8_t *old=committed_<0?staging_:entries_[committed_].data;
    if(last_size_&&off==last_offset_&&n==last_size_&&!std::memcmp(old+off,p,n))return {0,received_};
    if(off!=received_||committed_>=0)return {2,received_};
    std::memcpy(staging_+off,p,n);last_offset_=off;last_size_=uint32_t(n);received_+=uint32_t(n);
    return {0,received_};
}
ModelReply Models::install(const ModelKey &k,const uint8_t *p,bool persisted) {
    if(!model_key(k)||!p)return {8,0};
    if(model_crc(p,k.bytes)!=k.crc)return {1,0};
    if(!model_package(k.scene,k.kind,p,k.bytes))return {3,0};
    const int existing=by_tag(k);const auto *alias=find(k.scene,k.kind,k.crc);
    if((existing>=0&&(!same(entries_[existing].key,k)||std::memcmp(entries_[existing].data,p,k.bytes)))||
       (alias&&!same(alias->key,k)))return {3,0};
    ModelKey other=k;other.kind=uint8_t(!k.kind);const int pair=by_tag(other);
    if(k.kind&&pair<0)return {5,0};
    if(pair>=0&&!model_pair(k.scene,k.kind?entries_[pair].data:p,k.kind?p:entries_[pair].data))return {3,0};
    if(existing>=0) {
        if(persisted){entries_[existing].persisted=true;entries_[existing].persist_pending=false;}
        return {0,unsigned(existing)};
    }
    if(count_==MODEL_MAX_ENTRIES)return {8,0};
    auto &e=entries_[count_];e.key=k;std::memcpy(e.data,p,k.bytes);e.persisted=persisted;e.persist_pending=!persisted;
    return {0,count_++};
}
ModelReply Models::import(const ModelKey &k,const uint8_t *p) {
    if(faulted_)return {6,uint32_t(fault_code_)};
    return install(k,p,true);
}
ModelReply Models::persist(unsigned i,bool idle,ModelPersistence *disk) {
    auto &e=entries_[i];
    if(e.persisted)return {0,1};
    if(!idle){e.persist_pending=true;return {0,0};}
    e.persist_pending=false;e.persisted=disk&&disk->save(e.key,e.data);
    return {uint8_t(e.persisted?0:4),uint32_t(e.persisted)};
}
ModelReply Models::commit(uint32_t crc,bool idle,ModelPersistence *disk) {
    if(faulted_)return {6,uint32_t(fault_code_)};
    if(have_pending_&&pending_.crc==crc) {
        if(received_!=pending_.bytes)return {2,received_};
        if(committed_<0) {
            auto r=install(pending_,staging_,false);if(r.code)return r;committed_=int(r.value);
        }
        return persist(unsigned(committed_),idle,disk);
    }
    // v1 WCOMMIT carries only CRC: a delayed retry may refer to an older part.
    // Ambiguous cross-scene/kind CRCs must never choose an arbitrary entry.
    int found=-1;
    for(unsigned i=0;i<count_;++i)if(entries_[i].key.crc==crc){if(found>=0)return {8,0};found=int(i);}
    return found<0?ModelReply{5,0}:persist(unsigned(found),idle,disk);
}
bool Models::flush_one(ModelPersistence &disk) {
    if(faulted_)return false;
    for(unsigned i=0;i<count_;++i)if(entries_[i].persist_pending){(void)persist(i,true,&disk);return true;}
    return false;
}
void Models::fault(int rc){faulted_=true;fault_code_=rc;active_=-1;}
ModelReply Models::activate(unsigned scene,uint32_t crc,unsigned when,bool idle,ModelActivation &engine) {
    if(faulted_)return {6,uint32_t(fault_code_)};
    if(when||!idle||!scene_contract(scene))return {8,0};
    const auto *b=find(scene,1,crc);const auto *a=b?companion(*b):nullptr;
    if(!a||!b)return {5,0};
    if(active()==b&&engine.ready(*b))return {0,0};
    const int rc=engine.load(*a,*b);
    if(rc){if(engine.uncertain())fault(rc);return {6,uint32_t(rc)};}
    active_=int(b-entries_);return {0,0};
}
}
