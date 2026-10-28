#!/usr/bin/env python3
r"""E 正式系统（ABI4, gcs_r1_abi4_app，DP 画面+网口）在 Vitis 2026.1 上的开发重建。

输入 = 冻结发布包 build/host/gcs_r1_abi4_release_v6：
  app_src/ 35 个源（已 bound：S2C_RELEASE_BOUND 1）
  host_assets/vitis/s2c_roi_app/src/lscript.ld（审查过的低 DDR 链接脚本）
不改冻结包字节；只在暂存副本里做 2026.1 SDT 必需的适配：
  roi_display.cpp 的 DP/DPDMA LookupConfig 改用基址、XAVBuf_CfgInitialize 改为两参。
另：xtime_l.h 垫片转发 xiltimer.h；tt_engine(ABI4/v4) 驱动从平台 hw_artifacts 暂存导入。

注意：本 ELF 是 2026.1 开发/验证构建，不进入 ABI4 发布审计链；板端部署仍走原验收流程。

Usage: vitis -s tools/vitis_py/build_abi4_app.py <ws> [app]
"""
import hashlib
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path(os.environ.get("HSI_ABI4_BUNDLE") or ROOT / "build/host/gcs_r1_abi4_release_v6").resolve()
PLAT = "gcs_r1_abi4_plat"
DOMAIN = "standalone_domain"
LSCRIPT = BUNDLE / "host_assets/vitis/s2c_roi_app/src/lscript.ld"
FLAG_KEYS = ("USER_COMPILE_OTHER_FLAGS", "USER_COMPILE_FLAGS", "USER_COMPILE_MISC", "USER_MISC_FLAGS")
CXX_KEYS = ("USER_COMPILE_CXX_FLAGS", "USER_CXX_FLAGS", "USER_COMPILE_CXX_MISC")
C_KEYS = ("USER_COMPILE_C_FLAGS", "USER_C_FLAGS", "USER_COMPILE_C_MISC")
LINKER_KEYS = ("USER_LINKER_OTHER_FLAGS", "USER_LINKER_MISC", "USER_LINKER_FLAGS")
DRIVER_DEFINES = [
    "-DXPAR_XTT_ENGINE_NUM_INSTANCES=1",
    "-DXPAR_XTT_ENGINE_0_DEVICE_ID=0",
    "-DXPAR_XTT_ENGINE_0_S_AXI_CTRL_BASEADDR=XPAR_TT_ENGINE_0_BASEADDR",
]
DP_LOOKUP_OLD = ("    XDpPsu_Config *cfg = XDpPsu_LookupConfig(XPAR_PSU_DP_DEVICE_ID);\n"
                 "    XDpDma_Config *dcfg = XDpDma_LookupConfig(XPAR_XDPDMA_0_DEVICE_ID);\n")
DP_LOOKUP_NEW = ("#ifdef SDT\n"
                 "    // SDT LookupConfig matches physical base addresses, not legacy device IDs.\n"
                 "    XDpPsu_Config *cfg = XDpPsu_LookupConfig(XPAR_XDPPSU_0_BASEADDR);\n"
                 "    XDpDma_Config *dcfg = XDpDma_LookupConfig(XPAR_XDPDMA_0_BASEADDR);\n"
                 "#else\n" + DP_LOOKUP_OLD + "#endif\n")
XAVBUF_OLD = "    XAVBuf_CfgInitialize(&g_avbuf, g_dp.Config.BaseAddr, XPAR_PSU_DP_DEVICE_ID);\n"
XAVBUF_NEW = ("#ifdef SDT\n"
              "    /* 2026.1 SDT BSP：XAVBuf_CfgInitialize 去掉了第三参 DeviceId（xavbuf.h 的 #ifndef SDT 分支）。 */\n"
              "    XAVBuf_CfgInitialize(&g_avbuf, g_dp.Config.BaseAddr);\n"
              "#else\n"
              "    XAVBuf_CfgInitialize(&g_avbuf, g_dp.Config.BaseAddr, XPAR_PSU_DP_DEVICE_ID);\n"
              "#endif\n")
REQUIRED = ("-O2", "-mcpu=cortex-a53", "-ffp-contract=off")


