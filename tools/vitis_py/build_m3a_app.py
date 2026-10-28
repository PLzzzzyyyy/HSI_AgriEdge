#!/usr/bin/env python3
r"""M3a test app on Vitis 2026.1: builds the validated sources from a
prepare_m3a_sources.py package (.../tt_m3a_zu5ev/test_m3a/src) on chk_plat,
using the package's settings.json flags (-O2 -mcpu=cortex-a53 -ffp-contract=off
-ffunction-sections -fdata-sections -Wall -Wextra -Werror; libs: m;
linker: -Wl,--gc-sections). Prints BUILD PASS on success; the ELF stays in the
workspace (board/ is not overwritten).

Usage (from an ASCII path):
  vitis -s tools/vitis_py/build_m3a_app.py <ws> <package_dir> [app]
  <ws> must contain chk_plat (check_xsa_platform.py on the package XSA).
  <package_dir> = .../m3a_sources_*/tt_m3a_zu5ev (has test_m3a/src + settings.json).
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402

FLAG_KEYS = ("USER_COMPILE_OTHER_FLAGS", "USER_COMPILE_MISC", "USER_MISC_FLAGS", "USER_COMPILE_FLAGS")
LIB_KEYS = ("USER_LINK_LIBRARIES", "USER_LINKER_LIBRARIES")
LINKER_KEYS = ("USER_LINKER_OTHER_FLAGS", "USER_LINKER_MISC", "USER_LINKER_FLAGS")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    ws = Path(sys.argv[1]).resolve()
    pkg = Path(sys.argv[2]).resolve()
    app = sys.argv[3] if len(sys.argv) > 3 else "test_m3a"
    src_dir = pkg / "test_m3a/src"
    cfg = json.loads((pkg / "test_m3a/settings.json").read_text(encoding="utf-8"))
    if not src_dir.is_dir():
        raise SystemExit(f"REFUSE: package src missing: {src_dir}")
    if not (ws / "chk_plat").is_dir():
        raise SystemExit(f"REFUSE: chk_plat not found in {ws}; run check_xsa_platform.py first")
    files = sorted(p.name for p in src_dir.iterdir() if p.is_file())
    print("BUILD: sources:", ", ".join(files))
    # 2026.1：HLS 驱动不在 BSP 里（docs §4.6）：从平台 hw_artifacts 暂存导入 + 补生成 _g.c；
    # 冻结包源码按 2020.2 写 #include "xtime_l.h"，用垫片转发到 xiltimer.h。
    drv_gen_dir, drv_files = tt_vitis_client.stage_hls_driver(ws, "tt_engine")
    shim = tt_vitis_client.stage_xtime_shim(drv_gen_dir)
    if shim:
        drv_files.append(shim)
        print(f"BUILD: staged xtime_l.h shim -> xiltimer.h ({shim})")

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
    xpfm = client.find_platform_in_repos("chk_plat")
    app_obj = client.create_app_component(name=app, platform=xpfm,
                                          domain="standalone_domain", template="empty_application")

    print("== app config dump ==")
    dump = ""
    try:
        dump = str(app_obj.get_app_config())
        print(dump)
    except Exception as e:
        print("cfg dump err:", e)

    def try_cfg(key, value):
        try:
            print(f"  set {key} = {value} ->", app_obj.set_app_config(key=key, values=value))
            return True
        except Exception as e:
            print(f"  set {key} ERR: {e}")
            return False

    # 2026.1：驱动源码引用的经典宏（值与原 2020.2 BSP 一致，见 docs §4.6）
    driver_defines = [
        "-DXPAR_XTT_ENGINE_NUM_INSTANCES=1",
        "-DXPAR_XTT_ENGINE_0_DEVICE_ID=0",
        "-DXPAR_XTT_ENGINE_0_S_AXI_CTRL_BASEADDR=XPAR_TT_ENGINE_0_BASEADDR",
    ]
    all_flags = " ".join(cfg.get("compiler_flags", []) + driver_defines)
    stds = cfg.get("c_flags", []) + cfg.get("cxx_flags", [])
    linker = " ".join(cfg.get("linker_flags", []))

    # optimization via the dedicated key, plus the full flag set through a misc key
    try_cfg("USER_COMPILE_OPTIMIZATION_LEVEL", "-O2")
    for key in FLAG_KEYS:
        if try_cfg(key, all_flags):
            break
    # per-language std flags only if dedicated keys exist in this tool version
    c_key = next((k for k in dump.split() if k.strip("',:").endswith("USER_COMPILE_C_FLAGS")), None) \
        if "USER_COMPILE_C_FLAGS" in dump else None
    cxx_key = next((k for k in dump.split() if k.strip("',:").endswith("USER_COMPILE_CXX_FLAGS")), None) \
        if "USER_COMPILE_CXX_FLAGS" in dump else None
    if c_key and cfg.get("c_flags"):
        try_cfg("USER_COMPILE_C_FLAGS", " ".join(cfg["c_flags"]))
    else:
        print("  NOTE: no USER_COMPILE_C_FLAGS key; -std=c11 not applied by script (see migration doc)")
    if cxx_key and cfg.get("cxx_flags"):
        try_cfg("USER_COMPILE_CXX_FLAGS", " ".join(cfg["cxx_flags"]))
    else:
        print("  NOTE: no USER_COMPILE_CXX_FLAGS key; -std=c++14 not applied by script (see migration doc)")
    if linker:
        for key in LINKER_KEYS:
            if try_cfg(key, linker):
                break
    for key in LIB_KEYS:
        if try_cfg(key, ",".join(cfg.get("extra_libraries", []))):
            break

    comp = client.get_component(name=app)
    print("BUILD: import ->", comp.import_files(from_loc=str(src_dir), files=files, dest_dir_in_cmp="src"))
    print("BUILD: import (driver) ->",
          comp.import_files(from_loc=str(drv_gen_dir), files=drv_files, dest_dir_in_cmp="src"))
    build = getattr(app_obj, "build", None) or getattr(comp, "build", None)
    try:
        print("BUILD: build() ->", build())
    except Exception as e:
        print("BUILD: build() ERR:", e)

    elfs = sorted(ws.joinpath(app).rglob("*.elf"))
    text = ""
    for log in sorted(ws.joinpath(app).rglob("*.log")):
        try:
            text += log.read_text(encoding="utf-8", errors="replace") + "\n"
        except Exception:
            pass
    app_warn = [ln for ln in text.splitlines()
                if "warning:" in ln.lower() and ("src" in ln.lower() or "m3a" in ln.lower() or "tt_" in ln.lower())]
    required = ["-O2", "-mcpu=cortex-a53", "-ffp-contract=off"]
    flat = "".join(text.split())   # 构建日志按终端宽度折行，flag 可能断在词中间，去空白再匹配
    missing = [f for f in required if f not in flat]
    print(f"ELF candidates: {[str(p.relative_to(ws)) for p in elfs]}")
    print(f"warning lines: app-source={len(app_warn)}")
    for w in app_warn[:10]:
        print("  W:", w.strip()[:160])
    if len(elfs) != 1:
        print(f"BUILD FAIL: expected exactly 1 ELF, found {len(elfs)}")
        return 1
    if app_warn:
        print(f"BUILD FAIL: {len(app_warn)} warning(s) in application sources")
        return 1
    if missing:
        print("BUILD FAIL: required flags not seen in build log:", missing)
        return 1
    print(f"BUILD PASS: 0 application warnings, {elfs[0]}")
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
