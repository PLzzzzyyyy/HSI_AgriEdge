#ifndef S1B_PROFILE_H
#define S1B_PROFILE_H
#include "m3a_sd.h"
// Exact already-accepted S1b profile. No regeneration or numeric changes.
// Origin: report/system_s1b/20261009_app_board_r1 and original S1b App.
#define S1B_CUBE_BYTES 243794880u
static const TTM3aSdProfile S1B_PROFILE={400,550,270,3,9,{
    {"1:/scenes/longkou/cube_f32.bin",243794880u,0xbf3b60c5u},
    {"1:/scenes/longkou/weights/v2/cls_token.bin",10584u,0xc85f498eu},
    {"1:/scenes/longkou/weights/v2/pos_embed.bin",63504u,0xf5113faeu},
    {"1:/scenes/longkou/weights/v2/weights_engine.bin",480576u,0x27231983u},
}};
#endif
