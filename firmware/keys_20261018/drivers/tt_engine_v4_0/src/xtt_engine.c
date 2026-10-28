// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2020.2 (64-bit)
// Copyright 1986-2020 Xilinx, Inc. All Rights Reserved.
// ==============================================================
/***************************** Include Files *********************************/
#include "xtt_engine.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XTt_engine_CfgInitialize(XTt_engine *InstancePtr, XTt_engine_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Ctrl_BaseAddress = ConfigPtr->Ctrl_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XTt_engine_Start(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL) & 0x80;
    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XTt_engine_IsDone(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XTt_engine_IsIdle(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XTt_engine_IsReady(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XTt_engine_EnableAutoRestart(XTt_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL, 0x80);
}

void XTt_engine_DisableAutoRestart(XTt_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_CTRL, 0);
}

u32 XTt_engine_Get_return(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_AP_RETURN);
    return Data;
}
void XTt_engine_Set_x_in(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_X_IN_DATA, Data);
}

u32 XTt_engine_Get_x_in(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_X_IN_DATA);
    return Data;
}

void XTt_engine_Set_cube(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_CUBE_DATA, Data);
}

u32 XTt_engine_Get_cube(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_CUBE_DATA);
    return Data;
}

void XTt_engine_Set_x_out(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_X_OUT_DATA, Data);
}

u32 XTt_engine_Get_x_out(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_X_OUT_DATA);
    return Data;
}

void XTt_engine_Set_q_out(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_Q_OUT_DATA, Data);
}

u32 XTt_engine_Get_q_out(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_Q_OUT_DATA);
    return Data;
}

void XTt_engine_Set_k_out(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_K_OUT_DATA, Data);
}

u32 XTt_engine_Get_k_out(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_K_OUT_DATA);
    return Data;
}

void XTt_engine_Set_v_out(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_V_OUT_DATA, Data);
}

u32 XTt_engine_Get_v_out(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_V_OUT_DATA);
    return Data;
}

void XTt_engine_Set_stats_out(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_STATS_OUT_DATA, Data);
}

u32 XTt_engine_Get_stats_out(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_STATS_OUT_DATA);
    return Data;
}

void XTt_engine_Set_w_ddr(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_W_DDR_DATA, Data);
}

u32 XTt_engine_Get_w_ddr(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_W_DDR_DATA);
    return Data;
}

void XTt_engine_Set_cube_w(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_CUBE_W_DATA, Data);
}

u32 XTt_engine_Get_cube_w(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_CUBE_W_DATA);
    return Data;
}

void XTt_engine_Set_seg_row(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_SEG_ROW_DATA, Data);
}

u32 XTt_engine_Get_seg_row(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_SEG_ROW_DATA);
    return Data;
}

void XTt_engine_Set_seg_col(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_SEG_COL_DATA, Data);
}

u32 XTt_engine_Get_seg_col(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_SEG_COL_DATA);
    return Data;
}

void XTt_engine_Set_n_patch(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_N_PATCH_DATA, Data);
}

u32 XTt_engine_Get_n_patch(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_N_PATCH_DATA);
    return Data;
}

void XTt_engine_Set_layer_lo(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_LAYER_LO_DATA, Data);
}

u32 XTt_engine_Get_layer_lo(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_LAYER_LO_DATA);
    return Data;
}

void XTt_engine_Set_layer_hi(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_LAYER_HI_DATA, Data);
}

u32 XTt_engine_Get_layer_hi(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_LAYER_HI_DATA);
    return Data;
}

void XTt_engine_Set_proj_mask(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_PROJ_MASK_DATA, Data);
}

u32 XTt_engine_Get_proj_mask(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_PROJ_MASK_DATA);
    return Data;
}

void XTt_engine_Set_mode(XTt_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_MODE_DATA, Data);
}

u32 XTt_engine_Get_mode(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_MODE_DATA);
    return Data;
}

u32 XTt_engine_Get_cycles(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_CYCLES_DATA);
    return Data;
}

u32 XTt_engine_Get_cycles_vld(XTt_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_CYCLES_CTRL);
    return Data & 0x1;
}

void XTt_engine_InterruptGlobalEnable(XTt_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_GIE, 1);
}

void XTt_engine_InterruptGlobalDisable(XTt_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_GIE, 0);
}

void XTt_engine_InterruptEnable(XTt_engine *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_IER);
    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_IER, Register | Mask);
}

void XTt_engine_InterruptDisable(XTt_engine *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_IER);
    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_IER, Register & (~Mask));
}

void XTt_engine_InterruptClear(XTt_engine *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTt_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_ISR, Mask);
}

u32 XTt_engine_InterruptGetEnabled(XTt_engine *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_IER);
}

u32 XTt_engine_InterruptGetStatus(XTt_engine *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTt_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XTT_ENGINE_CTRL_ADDR_ISR);
}

