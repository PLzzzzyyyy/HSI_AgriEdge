// ABI4 regression: actual forward path against independently saved Q0.24.
// Includes ordinary CLASS/LOGITS/FEAT/PROJ tests; no PC substitute for PL output.
#define main legacy_full_main
#include "tb_tt_engine_full.cpp"
#undef main

int main() {
    require(legacy_full_main() == 0, "ordinary full regression");
    require(TT_ENGINE_VERSION == 4, "ABI4");
    const std::vector<i64> pb = load<uint8_t>("weights_engine.bin", TT_ENGINE_WPKG16_BYTES);
    std::vector<u64> pkg(TT_WPKG_WORDS, 0);
    for (int i=0;i<TT_ENGINE_WPKG16_BYTES;++i)
        pkg[i/8].range(8*(i%8)+7,8*(i%8))=(unsigned)pb[i];
    const unsigned mode=TT_ENGINE_MODE_FULL|TT_ENGINE_MODE_OUT(TT_ENGINE_OUT_ATTENTION);
    Bufs b;
    b.put(0,load<int16_t>("a/x_in_i16.bin",DN));
    b.put(1,load<int32_t>("b/x_embed_i32.bin",DN));
    b.put(2,load<int16_t>("a/x_in_i16.bin",DN));
    require(call(b,pkg,3,1,11,0,mode)==TT_ENGINE_ERR_MODE,"partial attention rejected");
    require(call(b,pkg,3,0,11,0,mode|TT_ENGINE_MODE_DUMP)==TT_ENGINE_ERR_MODE,"attention not DUMP");
    untouched(b.xo,0,"invalid attention");
    require(call(b,pkg,3,0,11,0,mode)==0,"attention batch");
    int bad=0;
    for(unsigned px=0;px<3;++px) {
        const std::string ent=px==1?"b":"a";
        const unsigned off=px*TT_ENGINE_ATTN_STRIDE/4;
        const uint32_t header[16]={TT_ENGINE_ATTN_MAGIC,4,
            (uint32_t)load<uint32_t>(ent+"/class_u32.bin",1)[0],
            (uint32_t)pkg[1].range(31,0),12,6,24,432,0,0,0,0,0,0,0,0};
        for(unsigned j=0;j<16;++j)require((uint32_t)lane32(b.xo,off+j)==header[j],"attention header");
        const std::vector<i64> lg=load<int32_t>(ent+"/logits_q16_i32.bin",32);
        for(unsigned j=0;j<32;++j)require(lane32(b.xo,off+16+j)==lg[j],"attention logits unchanged");
        for(unsigned l=0;l<12;++l) {
            const std::vector<i64> ref=load<int32_t>(ent+"/L"+std::to_string(l)+"_attn_i4.bin",36);
            std::vector<i64> got(36);
            for(unsigned j=0;j<36;++j)got[j]=lane32(b.xo,off+TT_ENGINE_ATTN_OFFSET/4+l*36+j);
            const int d=cmp("attention px"+std::to_string(px)+" layer"+std::to_string(l),got.data(),ref.data(),36);
            bad+=d;
            std::printf("ATTENTION px=%u layer=%u words=36 mismatches=%d\n",px,l,d);
        }
    }
    untouched(b.xo,3*TT_ENGINE_ATTN_STRIDE/8,"attention end guard");
    untouched(b.q,0,"attention q");untouched(b.k,0,"attention k");untouched(b.v,0,"attention v");untouched(b.st,0,"attention stats");
    require(!bad,"Q0.24 attention exact");
    std::puts("ATTENTION_ABI4_PASS 3 patches 12 layers; CLASS LOGITS retained; not board acceptance");
    return 0;
}
