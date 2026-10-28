# -*- coding: utf-8 -*-
"""把正式系统（GCS r1）需要的 45 个数据/模型文件写到 SD 卡，并按清单校验 SHA256。

背景：正式系统固件启动时会从 SD 卡读 scenes/<景>/… 共 45 个文件（1,150,149,380 B），
还要读 boot/jrn0.bin、boot/jrn1.bin 两个 64 B 的启动身份记录（journal）。
没有这些文件，固件会停在 `S2C STOP identity` 或找不到模型。

用法：
    # 1) 先只检查本地源文件齐不齐（不碰卡）
    D:\\Anaconda\\python.exe tools\\prepare_sd_card.py --check-sources

    # 2) 真写卡（会先确认卷标/文件系统/空间，再逐个写并回读校验）
    D:\\Anaconda\\python.exe tools\\prepare_sd_card.py --drive F: --yes

    # 3) 新卡第一次安装：同时生成一对全新 journal 并写入卡（已有 journal 会拒绝）
    D:\\Anaconda\\python.exe tools\\prepare_sd_card.py --drive F: --new-installation --yes

    # 4) 只想先演练（写到本地目录，不动卡）
    D:\\Anaconda\\python.exe tools\\prepare_sd_card.py --staging build/host/sd_staging

安全规则：
- 目标里已经有 boot\\jrn0.bin 或 boot\\jrn1.bin -> 视为「已安装介质」，脚本拒绝覆盖。
- 只有 --new-installation 才会调用 tools/gcs_boot_provision.py 生成新 journal；
  生成的是全新安装身份，旧卡的 journal 不会被恢复或覆盖。
- 不改分区、不格式化；卡必须是 FAT32（exFAT 固件不支持）。
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "build" / "host" / "gcs_r1_abi4_user" / "sd_required_layout_v3.txt"
PROVISION = ROOT / "tools" / "gcs_boot_provision.py"
JOURNAL_NAMES = ("jrn0.bin", "jrn1.bin")


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_layout(path=LAYOUT):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        name, size, sha = line.split("\t")[:3]
        rows.append((name.strip(), int(size), sha.strip()))
    return rows


def check_sources(rows):
    problems = []
    for name, size, sha in rows:
        src = ROOT / "data" / name
        if not src.is_file():
            problems.append((name, "缺少源文件"))
            continue
        if src.stat().st_size != size:
            problems.append((name, "大小不符 %d != %d" % (src.stat().st_size, size)))
            continue
        if sha256_of(src) != sha:
            problems.append((name, "SHA256 不符"))
    return problems


def target_check(path):
    """返回 (volume, filesystem, free_bytes)；非 FAT32 直接报错。"""
    drive = str(path.drive) or "?"
    vol = fs = None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Volume -DriveLetter %s | Select-Object FileSystemLabel,FileSystem,SizeRemaining | ConvertTo-Json" % drive.rstrip(":")],
            capture_output=True, text=True, timeout=30)
        info = json.loads(out.stdout)
        vol = info.get("FileSystemLabel")
        fs = info.get("FileSystem")
        free = int(info.get("SizeRemaining") or 0)
    except Exception as exc:                                  # noqa: BLE001
        raise SystemExit("读不到 %s 的卷信息：%s" % (drive, exc))
    if fs != "FAT32":
        raise SystemExit("%s 的文件系统是 %s，固件只认 FAT32（exFAT 会报 FR_NO_FILESYSTEM）。"
                         "请先用 Windows 格式化工具把它格成 FAT32（单分区），再来跑本脚本。"
                         % (drive, fs))
    return vol, fs, free


def existing_journals(target):
    return [n for n in JOURNAL_NAMES if (target / "boot" / n).exists()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="准备正式系统的 SD 卡（写入 45 个数据文件 + 校验）")
    ap.add_argument("--layout", default=str(LAYOUT), help="SD 文件清单")
    ap.add_argument("--drive", help="目标盘符，例如 F:")
    ap.add_argument("--staging", help="写到本地目录（演练用，不碰真卡）")
    ap.add_argument("--check-sources", action="store_true", help="只检查本地源文件，不写任何东西")
    ap.add_argument("--new-installation", action="store_true",
                    help="新卡第一次安装：额外生成一对全新 journal")
    ap.add_argument("--no-readback", action="store_true", help="写完后不回读校验（默认回读）")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = ap.parse_args(argv)

    rows = read_layout(Path(args.layout))
    total = sum(r[1] for r in rows)
    print("清单：%d 个文件，共 %s B（%.2f GB）" % (len(rows), format(total, ","), total / 1e9))

    print("\n[1/4] 检查本地源文件 ...")
    problems = check_sources(rows)
    if problems:
        for name, why in problems[:20]:
            print("  [问题] %s：%s" % (name, why))
        print("源文件有问题，先解决再写卡。")
        return 1
    print("  全部 %d 个源文件大小与 SHA256 校验通过。" % len(rows))

    if args.check_sources:
        print("\n只做检查，没写任何东西。")
        return 0

    if not args.drive and not args.staging:
        print("\n没给 --drive / --staging，只做了检查。写卡请加 --drive F: --yes")
        return 0

    if args.drive:
        drive = args.drive.rstrip("\\/")
        if not drive.endswith(":"):
            drive += ":"
        target = Path(drive + "\\")
        vol, fs, free = target_check(target)
        print("\n[2/4] 目标卡：%s  卷标=%s  文件系统=%s  剩余=%.2f GB"
              % (drive, vol, fs, free / 1e9))
        if free < total + (10 << 20):
            print("  空间不够：需要至少 %.2f GB" % (total / 1e9))
            return 1
        bad = existing_journals(target)
        if bad:
            print("  卡上已经有 boot/%s —— 这是已安装介质，脚本不会覆盖。"
                  % "、".join(bad))
            print("  换一张新卡，或确认后自己处理（不要回滚已用 journal）。")
            return 1
        if not args.yes:
            print("  即将写入 %d 个文件到 %s。确认请输入 yes：" % (len(rows), drive), end=" ")
            if input().strip().lower() != "yes":
                print("已取消。")
                return 1
    else:
        target = Path(args.staging)
        print("\n[2/4] 演练目录：%s（不动真卡）" % target)

    target.mkdir(parents=True, exist_ok=True)

    print("\n[3/4] 写入文件 ...")
    written = 0
    for i, (name, size, _sha) in enumerate(rows, 1):
        src = ROOT / "data" / name
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written += size
        if i % 10 == 0 or i == len(rows):
            print("  %d/%d  %.2f/%.2f GB" % (i, len(rows), written / 1e9, total / 1e9))

    if not args.no_readback:
        print("\n[3/4] 回读校验 ...")
        bad = []
        for i, (name, _size, sha) in enumerate(rows, 1):
            if sha256_of(target / name) != sha:
                bad.append(name)
            if i % 10 == 0 or i == len(rows):
                print("  已校验 %d/%d" % (i, len(rows)))
        if bad:
            print("  回读不一致：%s" % "、".join(bad[:10]))
            return 1
        print("  回读全部一致。")

    print("\n[4/4] 启动身份记录（journal）")
    if args.new_installation:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = ROOT / "build" / "host" / ("sd_provision_" + stamp)
        print("  生成全新安装身份 -> %s" % out)
        subprocess.run([sys.executable, "-X", "utf8", "-B", str(PROVISION),
                        "--new-installation", "--out", str(out)], check=True)
        (target / "boot").mkdir(parents=True, exist_ok=True)
        for n in JOURNAL_NAMES:
            shutil.copy2(out / "boot" / n, target / "boot" / n)
        print("  已写入 boot/jrn0.bin、boot/jrn1.bin")
        prov = json.loads((out / "provision.json").read_text(encoding="utf-8"))
        print("  安装身份：base=%s nonce=%s（记下来，后面最小客户端要用 boot-id）"
              % (prov.get("base"), prov.get("nonce")))
    else:
        have = existing_journals(target)
        if have:
            print("  沿用卡上已有的 boot/%s（没有覆盖）" % "、".join(have))
        else:
            print("  ⚠ 卡上没有 journal。全新卡请加 --new-installation 重新跑一次；")
            print("    已安装过的卡请把原来那对 journal 放回 boot/（不要回滚/克隆）。")

    print("\n完成。目标：%s" % target)
    print("下一步：断电插卡 -> 上电 -> 跑 build/host/dl_gcs.tcl -> 看 DP 画面。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
