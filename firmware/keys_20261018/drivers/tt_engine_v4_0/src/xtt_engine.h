// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2020.2 (64-bit)
// Copyright 1986-2020 Xilinx, Inc. All Rights Reserved.
// ==============================================================
#ifndef XTT_ENGINE_H
#define XTT_ENGINE_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xtt_engine_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
    u16 DeviceId;
    u32 Ctrl_BaseAddress;
} XTt_engine_Config;
#endif

typedef struct {
    u64 Ctrl_BaseAddress;
    u32 IsReady;
} XTt_engine;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XTt_engine_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XTt_engine_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XTt_engine_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XTt_engine_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
int XTt_engine_Initialize(XTt_engine *InstancePtr, u16 DeviceId);
XTt_engine_Config* XTt_engine_LookupConfig(u16 DeviceId);
int XTt_engine_CfgInitialize(XTt_engine *InstancePtr, XTt_engine_Config *ConfigPtr);
#else
int XTt_engine_Initialize(XTt_engine *InstancePtr, const char* InstanceName);
int XTt_engine_Release(XTt_engine *InstancePtr);
#endif

void XTt_engine_Start(XTt_engine *InstancePtr);
u32 XTt_engine_IsDone(XTt_engine *InstancePtr);
u32 XTt_engine_IsIdle(XTt_engine *InstancePtr);
u32 XTt_engine_IsReady(XTt_engine *InstancePtr);
void XTt_engine_EnableAutoRestart(XTt_engine *InstancePtr);
void XTt_engine_DisableAutoRestart(XTt_engine *InstancePtr);
u32 XTt_engine_Get_return(XTt_engine *InstancePtr);

void XTt_engine_Set_x_in(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_x_in(XTt_engine *InstancePtr);
void XTt_engine_Set_cube(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_cube(XTt_engine *InstancePtr);
void XTt_engine_Set_x_out(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_x_out(XTt_engine *InstancePtr);
void XTt_engine_Set_q_out(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_q_out(XTt_engine *InstancePtr);
void XTt_engine_Set_k_out(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_k_out(XTt_engine *InstancePtr);
void XTt_engine_Set_v_out(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_v_out(XTt_engine *InstancePtr);
void XTt_engine_Set_stats_out(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_stats_out(XTt_engine *InstancePtr);
void XTt_engine_Set_w_ddr(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_w_ddr(XTt_engine *InstancePtr);
void XTt_engine_Set_cube_w(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_cube_w(XTt_engine *InstancePtr);
void XTt_engine_Set_seg_row(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_seg_row(XTt_engine *InstancePtr);
void XTt_engine_Set_seg_col(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_seg_col(XTt_engine *InstancePtr);
void XTt_engine_Set_n_patch(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_n_patch(XTt_engine *InstancePtr);
void XTt_engine_Set_layer_lo(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_layer_lo(XTt_engine *InstancePtr);
void XTt_engine_Set_layer_hi(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_layer_hi(XTt_engine *InstancePtr);
void XTt_engine_Set_proj_mask(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_proj_mask(XTt_engine *InstancePtr);
void XTt_engine_Set_mode(XTt_engine *InstancePtr, u32 Data);
u32 XTt_engine_Get_mode(XTt_engine *InstancePtr);
u32 XTt_engine_Get_cycles(XTt_engine *InstancePtr);
u32 XTt_engine_Get_cycles_vld(XTt_engine *InstancePtr);

void XTt_engine_InterruptGlobalEnable(XTt_engine *InstancePtr);
void XTt_engine_InterruptGlobalDisable(XTt_engine *InstancePtr);
void XTt_engine_InterruptEnable(XTt_engine *InstancePtr, u32 Mask);
void XTt_engine_InterruptDisable(XTt_engine *InstancePtr, u32 Mask);
void XTt_engine_InterruptClear(XTt_engine *InstancePtr, u32 Mask);
u32 XTt_engine_InterruptGetEnabled(XTt_engine *InstancePtr);
u32 XTt_engine_InterruptGetStatus(XTt_engine *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
