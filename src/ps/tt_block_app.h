#ifndef TT_BLOCK_APP_H
#define TT_BLOCK_APP_H
#include "tt_net.h"

// Board entry points. Uses the embedded 64x64 N=6 block and existing PL IP.
bool tt_block_check(const TTNet &net);
void tt_block_run(const TTNet &net, bool pipelined);
#endif
