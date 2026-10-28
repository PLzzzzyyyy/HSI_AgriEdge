#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把平台里【新 XSA 解出来的驱动】同步进各个 BSP 的 libsrc/，并做符号级验证。

为什么需要这个脚本（PITFALLS 2026-08-27）：
  换 XSA 后 Vitis **不会覆盖 BSP libsrc/ 里已存在的驱动**。
  平台 Build 只是把旧 libsrc 又复制了一遍到 include/ ——
  **头文件时间戳会变新，内容还是旧的**，最有迷惑性的一种假象。
  于是 app 会一直报 `'XConv_Set_in1' was not declared; did you mean 'XConv_Set_in1_V'?`
  之类的错，Build 几次都一样。

  本项目在 2019.2 IP（XConv_Set_in1_V / XConv_Set_w1_V）和
  2020.2 IP（XConv_Set_in1 / XConv_Set_w1_r）之间来回切，两个方向都会踩。

⚠ `xconv_g.c` 必须保留不动 —— 它是 BSP 自己按 xparameters 生成的配置表
  （XConv_ConfigTable），不在 IP 自带文件里，删了就编不过。

⚠ 只改头文件不够：libxil.a 里编进去的还是旧 xconv.c，
  光换头文件会从【编译错误】变成【链接错误】。**改完必须 Build 平台。**

用法：
  python tools/sync_bsp_driver.py vitis/yolo
  python tools/sync_bsp_driver.py vitis/yolo --dry-run     # 只看要做什么
  python tools/sync_bsp_driver.py vitis/yolo --force       # 版本已相同也强制重刷

⚠⚠ 复制时**绝对不能用 shutil.copy2**（2026-08-29 踩过一次）：
  copy2 会把源文件的 mtime 一起复制过来。而源在 <platform>/hw/drivers/ 下，
  它的时间戳是「换 XSA 那一刻」，往往比 BSP 上次编出来的
  <bsp>/ps7_cortexa9_0/lib/xconv.o **还要旧**。
  于是 make 认为 .o 是最新的、跳过重编，libxil.a 里仍然是旧符号 ——
  Build 平台看着成功、libxil.a 时间戳也刷新了（那只是重新打包），
  链接照样报一片 `undefined reference to XConv_Set_in1_V`。
  所以这里用 shutil.copy（不带 2）+ 显式把 mtime 设成当前时间，
  再顺手删掉过期的 xconv*.o，双保险。

