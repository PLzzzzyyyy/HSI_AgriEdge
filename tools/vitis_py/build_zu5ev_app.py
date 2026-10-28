#!/usr/bin/env python3
r"""M1/M2 A53 benchmark app on Vitis 2026.1, mirrors tools/build_zu5ev_app.tcl.
Builds src/ps sources (variant m1 uses tt_hw_xil.cpp; m2/m2chk use
tt_hw_engine.cpp + src/hls/tt_engine_regs.h) on the chk_plat platform created
by check_xsa_platform.py, Release, verifies the critical compiler flags appear
in the build log, 0 application-source warnings, exactly 1 ELF.

Usage (from an ASCII path):
  vitis -s tools/vitis_py/build_zu5ev_app.py <ws> [app] [variant]
  variant: m1 (default) | m2 | m2chk
The ELF stays in the workspace; board/m1|m2/ is not overwritten.
"""
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

COMMON = ("main_benchmark.cpp tt_net.cpp tt_net.h tt_hw.h tt_hw_sim.cpp "
          "tt_hw_switch.cpp tt_hw_switch.h tt_ref_int.h tt_data.c tt_data.h "
          "tt_block_app.cpp tt_block_app.h tt_block_data.c tt_block_data.h "
          "tt_block_render.cpp tt_block_render.h tt_measure.h").split()
REQUIRED_FLAGS = ("-O2", "-mcpu=cortex-a53", "-ffp-contract=off")


