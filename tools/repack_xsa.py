#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把解压后的 XSA 目录重新打包成 .xsa。

★ 为什么不用 PowerShell 的 Compress-Archive：
  PowerShell 5.1 打出来的 zip，子目录条目用**反斜杠**做分隔符
  （drivers\\conv_v1_0\\src\\Makefile）。XSA 是 zip，而 Vitis 是 Java 写的，
  Java 的 ZipFile 只认正斜杠，于是读不到 drivers/ 下的驱动，
  建平台时报找不到驱动或直接静默用错版本。
  Python 的 zipfile 写 arcname 时统一转正斜杠，没这个问题。

  同理：改 Xilinx 工具链的文本文件一律用 Python，别用 PowerShell 的
  文本 cmdlet（Set-Content -Encoding UTF8 会加 BOM 并破坏中文注释，
  见 docs/PITFALLS.md）。

用法：
  python tools/repack_xsa.py <解压后的目录> <输出.xsa>

打包后会自检一遍：列出所有条目，确认没有反斜杠。
"""
import os
import sys
import zipfile


def repack(src_dir, out_path):
    src_dir = os.path.abspath(src_dir)
    if not os.path.isdir(src_dir):
        print("不是目录：%s" % src_dir)
        return 1

    if os.path.exists(out_path):
        os.remove(out_path)

    n = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, filenames in os.walk(src_dir):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, src_dir).replace(os.sep, "/")
                z.write(full, arc)
                n += 1

    # ---- 自检 ----
    bad = []
    with zipfile.ZipFile(out_path) as z:
        names = z.namelist()
        bad = [x for x in names if "\\" in x]

    print("打包 %d 个文件 -> %s (%d 字节)" % (n, out_path, os.path.getsize(out_path)))
    if bad:
        print("✗ 仍有 %d 个条目含反斜杠：" % len(bad))
        for b in bad:
            print("   ", b)
        return 1
    print("✓ 所有条目均为正斜杠")
    return 0


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    return repack(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
