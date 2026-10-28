#ifndef TT_M3A_APP_H
#define TT_M3A_APP_H
#include "m3a_sd.h"
#include "m3a_roi.h"
struct TTM3aAppSession {
    bool attempted;
    TTM3aSdSession sd;
    TTM3aRoiSession roi;
    int driver_status;
};
// Single attempt for the App lifetime, including LOAD_W timeouts. No retry or
// new session over these buffers without external PL reset + App restart.
// Caller must retain static buffers on halted, never return to CRT/cleanup.
int tt_m3a_app_once(TTM3aAppSession &, const TTM3aSdProfile &,
                   const TTM3aSdStorage &, const TTM3aRoiRequest &);
#endif
