// Host-only declarations of the Vitis HLS driver for tt_engine (M2); the test supplies the definitions.
#ifndef TT_TEST_XTT_ENGINE_H
#define TT_TEST_XTT_ENGINE_H
#include "xtucker_proj.h"
struct XTt_engine {};
int XTt_engine_Initialize(XTt_engine *, int);
void XTt_engine_Start(XTt_engine *);
u32 XTt_engine_IsDone(XTt_engine *);
u32 XTt_engine_Get_return(XTt_engine *);
u32 XTt_engine_Get_cycles(XTt_engine *); // explicit synthetic fixture, never a hardware measurement
void XTt_engine_Set_x_in(XTt_engine *, u32);
void XTt_engine_Set_cube(XTt_engine *, u32);
void XTt_engine_Set_x_out(XTt_engine *, u32);
void XTt_engine_Set_q_out(XTt_engine *, u32);
void XTt_engine_Set_k_out(XTt_engine *, u32);
void XTt_engine_Set_v_out(XTt_engine *, u32);
void XTt_engine_Set_stats_out(XTt_engine *, u32);
void XTt_engine_Set_w_ddr(XTt_engine *, u32);
void XTt_engine_Set_cube_w(XTt_engine *, u32);
void XTt_engine_Set_seg_row(XTt_engine *, u32);
void XTt_engine_Set_seg_col(XTt_engine *, u32);
void XTt_engine_Set_n_patch(XTt_engine *, u32);
void XTt_engine_Set_layer_lo(XTt_engine *, u32);
void XTt_engine_Set_layer_hi(XTt_engine *, u32);
void XTt_engine_Set_proj_mask(XTt_engine *, u32);
void XTt_engine_Set_mode(XTt_engine *, u32);
#endif
