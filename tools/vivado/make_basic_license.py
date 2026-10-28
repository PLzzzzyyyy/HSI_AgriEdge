# -*- coding: utf-8 -*-
"""从本机 Xilinx 许可证里挑出 BASIC（Vivado ML Standard）那一层，写一份只读副本。

背景：AMD 生成的 license 文件里同时含 `License_Tier:ALVEO` 和 `License_Tier:BASIC`
两类条目。Vivado 2026.1 默认会选中 ALVEO 那一层，于是只认 Alveo 板卡、其它器件
（含本项目的 XCZU5EV）一律报 "Specified part could not be found"。把 BASIC 层单独
放一个文件、用 XILINXD_LICENSE_FILE 指过去，器件就能正常选到。

本脚本**不修改原许可证文件**，只读它、另写一份副本（默认写到
`build/host/lic/vivado_basic.lic`），供 `launch_vivado.bat` 使用。

用法：
    D:\\Anaconda\\python.exe tools\\vivado\\make_basic_license.py
    D:\\Anaconda\\python.exe tools\\vivado\\make_basic_license.py --license <原 lic> --out <副本>
"""

import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "build" / "host" / "lic" / "vivado_basic.lic"


def find_license() -> Path:
    """按 Vivado 的常见位置找一个 Xilinx license 文件。"""
    cands = []
    env = __import__("os").environ.get("XILINXD_LICENSE_FILE", "")
    for part in re.split(r"[;]", env):
        part = part.strip()
        if part and Path(part).is_file():
            cands.append(Path(part))
    home = Path.home()
    cands += [
        home / "Downloads" / "Xilinx.lic",
        home / ".Xilinx" / "Xilinx.lic",
        Path("C:/Xilinx/Xilinx.lic"),
    ]
    for d in (home / "Downloads", home / ".Xilinx", Path("C:/Xilinx")):
        if d.is_dir():
            cands += sorted(d.glob("*.lic"))
    for c in cands:
        if c.is_file():
            return c
    raise SystemExit("没找到 Xilinx license 文件，请用 --license 指定")


def split_entries(text: str):
    """把 license 按逻辑条目切开（行尾反斜杠表示续行）。"""
    entries, cur = [], []
    for line in text.splitlines():
        cur.append(line)
        if not line.rstrip().endswith("\\"):
            entries.append(cur)
            cur = []
    if cur:
        entries.append(cur)
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 BASIC 层的 Xilinx license 副本")
    ap.add_argument("--license", help="原始 license 文件（默认自动查找）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出的副本路径")
    args = ap.parse_args(argv)

    src = Path(args.license) if args.license else find_license()
    if not src.is_file():
        raise SystemExit("license 不存在: %s" % src)

    text = io.open(src, encoding="utf-8", errors="replace").read()
    entries = split_entries(text)

    header, basic, other = [], [], []
    for e in entries:
        blob = "\n".join(e)
        if all((not ln.strip()) or ln.strip().startswith("#") for ln in e):
            header.append(e)
        elif re.search(r"License_Tier:\s*BASIC", blob):
            basic.append(e)
        else:
            other.append(e)

    if not basic:
        raise SystemExit("这份 license 里没有 BASIC 层，无法生成副本（原文件：%s）" % src)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        for e in header + basic:
            fh.write("\n".join(e) + "\n")

    print("源 license : %s" % src)
    print("输出副本   : %s" % out)
    print("条目统计   : 共 %d 条，BASIC %d 条（其余 %d 条属于 ALVEO / IP 评估，未写入副本）"
          % (len(entries), len(basic), len(other)))
    print("用法       : set XILINXD_LICENSE_FILE=%s" % out)
    print("（原文件没有被修改；要看 Alveo 器件时不设这个变量即可）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
