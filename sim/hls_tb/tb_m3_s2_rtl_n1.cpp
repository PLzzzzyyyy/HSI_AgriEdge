// Bounded diagnostic: weight load + ONE complete 12-layer n1 invocation.
// Reuse existing golden readers/checkers, not the full/budget call matrix.
#define main s2_unused_full_regression_main
#include "tb_m3_s2.cpp"
#undef main

int main() {
    static_assert(S2_P==1 && S2_NUM==8 && S2_PACK==1,"r9 P1 W8 diagnostic only");
    const char *env=getenv("S2_ROOT");root=env?env:".";
    auto w=read<uint64_t>(golden()+"weights_engine.bin");
    auto x=read<uint64_t>(golden()+"a/x_in_i16.bin");
    Buffers b(1,12);
    b.cls.resize(10,0x9ac51e37u); // whole 64-bit words in the AXI BFM
    check(call(w,x,b,0,S2_LOAD,0,0)==S2_OK,"weight load");
    guard(b.feat,0);guard(b.lg,0);
    for (uint32_t c:b.cls) check(c==0x9ac51e37u,"load class guard");
    // DUMP includes 12 layer features, logits and class, NOT CLASS_ONLY timing.
    check(call(w,x,b,1,S2_DUMP,0,11,0)==S2_OK,"full n1 dump");
    for(int l=0;l<12;l++) {
        block(b.feat,l*7938,read<int32_t>(golden()+"a/L"+std::to_string(l)+"_x_out_i4.bin"),"layer");
        printf("S2_RTL_N1_LAYER_PASS layer=%d elements=15876\n",l);
    }
    logits(b,0,"a");guard(b.feat,12*7938);guard(b.lg,16);
    for(size_t i=1;i<b.cls.size();i++) check(b.cls[i]==0x9ac51e37u,"class guard");
    printf("S2_RTL_N1_TB_PASS calls=2 inference=1 layers=12 seed=0 mode=DUMP_NOT_CLASS_ONLY\n");
    return 0;
}
