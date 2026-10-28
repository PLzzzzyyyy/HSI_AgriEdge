// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2020.2 (64-bit)
// Copyright 1986-2020 Xilinx, Inc. All Rights Reserved.
// ==============================================================
#ifndef __linux__

#include "xstatus.h"
#include "xparameters.h"
#include "xtt_engine.h"

extern XTt_engine_Config XTt_engine_ConfigTable[];

XTt_engine_Config *XTt_engine_LookupConfig(u16 DeviceId) {
	XTt_engine_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XTT_ENGINE_NUM_INSTANCES; Index++) {
		if (XTt_engine_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XTt_engine_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XTt_engine_Initialize(XTt_engine *InstancePtr, u16 DeviceId) {
	XTt_engine_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XTt_engine_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XTt_engine_CfgInitialize(InstancePtr, ConfigPtr);
}

#endif

