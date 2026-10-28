#!/usr/bin/env python3
"""Shared Vitis 2026.1 client helpers for HSI_AgriEdge build scripts.

Client bug workaround (Chinese Windows): vitis/_server.py startServer() reads
the vitis-server stdout looking for the '{serverPort: N}' line and decodes each
line as strict UTF-8; the server output contains GBK bytes (the Chinese
user/computer name appears in temp paths), raising UnicodeDecodeError
("'utf-8' codec can't decode byte 0xd5 ..."). Passing an explicit free port
makes the client skip that read loop entirely; a longer start timeout keeps the
channel-ready wait away from the same decode bug in its timeout handler.

lwip220 workaround: the 2026.1 installer ships
ThirdParty/sw_services/lwip220_v1_4/data/lwip220.yaml with a UTF-8 BOM (the
only BOM under embeddedsw); the Vitis repo loader rejects it at server start
("Failed to read ... lwip220.yaml, lwip220 ... will not be available"), so no
lwip library is applicable to any domain. The AMD installation is never
modified; a fixed copy is registered as a project-local repo instead.
"""
import os
import shutil
import socket
import stat
from pathlib import Path

# Read by vitis/_server.py createChannel(); set before create_client().
os.environ.setdefault("VITIS_SERVER_START_TIMEOUT", "300")

LWIP_INSTALL_REL = "data/embeddedsw/ThirdParty/sw_services/lwip220_v1_4"
LWIP_OVERLAY_REL = "ThirdParty/sw_services/lwip220_v1_4"
LWIP_YAML_REL = "data/lwip220.yaml"


def pick_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def create_client():
    import vitis

    return vitis.create_client(port=pick_free_port())


def prepare_lwip220_overlay(vendor_root):
    """Prepare a project-local embeddedsw overlay that makes lwip220 usable.

    Works around two installer issues in the copy only:
      - strip the UTF-8 BOM from data/lwip220.yaml;
      - add psu_cortexa53_0 / psu_cortexa53_1 to supported_processors.

    Registration order matters (verified 2026-10-16): call
    client.add_embedded_sw_repo(path=<overlay>) BEFORE creating the platform,
    then plain domain.set_lib('lwip220') succeeds. Adding the repo after the
    platform exists does NOT fix that platform's domain, and passing the
    library path to set_lib also fails.

    Returns the overlay root path to pass to add_embedded_sw_repo.
    """
    vitis_root = Path(os.environ.get("XILINX_VITIS", r"D:/AMD/2026.1/Vitis"))
    src = vitis_root / LWIP_INSTALL_REL
    if not src.is_dir():
        raise SystemExit(f"PLAT FAIL: installed lwip220 lib not found: {src}")
    overlay = Path(vendor_root) / "embeddedsw_overlay"
    lib_dst = overlay / LWIP_OVERLAY_REL
    yaml_dst = lib_dst / LWIP_YAML_REL

    need_copy = not yaml_dst.is_file()
    if not need_copy:
        blob = yaml_dst.read_bytes()
        if blob[:3] == b"\xef\xbb\xbf" or b"psu_cortexa53_0" not in blob:
            need_copy = True
    if need_copy:
        print("lwip220: preparing project-local overlay copy")
        print(f"  from {src}")
        print(f"  to   {overlay}")
        shutil.copytree(src, lib_dst, dirs_exist_ok=True)

    blob = yaml_dst.read_bytes()
    if blob[:3] == b"\xef\xbb\xbf":
        os.chmod(yaml_dst, stat.S_IWRITE | stat.S_IREAD)
        yaml_dst.write_bytes(blob[3:])
        print("  stripped UTF-8 BOM from copied lwip220.yaml")
        blob = yaml_dst.read_bytes()
    if b"psu_cortexa53_0" not in blob:
        text = blob.decode("utf-8")
        text = text.replace("  - psu_cortexa53\n",
                            "  - psu_cortexa53\n  - psu_cortexa53_0\n  - psu_cortexa53_1\n", 1)
        os.chmod(yaml_dst, stat.S_IWRITE | stat.S_IREAD)
        yaml_dst.write_text(text, encoding="utf-8")
        print("  tagged psu_cortexa53_0/_1 in copied lwip220.yaml")
    print(f"lwip220 overlay ready: {overlay}")
    return overlay


def bsp2026_compat_defines():
    """2026.1 SDT BSP 不再导出的经典 XPAR 宏，编译期 -D 补回。

    每个值都与 2020.2 BSP 逐一核对过（旧构建 build/board/periph_formal_20260928）：
      - CPU 频率：旧 XPAR_CPU_CORTEXA53_0_CPU_CLK_FREQ_HZ = 1066656005，
        与新 XPAR_CPU_CORE_CLOCK_FREQ_HZ 完全相同。
      - 下面的 0 宏保留经典源码兼容值，不表示所有 SDT 驱动都按索引查表。
        DP/DPDMA 的 SDT LookupConfig 按物理基址查表，调用点必须使用
        XPAR_XDPPSU_0_BASEADDR / XPAR_XDPDMA_0_BASEADDR；不可传旧 DeviceId 0。
    详见 docs/vitis2026_migration.md §4.5。
    """
    return [
        "-DXPAR_CPU_CORTEXA53_0_CPU_CLK_FREQ_HZ=XPAR_CPU_CORE_CLOCK_FREQ_HZ",
        "-DXPAR_SCUGIC_0_DEVICE_ID=0U",
        "-DXPAR_PSU_DP_DEVICE_ID=0",
        "-DXPAR_XDPDMA_0_DEVICE_ID=0",
        "-DXPAR_XGPIOPS_0_DEVICE_ID=0",
        "-DXPAR_XSYSMONPSU_0_DEVICE_ID=0",
    ]



