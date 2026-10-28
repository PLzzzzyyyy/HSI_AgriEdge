"""从厂商 Vivado 工程的块设计 .bd（JSON）抽出 zynq_ultra_ps_e 的全部 CONFIG 参数，写成 set_property tcl。

用法：D:/pytorch/python.exe tools/extract_psu_cfg.py <design.bd> <out.tcl> [--cell zynq_ultra_ps_e_0]
.bd 只存非默认值，导出的就是厂商在 GUI 里改过的那些；与 build/vivado/ps7_cfg.tcl 同格式，供 build_zu5ev.tcl source。
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bd')
    ap.add_argument('out')
    ap.add_argument('--cell', default='zynq_ultra_ps_e_0')
    args = ap.parse_args()
    bd = json.loads(Path(args.bd).read_text(encoding='utf-8'))
    comps = bd['design']['components']
    cell = comps[args.cell]
    params = cell['parameters']
    vlnv = cell['vlnv']
    info = bd['design'].get('design_info', {})
    lines = [f'# 由 tools/extract_psu_cfg.py 从 {Path(args.bd).name}（Vivado {info.get("tool_version", "?")}，'
             f'part {info.get("device", "?")}）抽出，勿手改',
             f'set {args.cell} [ create_bd_cell -type ip -vlnv {vlnv} {args.cell} ]',
             'set_property -dict [ list \\']
    for k in sorted(params):
        v = params[k]['value']
        lines.append(f'   CONFIG.{k} {{{v}}} \\')
    lines.append(f' ] ${args.cell}')
    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{len(params)} parameters -> {args.out}')
    for key in ('PSU__DDRC__DEVICE_CAPACITY', 'PSU__DDRC__SPEED_BIN', 'PSU__DDRC__BUS_WIDTH', 'PSU__DDRC__DRAM_WIDTH',
                'PSU__DDRC__COMPONENTS', 'PSU__DDRC__ROW_ADDR_COUNT', 'PSU__DDRC__BG_ADDR_COUNT', 'PSU__DDRC__ECC',
                'PSU__DDRC__FREQ_MHZ', 'PSU__CRF_APB__ACPU_CTRL__FREQMHZ', 'PSU__UART0__PERIPHERAL__IO', 'PSU__UART1__PERIPHERAL__IO',
                'PSU__SD0__PERIPHERAL__IO', 'PSU__SD1__PERIPHERAL__IO', 'PSU__SD1__GRP_CD__IO', 'PSU__ENET3__PERIPHERAL__IO',
                'PSU__ENET3__GRP_MDIO__IO', 'PSU__QSPI__PERIPHERAL__DATA_MODE', 'PSU__USB0__PERIPHERAL__IO', 'PSU__DP__LANE_SEL',
                'PSU__DP__REF_CLK_FREQ', 'PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ', 'PSU__CRL_APB__PL1_REF_CTRL__FREQMHZ',
                'PSU__USE__M_AXI_GP0', 'PSU__USE__M_AXI_GP1', 'PSU__USE__M_AXI_GP2', 'PSU__USE__S_AXI_GP0', 'PSU__USE__S_AXI_GP2',
                'PSU__USE__S_AXI_GP3', 'PSU__USE__S_AXI_GP4', 'PSU__MAXIGP0__DATA_WIDTH', 'PSU__MAXIGP2__DATA_WIDTH',
                'PSU__SAXIGP2__DATA_WIDTH', 'PSU__USE__IRQ0', 'PSU__GPIO0_MIO__PERIPHERAL__ENABLE', 'PSU__GPIO1_MIO__PERIPHERAL__ENABLE',
                'PSU__TTC0__PERIPHERAL__ENABLE', 'PSU__I2C1__PERIPHERAL__IO', 'PSU__CAN1__PERIPHERAL__IO', 'PSU__SATA__PERIPHERAL__ENABLE',
                'PSU__PCIE__PERIPHERAL__ENABLE', 'PSU__USB3_0__PERIPHERAL__ENABLE'):
        if key in params:
            print(f'  {key} = {params[key]["value"]}')


if __name__ == '__main__':
    main()
