// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2020.2 (64-bit)
// Copyright 1986-2020 Xilinx, Inc. All Rights Reserved.
// ==============================================================
// CTRL
// 0x00 : Control signals
//        bit 0  - ap_start (Read/Write/COH)
//        bit 1  - ap_done (Read/COR)
//        bit 2  - ap_idle (Read)
//        bit 3  - ap_ready (Read)
//        bit 7  - auto_restart (Read/Write)
//        others - reserved
// 0x04 : Global Interrupt Enable Register
//        bit 0  - Global Interrupt Enable (Read/Write)
//        others - reserved
// 0x08 : IP Interrupt Enable Register (Read/Write)
//        bit 0  - enable ap_done interrupt (Read/Write)
//        bit 1  - enable ap_ready interrupt (Read/Write)
//        others - reserved
// 0x0c : IP Interrupt Status Register (Read/TOW)
//        bit 0  - ap_done (COR/TOW)
//        bit 1  - ap_ready (COR/TOW)
//        others - reserved
// 0x10 : Data signal of ap_return
//        bit 31~0 - ap_return[31:0] (Read)
// 0x18 : Data signal of x_in
//        bit 31~0 - x_in[31:0] (Read/Write)
// 0x1c : reserved
// 0x20 : Data signal of cube
//        bit 31~0 - cube[31:0] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of x_out
//        bit 31~0 - x_out[31:0] (Read/Write)
// 0x2c : reserved
// 0x30 : Data signal of q_out
//        bit 31~0 - q_out[31:0] (Read/Write)
// 0x34 : reserved
// 0x38 : Data signal of k_out
//        bit 31~0 - k_out[31:0] (Read/Write)
// 0x3c : reserved
// 0x40 : Data signal of v_out
//        bit 31~0 - v_out[31:0] (Read/Write)
// 0x44 : reserved
// 0x48 : Data signal of stats_out
//        bit 31~0 - stats_out[31:0] (Read/Write)
// 0x4c : reserved
// 0x50 : Data signal of w_ddr
//        bit 31~0 - w_ddr[31:0] (Read/Write)
// 0x54 : reserved
// 0x58 : Data signal of cube_w
//        bit 31~0 - cube_w[31:0] (Read/Write)
// 0x5c : reserved
// 0x60 : Data signal of seg_row
//        bit 31~0 - seg_row[31:0] (Read/Write)
// 0x64 : reserved
// 0x68 : Data signal of seg_col
//        bit 31~0 - seg_col[31:0] (Read/Write)
// 0x6c : reserved
// 0x70 : Data signal of n_patch
//        bit 31~0 - n_patch[31:0] (Read/Write)
// 0x74 : reserved
// 0x78 : Data signal of layer_lo
//        bit 31~0 - layer_lo[31:0] (Read/Write)
// 0x7c : reserved
// 0x80 : Data signal of layer_hi
//        bit 31~0 - layer_hi[31:0] (Read/Write)
// 0x84 : reserved
// 0x88 : Data signal of proj_mask
//        bit 31~0 - proj_mask[31:0] (Read/Write)
// 0x8c : reserved
// 0x90 : Data signal of mode
//        bit 31~0 - mode[31:0] (Read/Write)
// 0x94 : reserved
// 0x98 : Data signal of cycles
//        bit 31~0 - cycles[31:0] (Read)
// 0x9c : Control signal of cycles
//        bit 0  - cycles_ap_vld (Read/COR)
//        others - reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XTT_ENGINE_CTRL_ADDR_AP_CTRL        0x00
#define XTT_ENGINE_CTRL_ADDR_GIE            0x04
#define XTT_ENGINE_CTRL_ADDR_IER            0x08
#define XTT_ENGINE_CTRL_ADDR_ISR            0x0c
#define XTT_ENGINE_CTRL_ADDR_AP_RETURN      0x10
#define XTT_ENGINE_CTRL_BITS_AP_RETURN      32
#define XTT_ENGINE_CTRL_ADDR_X_IN_DATA      0x18
#define XTT_ENGINE_CTRL_BITS_X_IN_DATA      32
#define XTT_ENGINE_CTRL_ADDR_CUBE_DATA      0x20
#define XTT_ENGINE_CTRL_BITS_CUBE_DATA      32
#define XTT_ENGINE_CTRL_ADDR_X_OUT_DATA     0x28
#define XTT_ENGINE_CTRL_BITS_X_OUT_DATA     32
#define XTT_ENGINE_CTRL_ADDR_Q_OUT_DATA     0x30
#define XTT_ENGINE_CTRL_BITS_Q_OUT_DATA     32
#define XTT_ENGINE_CTRL_ADDR_K_OUT_DATA     0x38
#define XTT_ENGINE_CTRL_BITS_K_OUT_DATA     32
#define XTT_ENGINE_CTRL_ADDR_V_OUT_DATA     0x40
#define XTT_ENGINE_CTRL_BITS_V_OUT_DATA     32
#define XTT_ENGINE_CTRL_ADDR_STATS_OUT_DATA 0x48
#define XTT_ENGINE_CTRL_BITS_STATS_OUT_DATA 32
#define XTT_ENGINE_CTRL_ADDR_W_DDR_DATA     0x50
#define XTT_ENGINE_CTRL_BITS_W_DDR_DATA     32
#define XTT_ENGINE_CTRL_ADDR_CUBE_W_DATA    0x58
#define XTT_ENGINE_CTRL_BITS_CUBE_W_DATA    32
#define XTT_ENGINE_CTRL_ADDR_SEG_ROW_DATA   0x60
#define XTT_ENGINE_CTRL_BITS_SEG_ROW_DATA   32
#define XTT_ENGINE_CTRL_ADDR_SEG_COL_DATA   0x68
#define XTT_ENGINE_CTRL_BITS_SEG_COL_DATA   32
#define XTT_ENGINE_CTRL_ADDR_N_PATCH_DATA   0x70
#define XTT_ENGINE_CTRL_BITS_N_PATCH_DATA   32
#define XTT_ENGINE_CTRL_ADDR_LAYER_LO_DATA  0x78
#define XTT_ENGINE_CTRL_BITS_LAYER_LO_DATA  32
#define XTT_ENGINE_CTRL_ADDR_LAYER_HI_DATA  0x80
#define XTT_ENGINE_CTRL_BITS_LAYER_HI_DATA  32
#define XTT_ENGINE_CTRL_ADDR_PROJ_MASK_DATA 0x88
#define XTT_ENGINE_CTRL_BITS_PROJ_MASK_DATA 32
#define XTT_ENGINE_CTRL_ADDR_MODE_DATA      0x90
#define XTT_ENGINE_CTRL_BITS_MODE_DATA      32
#define XTT_ENGINE_CTRL_ADDR_CYCLES_DATA    0x98
#define XTT_ENGINE_CTRL_BITS_CYCLES_DATA    32
#define XTT_ENGINE_CTRL_ADDR_CYCLES_CTRL    0x9c

