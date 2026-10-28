#!/usr/bin/env python3
"""
修复 Vitis HLS 生成的驱动 Makefile 在 Windows 下无法编译的问题

问题现象：
    process_begin: CreateProcess(NULL, #echo "Copying 'xconv_hw.h' ...) failed.
    make (e=2): 系统找不到指定的文件
    make[2]: *** [Makefile:40: ../../../include/xconv_hw.h] Error 2
    Failed to generate the platform.

根因：
    Vitis HLS 生成的驱动 Makefile 里，recipe（命令行）写成：

        $(INCLUDEDIR)/%.h: %.h
        <TAB>#echo "Copying '$<' to '$@'"
        <TAB>$(CP) $< $@

    在 Makefile 中，recipe 行以 TAB 开头，其内容会**原样传给 shell 执行**，
    `#` 在这里不是 Makefile 注释。Linux 的 sh 会把 `#` 当注释忽略，所以没事；
    但 Vitis 在 Windows 下用 `SHELL=CMD`，CMD 不认 `#`，
    于是试图执行一个名为 `#echo` 的程序 -> 失败。

    这是 Xilinx 工具在 Windows 上的已知缺陷，每次重新 export_design 都会复现。

修复：
    删除所有以 TAB + # 开头的 recipe 行。

用法：
    python tools/fix_hls_driver_makefile.py <目录1> [目录2] ...
    # 会递归查找其下所有 drivers/*/src/Makefile
"""
import os
import re
import sys


def fix_makefile(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    out, fixes = [], []
    for ln in lines:
        # ---- 坑 1（2020.2 生成器）：recipe 行里的 #echo ----
        # recipe 行 = TAB 开头；其内容原样交给 shell。
        # sh 把 # 当注释，CMD 不认，会去找一个叫 #echo 的程序。
        if ln.startswith("\t") and ln.lstrip("\t").startswith("#"):
            fixes.append("删除 -> " + ln.strip())
            continue

        # ---- 坑 2（2019.2 生成器）：变量里的通配符 ----
        # OUTS = *.o 之类交给 ar 时，CMD 不做展开，ar 收到字面量 "*.o"
        # 报 "Invalid argument"。改用 make 自己的 $(wildcard)，
        # 在 make 层面展开，与 shell 无关。
        #
        # ★ OUTS 不能写成 $(wildcard *.o) —— recipe 在执行前整体展开，
        #   那时 .o 还没编出来，会展开成空。必须从 *.c 推导。
        stripped = ln.strip()
        m = re.match(r"^(INCLUDEFILES|LIBSOURCES|OUTS)\s*=\s*\*\.(h|c|o)\s*$", stripped)
        if m:
            var, ext = m.group(1), m.group(2)
            if ext == "o":
                new = "%s = $(patsubst %%.c,%%.o,$(wildcard *.c))\n" % var
            else:
                new = "%s=$(wildcard *.%s)\n" % (var, ext)
            fixes.append("替换 -> %s   =>   %s" % (stripped, new.strip()))
            out.append(new)
            continue

        out.append(ln)

    if not fixes:
        return 0

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)

    print(f"  修复: {path}")
    for r in fixes:
        print(f"    {r}")
    return len(fixes)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    total_files, total_lines = 0, 0
    for root_dir in sys.argv[1:]:
        if not os.path.exists(root_dir):
            print(f"跳过（不存在）: {root_dir}")
            continue
        for dirpath, _, filenames in os.walk(root_dir):
            if "Makefile" not in filenames:
                continue
            # 只处理 HLS 驱动的 Makefile
            # HLS 驱动的 Makefile 出现在 ip_export/drivers/、平台 hw/drivers/ 和各 BSP 的 libsrc/<ip>_v1_0/ 三处
            dp = dirpath.replace("\\", "/")
            if "drivers" not in dp and "/libsrc/" not in dp:
                continue
            p = os.path.join(dirpath, "Makefile")
            n = fix_makefile(p)
            if n:
                total_files += 1
                total_lines += n

    print(f"\n共修复 {total_files} 个 Makefile，删除 {total_lines} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
