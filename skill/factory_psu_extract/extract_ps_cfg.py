"""从 Vivado 块设计 .bd（JSON）抽出 PS 单元的全部 CONFIG 参数，写成 set_property tcl；或对比两个 .bd 的 PS 配置。

用法见同目录 README.md。只用 Python 标准库。
PS 单元按 vlnv 自动找（zynq_ultra_ps_e = ZU+，processing_system7 = Zynq-7000），也可用 --cell 指定。
.bd 只存非默认值，导出的就是在 GUI 里改过（或板卡预设带来）的那些。
"""
import argparse
import json
import sys
from pathlib import Path

PS_IPS = ('zynq_ultra_ps_e', 'processing_system7')
# 摘要里打印的关键项（存在才打印）：DDR、CPU 频率、常用外设 IO、PL 时钟、AXI 口
SUMMARY = (
    'PSU__DDRC__DEVICE_CAPACITY', 'PSU__DDRC__SPEED_BIN', 'PSU__DDRC__BUS_WIDTH', 'PSU__DDRC__DRAM_WIDTH',
    'PSU__DDRC__COMPONENTS', 'PSU__DDRC__ECC', 'PSU__DDRC__FREQ_MHZ', 'PSU__CRF_APB__ACPU_CTRL__FREQMHZ',
    'PSU__UART0__PERIPHERAL__IO', 'PSU__UART1__PERIPHERAL__IO', 'PSU__SD0__PERIPHERAL__IO', 'PSU__SD1__PERIPHERAL__IO',
    'PSU__ENET3__PERIPHERAL__IO', 'PSU__QSPI__PERIPHERAL__DATA_MODE', 'PSU__USB0__PERIPHERAL__IO', 'PSU__DP__LANE_SEL',
    'PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ', 'PSU__CRL_APB__PL1_REF_CTRL__FREQMHZ',
    'PSU__USE__M_AXI_GP0', 'PSU__USE__M_AXI_GP2', 'PSU__USE__S_AXI_GP2', 'PSU__USE__S_AXI_GP3', 'PSU__USE__IRQ0',
    'PCW_UIPARAM_DDR_PARTNO', 'PCW_UIPARAM_DDR_BUS_WIDTH', 'PCW_APU_PERIPHERAL_FREQMHZ', 'PCW_UART1_PERIPHERAL_ENABLE',
    'PCW_UART1_UART1_IO', 'PCW_SD0_PERIPHERAL_ENABLE', 'PCW_ENET0_PERIPHERAL_ENABLE', 'PCW_QSPI_PERIPHERAL_ENABLE',
    'PCW_FPGA0_PERIPHERAL_FREQMHZ', 'PCW_USE_M_AXI_GP0', 'PCW_USE_S_AXI_HP0', 'PCW_USE_S_AXI_HP1', 'PCW_USE_FABRIC_INTERRUPT',
)


def load_ps(bd_path, cell=None):
    """返回 (单元名, vlnv, {参数: 值}, design_info)。"""
    design = json.loads(Path(bd_path).read_text(encoding='utf-8'))['design']
    comps = design['components']
    if cell is None:
        found = [k for k, v in comps.items() if any(f':{ip}:' in v.get('vlnv', '') for ip in PS_IPS)]
        if len(found) != 1:
            sys.exit(f'错误：{bd_path} 顶层找到 {len(found)} 个 PS 单元 {found}，用 --cell 指定')
        cell = found[0]
    if cell not in comps:
        sys.exit(f'错误：{bd_path} 顶层没有单元 {cell}')
    params = {k: v['value'] for k, v in comps[cell].get('parameters', {}).items()}
    return cell, comps[cell]['vlnv'], params, design.get('design_info', {})


def extract(a):
    cell, vlnv, params, info = load_ps(a.bd, a.cell)
    lines = [f'# 由 extract_ps_cfg.py 从 {Path(a.bd).name}（Vivado {info.get("tool_version", "?")}，'
             f'part {info.get("device", "?")}）抽出，勿手改',
             f'set {cell} [ create_bd_cell -type ip -vlnv {vlnv} {cell} ]',
             'set_property -dict [ list \\']
    lines += [f'   CONFIG.{k} {{{params[k]}}} \\' for k in sorted(params)]
    lines.append(f' ] ${cell}')
    Path(a.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{cell} ({vlnv}): {len(params)} parameters -> {a.out}')
    for k in SUMMARY:
        if k in params:
            print(f'  {k} = {params[k]}')


def diff(a):
    ca, va, pa, _ = load_ps(a.bd, a.cell)
    cb, vb, pb, _ = load_ps(a.diff, a.cell)
    if va != vb:
        print(f'注意：vlnv 不同 {va} vs {vb}')
    keys = sorted(set(pa) | set(pb))
    changed = [k for k in keys if pa.get(k) != pb.get(k)]
    print(f'A = {a.bd}（{ca}，{len(pa)} 项）')
    print(f'B = {a.diff}（{cb}，{len(pb)} 项）')
    print(f'不同 {len(changed)} 项（"<默认>" = 该 .bd 未存，即 IP 默认值）：')
    for k in changed:
        x, y = pa.get(k, '<默认>'), pb.get(k, '<默认>')
        tag = '（派生：Vivado 按时钟分配算出的实际频率）' if k.endswith('ACT_FREQMHZ') else ''
        if '|' in x and '|' in y:
            ix, iy = x.split('|'), y.split('|')
            x = '|'.join(i for i in ix if i not in iy) + f'（列表 {len(ix)} 项中）'
            y = '|'.join(i for i in iy if i not in ix)
        print(f'  {k}: {x} -> {y}{tag}')
    return 1 if a.expect is not None and len(changed) != a.expect else 0


def main():
    ap = argparse.ArgumentParser(description='从 .bd 抽 PS CONFIG 成 tcl，或对比两个 .bd 的 PS 配置')
    ap.add_argument('bd', help='块设计 .bd（厂商出厂工程或任意工程）')
    ap.add_argument('out', nargs='?', help='输出 tcl（抽取模式必填）')
    ap.add_argument('--cell', help='PS 单元名；不给则按 vlnv 自动找')
    ap.add_argument('--diff', metavar='BD2', help='对比模式：列出 BD2 与 bd 的 PS 参数差异')
    ap.add_argument('--expect', type=int, help='对比模式：差异项数不等于该值时退出码 1')
    a = ap.parse_args()
    if a.diff:
        return diff(a)
    if not a.out:
        ap.error('抽取模式需要 out')
    extract(a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
