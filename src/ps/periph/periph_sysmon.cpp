// C3d：AMS 里的 PS SYSMON 与 PL SYSMON，读温度与供电（当前值 + 上电以来最大最小）。不改序列器，用上电默认配置，
// 与厂商 course_s2/11_ps_sysmon 相同。通道含义：PS 块 1/2/6 = VCC_PSINTLP / VCC_PSINTFP / VCC_PSAUX（xsysmonpsu.h），
// PL 块 1/2/6 = VCCINT / VCCAUX / VCCBRAM（UG580 SYSMONE4）。额定值按 xazu5ev -1（非 L 档）：0.85 V 与 1.8 V。
#include "periph.h"
#include <stdio.h>
#include "xparameters.h"
#include "xsysmonpsu.h"

namespace {

XSysMonPsu g_sm;

struct Rail {
    const char *name;
    u8 ch, max_id, min_id;
    u32 block;
    float nominal;   // 0 = 温度
};

const Rail RAILS[] = {
    {"PS temp (LPD)", XSM_CH_TEMP, XSM_MAX_TEMP, XSM_MIN_TEMP, XSYSMON_PS, 0},
    {"PS VCC_PSINTLP", XSM_CH_SUPPLY1, XSM_MAX_SUPPLY1, XSM_MIN_SUPPLY1, XSYSMON_PS, 0.85f},
    {"PS VCC_PSINTFP", XSM_CH_SUPPLY2, XSM_MAX_SUPPLY2, XSM_MIN_SUPPLY2, XSYSMON_PS, 0.85f},
    {"PS VCC_PSAUX", XSM_CH_SUPPLY3, XSM_MAX_SUPPLY3, XSM_MIN_SUPPLY3, XSYSMON_PS, 1.8f},
    {"PL temp", XSM_CH_TEMP, XSM_MAX_TEMP, XSM_MIN_TEMP, XSYSMON_PL, 0},
    {"PL VCCINT", XSM_CH_SUPPLY1, XSM_MAX_SUPPLY1, XSM_MIN_SUPPLY1, XSYSMON_PL, 0.85f},
    {"PL VCCAUX", XSM_CH_SUPPLY2, XSM_MAX_SUPPLY2, XSM_MIN_SUPPLY2, XSYSMON_PL, 1.8f},
    {"PL VCCBRAM", XSM_CH_SUPPLY3, XSM_MAX_SUPPLY3, XSM_MIN_SUPPLY3, XSYSMON_PL, 0.85f},
};

float convert(u16 raw, bool temp) {
    return temp ? XSysMonPsu_RawToTemperature_OnChip(raw) : XSysMonPsu_RawToVoltage(raw);
}

}  // namespace

bool sysmon_test() {
    printf("\n--- C3d SYSMON: current / min / max since power-up; PASS window temp 10..85 C, supplies nominal +-5%% ---\n");
    XSysMonPsu_Config *cfg = XSysMonPsu_LookupConfig(XPAR_XSYSMONPSU_0_DEVICE_ID);
    if (cfg == nullptr || XSysMonPsu_CfgInitialize(&g_sm, cfg, cfg->BaseAddress) != XST_SUCCESS) {
        printf("C3d SYSMON FAIL: driver init\n");
        return false;
    }
    bool pass = true;
    for (const Rail &r : RAILS) {
        const bool temp = r.nominal == 0;
        const float cur = convert(XSysMonPsu_GetAdcData(&g_sm, r.ch, r.block), temp);
        const float mx = convert(XSysMonPsu_GetMinMaxMeasurement(&g_sm, r.max_id, r.block), temp);
        const float mn = convert(XSysMonPsu_GetMinMaxMeasurement(&g_sm, r.min_id, r.block), temp);
        const bool ok = temp ? (cur > 10.0f && cur < 85.0f) : (cur > r.nominal * 0.95f && cur < r.nominal * 1.05f);
        if (!ok) pass = false;
        printf("  %-16s %8.3f %s  (min %8.3f, max %8.3f)  %s\n", r.name, cur, temp ? "C" : "V", mn, mx, ok ? "OK" : "OUT OF RANGE");
    }
    printf("C3d SYSMON %s\n", pass ? "PASS" : "FAIL (PL rows all near 0 or -280 C = PL SYSMON not reachable: bitstream not loaded?)");
    return pass;
}
