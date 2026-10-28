#include <ap_int.h>
#include <cstdint>
#include <cstdio>
void m3_quant_micro(ap_int<18>[14],ap_int<21>[7],int,int,int,ap_int<8>[21]);
static int ref(int x,int e) {
    int64_t den=INT64_C(1)<<e,n=int64_t(x)+(e?den/2:0),q=n/den;
    if (n<0 && n%den) --q;
    return q<-128?-128:q>127?127:int(q);
}
int main() {
    ap_int<18> a[14];ap_int<21>b[7];ap_int<8>y[21];
    uint32_t rng=0x95136;
    for (int k=0;k<100;++k) {
        for (int i=0;i<14;++i) {rng=rng*1664525u+1013904223u;a[i]=int(rng&262143)-131072;}
        for (int i=0;i<7;++i) {rng=rng*1664525u+1013904223u;b[i]=int(rng&2097151)-1048576;}
        a[0]=-113792;a[1]=114688;a[2]=-1;a[3]=1;
        b[0]=-877824;b[1]=884736;b[2]=-1;b[3]=1;
        int e1=k%25,e2=(k+8)%25,e3=(k+16)%25;
        m3_quant_micro(a,b,e1,e2,e3,y);
        for (int i=0;i<21;++i) {
            int x=i<14?int(a[i]):int(b[i-14]),e=i<7?e1:i<14?e2:e3;
            if (int(y[i])!=ref(x,e)) {std::printf("M3_QUANT_MICRO_FAIL %d %d\n",k,i);return 1;}
        }
    }
    std::puts("M3_QUANT_MICRO_PASS transactions=100");return 0;
}