def stage_hls_driver(ws, marker):
    """2026.1 BSP 不再编译 HLS 自定义驱动：把 hw_artifacts 里的驱动源码暂存到
    <ws>/_drvgen（跳过 *_linux.c）并补生成 <stem>_g.c 配置表，返回 (目录, 文件名列表)。"""
    base = ws / "chk_plat/psu_cortexa53_0/standalone_domain/bsp/hw_artifacts/drivers"
    cands = sorted(d for d in base.glob("*") if marker in d.name.lower() and (d / "src").is_dir())
    if not cands:
        raise SystemExit(f"REFUSE: no HLS driver matching '{marker}' under {base}")
    drv_src = cands[-1] / "src"
    print(f"BUILD: HLS driver sources from {drv_src}")
    gen_dir = ws / "_drvgen"
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
    m = re.search(r"extern\s+(\w+)\s+(\w+)\s*\[\s*\]", sinit_text)
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


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ws = Path(sys.argv[1]).resolve()
    app = sys.argv[2] if len(sys.argv) > 2 else "tt_bench_zu5ev"
    variant = sys.argv[3] if len(sys.argv) > 3 else "m1"
    if variant not in ("m1", "m2", "m2chk"):
        raise SystemExit("variant must be m1, m2 or m2chk")
    if not (ws / "chk_plat").is_dir():
        raise SystemExit(f"REFUSE: platform chk_plat not found in {ws}; run check_xsa_platform.py first")

    # 2026.1：SDT BSP 不再编译/导出 HLS 自定义驱动（bsp.yaml 中为 None），
    # 改为把驱动源码导入应用并补生成 _g.c；宏值与原 2020.2 BSP 一致。见 docs/vitis2026_migration.md §4.6。
    srcs = list(COMMON)
    extra_import = [(ROOT / "src/hls", ["tt_engine_regs.h"])]   # tt_measure.h 包含它，各变体都要
    defines = ["TT_HW_RUNTIME_SWITCH"]
    if variant == "m1":
        srcs.append("tt_hw_xil.cpp")
        drv_marker = "tucker"
        driver_defines = [
            "-DXPAR_XTUCKER_PROJ_NUM_INSTANCES=1",
            "-DXPAR_XTUCKER_PROJ_0_DEVICE_ID=0",
            "-DXPAR_XTUCKER_PROJ_0_S_AXI_CTRL_BASEADDR=XPAR_TUCKER_PROJ_0_BASEADDR",
        ]
    else:
        srcs += ["tt_hw_engine.cpp", "tt_hw_engine.h"]
        drv_marker = "tt_engine"
        driver_defines = [
            "-DXPAR_XTT_ENGINE_NUM_INSTANCES=1",
            "-DXPAR_XTT_ENGINE_0_DEVICE_ID=0",
            "-DXPAR_XTT_ENGINE_0_S_AXI_CTRL_BASEADDR=XPAR_TT_ENGINE_0_BASEADDR",
        ]
    if variant == "m2chk":
        defines.append("TT_ENG_SELFCHECK")
    drv_gen_dir, drv_files = stage_hls_driver(ws, drv_marker)

    client = tt_vitis_client.create_client()
    tt_vitis_client.set_workspace_retry(client, ws)
    try:
        client.delete_component(app)
        print(f"BUILD: removed existing component {app} (if any)")
    except Exception as e:
        print(f"BUILD: no existing component to remove: {e}")
    app_dir = ws / app
    if app_dir.exists():
        shutil.rmtree(app_dir, ignore_errors=True)
        print(f"BUILD: removed stale app dir {app_dir}")

    platform_xpfm = client.find_platform_in_repos("chk_plat")
    print(f"BUILD: creating app {app} ({variant}) on chk_plat")
    app_obj = client.create_app_component(name=app, platform=platform_xpfm,
                                          domain="standalone_domain", template="empty_application")

    def try_cfg(key, value):
        try:
            print(f"  set {key} = {value} ->", app_obj.set_app_config(key=key, values=value))
            return True
        except Exception as e:
            print(f"  set {key} ERR: {e}")
            return False

    try_cfg("USER_COMPILE_OPTIMIZATION_LEVEL", "-O2")
    flags = " ".join(tt_vitis_client.bsp2026_compat_defines() + driver_defines
                     + ["-mcpu=cortex-a53", "-ffp-contract=off"])
    for key in ("USER_COMPILE_OTHER_FLAGS", "USER_COMPILE_FLAGS", "USER_COMPILE_MISC", "USER_MISC_FLAGS"):
        if try_cfg(key, flags):
            break
    for key in ("USER_COMPILE_DEFINITIONS", "USER_DEFINE_SYMBOLS", "USER_COMPILE_SYMBOLS"):
        if try_cfg(key, ";".join(defines)):
            break
    for key in ("USER_LINK_LIBRARIES", "USER_LINKER_LIBRARIES"):
        if try_cfg(key, "m"):
            break

    comp = client.get_component(name=app)
    ps_dir = ROOT / "src/ps"
    status = comp.import_files(from_loc=str(ps_dir), files=srcs, dest_dir_in_cmp="src")
    print("BUILD: import_files (ps) ->", status)
    for loc, files in extra_import:
        print("BUILD: import_files", files, "from", loc, "->",
              comp.import_files(from_loc=str(loc), files=files, dest_dir_in_cmp="src"))
    print("BUILD: import_files (driver) ->",
          comp.import_files(from_loc=str(drv_gen_dir), files=drv_files, dest_dir_in_cmp="src"))

    print("BUILD: compiling")
    build = getattr(app_obj, "build", None) or getattr(comp, "build", None)
    try:
        print("BUILD: build() ->", build())
    except Exception as e:
        print("BUILD: build() ERR:", e)

    app_dir = ws / app / "build"
    elfs = sorted(ws.joinpath(app).rglob("*.elf"))
    print("ELF candidates:", [str(p.relative_to(ws)) for p in elfs])
    logs = sorted(ws.joinpath(app).rglob("*.log"))
    text = ""
    for log in logs:
        try:
            text += log.read_text(encoding="utf-8", errors="replace") + "\n"
        except Exception:
            pass
    app_warn = [ln for ln in text.splitlines()
                if "warning:" in ln.lower() and ("src" in ln.lower() or "tt_" in ln.lower())]
    print(f"warning lines: app-source={len(app_warn)}")
    for w in app_warn[:10]:
        print("  W:", w.strip()[:160])
    flat = "".join(text.split())   # 构建日志按终端宽度折行，flag 可能断在词中间，去空白再匹配
    missing_flags = [f for f in REQUIRED_FLAGS if f not in flat]
    if missing_flags:
        print("BUILD FAIL: required flags not seen in build log:", missing_flags)
    if len(elfs) != 1:
        print(f"BUILD FAIL: expected exactly 1 ELF, found {len(elfs)}")
        return 1
    if app_warn:
        print(f"BUILD FAIL: {len(app_warn)} warning(s) in application sources")
        return 1
    if missing_flags:
        return 1
    print(f"BUILD PASS: 0 application warnings, {elfs[0]}")
    print(f"  (variant {variant}; board/ is not overwritten)")
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