def adapt_display_for_sdt(text):
    """Adapt known frozen display code; reject missing/duplicate transformations."""
    for label, old, new in (("DP/DPDMA LookupConfig", DP_LOOKUP_OLD, DP_LOOKUP_NEW),
                            ("XAVBuf_CfgInitialize", XAVBUF_OLD, XAVBUF_NEW)):
        # Each adapted block retains exactly one legacy call in its #else branch.
        if text.count(new) == 1 and text.count(old) == 1:
            continue
        if text.count(new) or text.count(old) != 1:
            raise ValueError(f"unrecognized or duplicate {label} in roi_display.cpp")
        text = text.replace(old, new, 1)
    return text


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ws = Path(sys.argv[1]).resolve()
    app = sys.argv[2] if len(sys.argv) > 2 else "gcs_r1_abi4_app"
    if not (ws / PLAT).is_dir():
        raise SystemExit(f"REFUSE: platform {PLAT} not in {ws}; run build_abi4_platform.py first")
    if not (BUNDLE / "app_src").is_dir() or not LSCRIPT.is_file():
        raise SystemExit(f"REFUSE: frozen bundle incomplete: {BUNDLE}")

    stage = ws / "_appsrc"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    files = []
    for f in sorted((BUNDLE / "app_src").iterdir()):
        if f.is_file():
            shutil.copy2(f, stage / f.name)
            files.append(f.name)
    disp = stage / "roi_display.cpp"
    text = disp.read_text(encoding="utf-8")
    try:
        adapted = adapt_display_for_sdt(text)
    except ValueError as exc:
        raise SystemExit(f"REFUSE: {exc}") from exc
    if adapted != text:
        disp.write_text(adapted, encoding="utf-8")
    print("BUILD: staged roi_display.cpp SDT adaptation verified (DP/DMA base-address lookup; XAVBuf 2-arg call)")
    shim = tt_vitis_client.stage_xtime_shim(stage)
    if shim:
        files.append(shim)
        print(f"BUILD: staged xtime_l.h shim -> xiltimer.h ({shim})")
    print(f"BUILD: staged {len(files)} app sources from frozen bundle")
    drv_gen_dir, drv_files = tt_vitis_client.stage_hls_driver(ws, "tt_engine", plat=PLAT)

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

    print(f"BUILD: creating app {app} on {PLAT}")
    app_obj = client.create_app_component(name=app, platform=client.find_platform_in_repos(PLAT),
                                          domain=DOMAIN, template="empty_application")

    def try_cfg(key, value):
        try:
            print(f"  set {key} = {value} ->", app_obj.set_app_config(key=key, values=value))
            return True
        except Exception as e:
            print(f"  set {key} ERR: {e}")
            return False

    try_cfg("USER_COMPILE_OPTIMIZATION_LEVEL", "-O2")
    flags = " ".join(tt_vitis_client.bsp2026_compat_defines() + DRIVER_DEFINES
                     + ["-mcpu=cortex-a53", "-ffp-contract=off", "-ffunction-sections",
                        "-fdata-sections", "-Wall", "-Wextra", "-Werror"])
    for key in FLAG_KEYS:
        if try_cfg(key, flags):
            break
    got_cxx = any(try_cfg(k, "-std=c++14") for k in CXX_KEYS)
    got_c = any(try_cfg(k, "-std=c11") for k in C_KEYS)
    print(f"BUILD: CXX std applied={got_cxx}; C std applied={got_c}")
    if not got_cxx:
        print("  NOTE: no CXX std key; -std=c++14 not applied by script (staged C driver would warn)")
    for key in LINKER_KEYS:
        if try_cfg(key, "-Wl,--gc-sections"):
            break
    for key in ("USER_LINK_LIBRARIES", "USER_LINKER_LIBRARIES"):
        if try_cfg(key, "m"):
            break

    comp = client.get_component(name=app)
    print("BUILD: import (app) ->", comp.import_files(from_loc=str(stage), files=files, dest_dir_in_cmp="src"))
    print("BUILD: import (driver) ->",
          comp.import_files(from_loc=str(drv_gen_dir), files=drv_files, dest_dir_in_cmp="src"))
    dst_ls = ws / app / "src" / "lscript.ld"
    shutil.copy2(LSCRIPT, dst_ls)
    print(f"BUILD: installed reviewed low-DDR lscript.ld -> {dst_ls}")

    print("BUILD: compiling")
    build = getattr(app_obj, "build", None) or getattr(comp, "build", None)
    try:
        print("BUILD: build() ->", build())
    except Exception as e:
        print("BUILD: build() ERR:", e)

    elfs = sorted(ws.joinpath(app).rglob("*.elf"))
    print("ELF candidates:", [str(p.relative_to(ws)) for p in elfs])
    text = ""
    for log in sorted(ws.joinpath(app).rglob("*.log")):
        try:
            text += log.read_text(encoding="utf-8", errors="replace") + "\n"
        except Exception:
            pass
    app_warn = [ln for ln in text.splitlines() if "warning:" in ln.lower()
                and any(k in ln.lower() for k in ("src", "roi", "tt_", "m3a", "boot", "legacy"))]
    print(f"warning lines: app-source={len(app_warn)}")
    for w in app_warn[:10]:
        print("  W:", w.strip()[:160])
    flat = "".join(text.split())
    missing = [f for f in REQUIRED if f not in flat]
    ninja = ws / app / "build" / "build.ninja"
    ninja_text = ninja.read_text(encoding="utf-8", errors="replace") if ninja.is_file() else ""
    print("lscript.ld referenced (build.ninja -T):", "lscript.ld" in ninja_text)
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
    print(f"  elf size: {elfs[0].stat().st_size} bytes; lscript sha256 prefix: "
          f"{hashlib.sha256(LSCRIPT.read_bytes()).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
