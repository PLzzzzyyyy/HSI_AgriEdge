#!/usr/bin/env python3
r"""C3 periph application on Vitis 2026.1: builds src/ps/periph into an Empty
app on periph_plat (created by build_periph_platform.py), Release configuration,
aiming for -O2 -mcpu=cortex-a53 -Wall -Wextra -Werror, prints BUILD PASS
(0 application-source warnings, exactly 1 ELF) on success.
Mirrors the 2020.2 tools/build_periph_app.tcl.

Usage (from an ASCII path):
  vitis -s tools/vitis_py/build_periph_app.py [ws] [app]
ws default build/board/periph_ws; app default periph_zu5ev.
The ELF is left in the workspace; board/periph/ is not overwritten.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WS = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build/board/periph_ws"
APP = sys.argv[2] if len(sys.argv) > 2 else "periph_zu5ev"
PLAT = "periph_plat"
DOMAIN = "standalone_domain"
# 2026.1: 补回 SDT BSP 不再导出的经典 XPAR 宏（值与 2020.2 一致，见 tt_vitis_client.bsp2026_compat_defines）
DESIRED_FLAGS = " ".join(tt_vitis_client.bsp2026_compat_defines() + ["-mcpu=cortex-a53", "-Wall", "-Wextra", "-Werror"])


def main():
    if not (WS / PLAT).is_dir():
        raise SystemExit(f"REFUSE: platform {PLAT} not found in {WS}; run build_periph_platform.py first")

    src_dir = ROOT / "src/ps/periph"
    src_files = sorted(p for p in src_dir.iterdir() if p.suffix in (".c", ".cpp", ".h"))
    print("BUILD: sources:", ", ".join(p.name for p in src_files))

    client = tt_vitis_client.create_client()
    tt_vitis_client.set_workspace_retry(client, WS)
    try:
        client.delete_component(APP)
        print(f"BUILD: removed existing component {APP} (if any)")
    except Exception as e:
        print(f"BUILD: no existing component to remove: {e}")
    app_dir = WS / APP
    if app_dir.exists():
        shutil.rmtree(app_dir, ignore_errors=True)
        print(f"BUILD: removed stale app dir {app_dir}")
    platform_xpfm = client.find_platform_in_repos(PLAT)
    print("BUILD: platform:", platform_xpfm)

    print(f"BUILD: creating app {APP}")
    app = client.create_app_component(name=APP, platform=platform_xpfm, domain=DOMAIN, template="empty_application")

    print("== app config dump (keys for reference) ==")
    try:
        print(app.get_app_config())
    except Exception as e:
        print("cfg dump err:", e)

    def try_cfg(key, value):
        try:
            r = app.set_app_config(key=key, values=value)
            print(f"  set {key} = {value} ->", r)
            return True
        except Exception as e:
            print(f"  set {key} ERR: {e}")
            return False

    try_cfg("USER_COMPILE_OPTIMIZATION_LEVEL", "-O2")
    for key in ("USER_COMPILE_OTHER_FLAGS", "USER_COMPILE_FLAGS", "USER_COMPILE_MISC", "USER_MISC_FLAGS"):
        if try_cfg(key, DESIRED_FLAGS):
            break

    comp = client.get_component(name=APP)
    status = comp.import_files(from_loc=str(src_dir), files=[p.name for p in src_files], dest_dir_in_cmp="src")
    print("BUILD: import_files ->", status)

    print("BUILD: compiling")
    build = getattr(app, "build", None) or getattr(comp, "build", None)
    try:
        print("BUILD: build() ->", build())
    except Exception as e:
        print("BUILD: build() ERR:", e)

    app_dir = WS / APP
    print("== app dir (depth<=4) ==")
    for root, dirs, files in app_dir.walk() if hasattr(app_dir, "walk") else []:
        pass
    import os
    for root, dirs, files in os.walk(app_dir):
        rel = Path(root).relative_to(app_dir)
        if len(rel.parts) <= 4:
            print("DIR:", rel if str(rel) != "." else "<app>")
            for f in sorted(files)[:8]:
                print("   f:", f)

    elfs = sorted(app_dir.rglob("*.elf"))
    logs = sorted(app_dir.rglob("*.log"))
    print("ELF candidates:", [str(p.relative_to(WS)) for p in elfs])
    warn_lines = []
    for log in logs:
        try:
            for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if "warning:" in ln.lower():
                    warn_lines.append(f"{log.name}: {ln.strip()[:160]}")
        except Exception:
            pass
    app_warn = [w for w in warn_lines if "src" in w.lower() or "periph" in w.lower()]
    print(f"warning lines: total={len(warn_lines)} app-source={len(app_warn)}")
    for w in app_warn[:10]:
        print("  W:", w)

    if len(elfs) != 1:
        print(f"BUILD FAIL: expected exactly 1 ELF, found {len(elfs)}")
        return 1
    if app_warn:
        print(f"BUILD FAIL: {len(app_warn)} warning(s) in application sources")
        return 1
    print(f"BUILD PASS: 0 application warnings, {elfs[0]}")
    print("  (download copy board/periph/ is not overwritten)")
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