def stage_hls_driver(ws, marker, plat=None):
    """2026.1 BSP 不再编译 HLS 自定义驱动：把 hw_artifacts 里的驱动源码暂存到
    <ws>/_drvgen（跳过 *_linux.c）并补生成 <stem>_g.c 配置表，返回 (目录, 文件名列表)。
    plat 省略时在工作区里自动找平台目录（chk_plat / gcs_r1_abi4_plat 等均可）。"""
    import re as _re
    if plat:
        bases = [Path(ws) / plat]
    else:
        bases = [d for d in Path(ws).glob("*") if (d / "psu_cortexa53_0").is_dir()]
    drv_cands = []
    searched = []
    for b in bases:
        for hw in b.glob("psu_cortexa53_0/*/bsp/hw_artifacts/drivers"):
            searched.append(hw)
            drv_cands += [d for d in hw.glob("*") if marker in d.name.lower() and (d / "src").is_dir()]
    if not drv_cands:
        raise SystemExit(f"REFUSE: no HLS driver matching '{marker}' under {searched or bases}")
    drv_src = sorted(drv_cands)[-1] / "src"
    print(f"BUILD: HLS driver sources from {drv_src}")
    gen_dir = Path(ws) / "_drvgen"
    if gen_dir.exists():
        shutil.rmtree(gen_dir)
    gen_dir.mkdir(parents=True)
    files = []
    for f in sorted(drv_src.iterdir()):
        if f.suffix in (".c", ".h") and not f.name.endswith("_linux.c"):
            shutil.copy2(f, gen_dir / f.name)
            files.append(f.name)
    mains = [n for n in files if n.endswith(".c") and not n.endswith("_sinit.c")]
    sinits = [n for n in files if n.endswith("_sinit.c")]
    if len(mains) != 1 or len(sinits) != 1:
        raise SystemExit(f"REFUSE: expected 1 driver .c + 1 _sinit.c, got {mains} {sinits}")
    stem = mains[0][:-2]
    sinit_text = (gen_dir / sinits[0]).read_text(encoding="utf-8", errors="replace")
    m = _re.search(r"extern\s+(\w+)\s+(\w+)\s*\[\s*\]", sinit_text)
    if not m:
        raise SystemExit(f"REFUSE: cannot parse config table extern in {sinits[0]}")
    cfg_type, table = m.group(1), m.group(2)
    macro = "XPAR_" + stem.upper()
    g_name = stem + "_g.c"
    (gen_dir / g_name).write_text(
        "/* 2026.1 migration: SDT BSP no longer generates HLS driver _g.c; rebuilt from 2020.2 format. */\n"
        f'#include "{stem}.h"\n\n'
        f"{cfg_type} {table}[] = {{\n"
        f"    {{ {macro}_0_DEVICE_ID, {macro}_0_S_AXI_CTRL_BASEADDR }}\n"
        "};\n",
        encoding="utf-8")
    files.append(g_name)
    print(f"BUILD: generated {g_name} ({cfg_type} {table}), {len(files)} files staged")
    return gen_dir, files


def stage_xtime_shim(gen_dir):
    """冻结包源码按 2020.2 写 #include "xtime_l.h"；2026.1 BSP 不再导出该头，
    在暂存目录写一个转发垫片（XTime_GetTime / COUNTS_PER_SECOND 与 xiltimer.h 同义，
    频率 33333000 一致）。返回垫片文件名；已存在则返回 None。"""
    p = Path(gen_dir) / "xtime_l.h"
    if p.exists():
        return None
    p.write_text(
        "/* 2026.1 migration shim: xtime_l.h -> xiltimer.h (same XTime_GetTime/COUNTS_PER_SECOND,\n"
        "   33333000 Hz; see docs/vitis2026_migration.md). */\n"
        "#ifndef TT_XTIME_L_SHIM_H\n#define TT_XTIME_L_SHIM_H\n"
        '#include "xiltimer.h"\n'
        "#endif\n",
        encoding="utf-8")
    return p.name



def set_workspace_retry(client, ws, tries=6, delay=15):
    """set_workspace 偶发 FAILED_PRECONDITION：上一个 vitis 会话退出后工作区锁未及时释放，
    平台刚建完紧接着开下一个会话时最容易出现。退避重试几轮再放弃。"""
    import time as _time
    last = None
    for i in range(tries):
        try:
            r = client.set_workspace(path=str(ws))
            print(f"WORKSPACE OK: {ws} (attempt {i + 1})")
            return r
        except Exception as e:
            last = e
            print(f"WORKSPACE retry {i + 1}/{tries}: {e}")
            _time.sleep(delay)
    raise SystemExit(f"REFUSE: cannot set workspace {ws}: {last}")
