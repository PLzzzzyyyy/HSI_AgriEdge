"""对比两个 XSA 里 PS 初始化代码（psu_init.c / ps7_init.c）的寄存器写序列，确认改动只落在预期的寄存器上。

用法：python diff_xsa_init.py <A.xsa> <B.xsa> [--expect N]
XSA 是 zip，里面的 psu_init.c（ZU+）或 ps7_init.c（Zynq-7000）是 Vivado 按 PS CONFIG 生成、FSBL 上电执行的寄存器写。
比对单位是 (寄存器, 掩码, 值) 三元组序列；输出 unified diff。--expect 给出差异块数，不等时退出码 1。
"""
import argparse
import difflib
import re
import sys
import zipfile

PAT = {
    # 值可以是运行时变量（SERDES 校准函数里的 ill12_val[i]），照原文比
    'psu_init.c': re.compile(r'PSU_Mask_Write\((\w+)\s*,\s*(0x[0-9A-F]+U?)\s*,\s*([^;]+?)\);', re.I),
    # ps7_init.c 是数据表：EMIT_MASKWRITE(addr, mask, val)
    'ps7_init.c': re.compile(r'EMIT_MASKWRITE\((0X[0-9A-F]+)\s*,\s*(0x[0-9A-F]+U?L?)\s*,\s*(0x[0-9A-F]+U?L?)\)', re.I),
}


def writes(xsa):
    z = zipfile.ZipFile(xsa)
    for name, pat in PAT.items():
        if name in z.namelist():
            return name, [' '.join(m) for m in pat.findall(z.read(name).decode(errors='replace'))]
    sys.exit(f'错误：{xsa} 里没有 psu_init.c / ps7_init.c')


def main():
    ap = argparse.ArgumentParser(description='对比两个 XSA 的 PS 初始化寄存器写')
    ap.add_argument('a')
    ap.add_argument('b')
    ap.add_argument('--expect', type=int, help='期望的差异块数')
    a = ap.parse_args()
    na, wa = writes(a.a)
    nb, wb = writes(a.b)
    if na != nb:
        sys.exit(f'错误：两个 XSA 的 PS 类型不同（{na} vs {nb}）')
    if not wa or not wb:
        sys.exit(f'错误：{na} 里没解析到寄存器写（格式变了？）')
    print(f'{na}：A {len(wa)} 次写，B {len(wb)} 次写')
    hunks = 0
    for ln in difflib.unified_diff(wa, wb, 'A', 'B', lineterm='', n=0):
        hunks += ln.startswith('@@')
        print(ln)
    print(f'差异块 {hunks} 个')
    return 1 if a.expect is not None and hunks != a.expect else 0


if __name__ == '__main__':
    sys.exit(main())
