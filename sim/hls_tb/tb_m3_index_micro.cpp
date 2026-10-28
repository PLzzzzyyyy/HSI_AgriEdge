#include <stdint.h>
#include <stdio.h>
void m3_index_micro(const uint8_t command[1024],uint64_t trace[1024]);
int main() {
    uint8_t command[1024];uint64_t trace[1024];uint32_t rng=0x54ac;
    unsigned checks=0,ends=0,resets=0,stalls=0;
    // Idle-only, full runs + terminal stalls, stalls around column carries,
    // deterministic random enable/reset, and immediate reuse across calls.
    for (unsigned trial=0;trial<8;++trial) {
        for (unsigned n=0;n<1024;++n) {
            rng=rng*1664525u+1013904223u;
            command[n]=trial==0?0:trial<=2?1:trial==3?(n%55!=53):(rng>>28!=0);
            if ((trial==2 && n==500) || (trial==4 && n%173==0) ||
                (trial>=5 && (rng&511)==0)) command[n]|=2;
        }
        m3_index_micro(command,trace);
        unsigned flat=0;
        for (unsigned n=0;n<1024;++n) {
            if (command[n]&2) {flat=0;++resets;}
            uint64_t want=uint64_t(flat)|(uint64_t(flat/54)<<9)|(uint64_t(flat%54)<<12);
            if ((command[n]&1) && flat<378) {++flat;if(flat==378)++ends;}
            else ++stalls;
            want|=(uint64_t(flat)<<18)|(uint64_t(flat==378)<<27);
            if (trace[n]!=want) {
                fprintf(stderr,"INDEX_TRACE_FAIL trial=%u n=%u got=%llu want=%llu\n",trial,n,
                        (unsigned long long)trace[n],(unsigned long long)want);return 1;
            }
            ++checks;
        }
    }
    printf("M3_INDEX_MICRO_PASS checks=%u terminals=%u resets=%u stalls=%u\n",checks,ends,resets,stalls);
    return ends>=5 && resets>=5 && stalls>=1024?0:2;
}
