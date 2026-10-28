#include "s1_micro.h"
#include <cstdint>
#include <iostream>
static uint32_t state = 0x715134u;
static int sample() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return int(state & 255) - 128; }
int main() {
#ifdef TT_S1_COPY_TB
    s1_act input[2646], output[2646];
    for (int round = 0; round < 3; ++round) {
        for (unsigned ctx = 0; ctx < TT_S1_P; ++ctx) {
            for (int p = 0; p < 2646; ++p) input[p] = ((p * 17 + ctx * 67 + round * 29) & 255) - 128;
            s1_copy(0, ctx, input, output);
            s1_copy(1, ctx, input, output);
        }
        for (unsigned ctx = 0; ctx < TT_S1_P; ++ctx) {
            s1_copy(2, ctx, input, output);
            for (int p = 0; p < 2646; ++p)
                if (output[p] != ((p * 17 + ctx * 67 + round * 29) & 255) - 128) return 2;
        }
    }
    std::cout << "S1_COPY_PASS bits=" << TT_S1_BITS << " P=" << TT_S1_P << " rounds=3\n";
#else
    ap_int<8> x[54], w0[54], w1[54]; ap_int<21> y[2];
    for (int test = 0; test < 300; ++test) {
        long a = 0, b = 0;
        for (int j = 0; j < 54; ++j) {
            int xx = test < 4 ? (test & 1 ? 127 : -128) : sample();
            int ww = test < 4 ? (test & 2 ? 127 : -128) : sample();
            x[j] = xx; w0[j] = ww; w1[j] = test < 4 ? -127 : sample();
            a += xx * ww; b += xx * int(w1[j]);
        }
        s1_dot(x, w0, w1, y);
        if (y[0] != a || y[1] != b) return 1;
    }
    std::cout << "S1_DOT_PASS cases=300 pack=" << TT_S1_PACK << "\n";
#endif
    return 0;
}