旧的 src/ 会备份成 src.bak_<api>，<api> 由实际检测到的函数名决定
（bak_2019api / bak_2020api），不会互相覆盖。
"""
import os
import re
import shutil
import sys

KEEP = {"xconv_g.c"}          # BSP 生成的配置表，不能被 IP 自带文件覆盖

API_MARKS = [
    ("2019api", re.compile(r"XConv_Set_in1_V\s*\(")),
    ("2020api", re.compile(r"XConv_Set_in1\s*\(")),
]


def detect_api(srcdir):
    """从 xconv.h 判断这份驱动是哪个版本的 API。"""
    h = os.path.join(srcdir, "xconv.h")
    if not os.path.exists(h):
        return "unknown"
    text = open(h, "rb").read().decode("utf-8", errors="replace")
    for name, pat in API_MARKS:          # 2019 的先匹配，因为 _V 是 in1 的超集
        if pat.search(text):
            return name
    return "unknown"


def find_libsrc_dirs(platform, drv):
    """平台下所有 BSP 的 libsrc/<drv>/src —— standalone_domain 和 zynq_fsbl_bsp 都要。"""
    hits = []
    for root, dirs, _ in os.walk(platform):
        if os.path.basename(root) == "libsrc":
            d = os.path.join(root, drv, "src")
            if os.path.isdir(d):
                hits.append(d)
        # 别往备份目录里钻
        dirs[:] = [x for x in dirs if not x.startswith("src.bak_")]
    return sorted(hits)


def stale_objects(dst):
    """dst = <bsp_root>/libsrc/<drv>/src  ->  <bsp_root>/lib/ 下对应的 .o

    BSP 的 makefile 把 libsrc/*/src/*.c 编到 <bsp_root>/lib/*.o，再打包进 libxil.a。
    .c 换了但 .o 时间更新的话 make 会跳过重编（就是文件开头那个 copy2 的坑），
    所以把过期的 .o 直接删掉，逼它重编。
    """
    bsp_root = os.path.dirname(os.path.dirname(os.path.dirname(dst)))
    libdir = os.path.join(bsp_root, "lib")
    if not os.path.isdir(libdir):
        return []
    stems = sorted({os.path.splitext(f)[0]
                    for f in os.listdir(dst) if f.endswith(".c")})
    return [os.path.join(libdir, s + ".o") for s in stems
            if os.path.exists(os.path.join(libdir, s + ".o"))]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    if len(args) != 1:
        print(__doc__)
        return 1
    platform = args[0]

    hwdrv = os.path.join(platform, "hw", "drivers")
    if not os.path.isdir(hwdrv):
        print("✗ 找不到 %s —— 这个路径是平台工程目录吗（形如 vitis/yolo）？" % hwdrv)
        return 1

    drivers = sorted(d for d in os.listdir(hwdrv)
                     if os.path.isdir(os.path.join(hwdrv, d, "src")))
    if not drivers:
        print("✗ %s 下没有带 src/ 的驱动" % hwdrv)
        return 1

    rc = 0
    for drv in drivers:
        srcdir = os.path.join(hwdrv, drv, "src")
        new_api = detect_api(srcdir)
        print("=" * 70)
        print("驱动 %s   新版本（来自 XSA）: %s" % (drv, new_api))
        print("  源: %s" % srcdir)

        targets = find_libsrc_dirs(platform, drv)
        if not targets:
            print("  ⚠ 没找到任何 BSP 的 libsrc/%s/src，跳过" % drv)
            continue

        for dst in targets:
            old_api = detect_api(dst)
            print("  -> %s" % dst)
            print("     现有: %s" % old_api)
            if old_api == new_api and not force:
                print("     已经是同一版本，跳过（要连时间戳一起重刷加 --force）")
                continue

            bak = dst + ".bak_" + old_api
            objs = stale_objects(dst)
            if dry:
                print("     [dry-run] 备份到 %s，复制新驱动（保留 %s），"
                      "mtime 设为当前时间"
                      % (os.path.basename(bak), "/".join(sorted(KEEP))))
                for o in objs:
                    print("     [dry-run] 删除过期目标文件 %s" % os.path.basename(o))
                continue

            if os.path.exists(bak):
                shutil.rmtree(bak)
            shutil.copytree(dst, bak)

            n = 0
            for fn in os.listdir(srcdir):
                if fn in KEEP:
                    continue
                s = os.path.join(srcdir, fn)
                if os.path.isfile(s):
                    d = os.path.join(dst, fn)
                    # ⚠ 必须是 copy（不是 copy2）：copy2 会把源的旧 mtime 一起带过来，
                    #   make 就会认为 .o 还是最新的而跳过重编。见文件头的说明。
                    shutil.copy(s, d)
                    os.utime(d, None)          # 显式盖成"现在"
                    n += 1

            for o in objs:
                os.remove(o)

            got = detect_api(dst)
            ok = (got == new_api)
            print("     备份 -> %s" % os.path.basename(bak))
            print("     复制 %d 个文件（保留 %s），mtime 已设为当前时间"
                  % (n, "/".join(sorted(KEEP))))
            if objs:
                print("     删除过期目标文件 %d 个：%s"
                      % (len(objs), ", ".join(os.path.basename(o) for o in objs)))
            print("     复制后检测: %s  %s" % (got, "✅" if ok else "❌ 不符预期"))
            if not ok:
                rc = 1

    print("=" * 70)
    if dry:
        print("dry-run，什么都没改。")
    else:
        print("完成。⚠ 接下来必须在 Vitis 里 Build 平台工程 ——")
        print("   libxil.a 里编进去的还是旧 xconv.c，不重编只是把编译错误换成链接错误。")
        print("   验证（应当只剩新 API 的符号）：")
        print("   arm-none-eabi-nm <...>/libxil.a | grep -oE \"XConv_Set_in1[a-zA-Z_]*\"")
    return rc


if __name__ == "__main__":
    sys.exit(main())
