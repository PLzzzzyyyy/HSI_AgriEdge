// Host-only declarations for testing the real asynchronous driver and cache order.
#ifndef TT_TEST_XTUCKER_PROJ_H
#define TT_TEST_XTUCKER_PROJ_H
#include <stdint.h>
typedef uint32_t u32;
typedef intptr_t INTPTR;
typedef uintptr_t UINTPTR;
#define XST_SUCCESS 0
struct XTucker_proj {};
int XTucker_proj_Initialize(XTucker_proj *, int);
void XTucker_proj_Start(XTucker_proj *);
int XTucker_proj_IsDone(XTucker_proj *);
void XTucker_proj_Set_in_r(XTucker_proj *, u32);
void XTucker_proj_Set_out_q(XTucker_proj *, u32);
void XTucker_proj_Set_out_k(XTucker_proj *, u32);
void XTucker_proj_Set_out_v(XTucker_proj *, u32);
void XTucker_proj_Set_stats(XTucker_proj *, u32);
void XTucker_proj_Set_w_q(XTucker_proj *, u32);
void XTucker_proj_Set_w_k(XTucker_proj *, u32);
void XTucker_proj_Set_w_v(XTucker_proj *, u32);
void XTucker_proj_Set_n_tok(XTucker_proj *, u32);
void XTucker_proj_Set_n_proj(XTucker_proj *, u32);
#endif
