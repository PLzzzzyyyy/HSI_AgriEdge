#!/usr/bin/env python3
r"""C3 periph_plat on Vitis 2026.1: platform from build/vivado/tt_zu5ev.xsa
(psu_cortexa53_0, standalone) with xilffs + lwip220, prints PLAT PASS on success.
Mirrors the 2020.2 tools/build_periph_platform.tcl.

Usage (from an ASCII path; 2026.1 fails on non-ASCII paths):
  vitis -s tools/vitis_py/build_periph_platform.py [ws]
ws default build/board/periph_ws; refuses an existing workspace.

2026.1 differences vs the 2020.2 tcl:
  - psu_dp is already driven by dppsu by default; no setdriver step needed.
  - the platform is created with is_pmufw_req=True to get a PMU firmware boot
    domain (the 2020.2 'platform generate' produced it implicitly).
  - xilffs parameters are prefixed (XILFFS_use_lfn ...).
  - lwip is lwip220 added from a project-local BOM-free overlay repo
    (tt_vitis_client.prepare_lwip220_overlay) that MUST be registered before
    the platform is created; plain set_lib('lwip220') then works.
  - lwip parameter names are discovered at runtime and set by suffix match.
  - the KSZ9031 link stays fixed at 1000 Mbps (same rationale as 2020.2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
XSA = ROOT / "build/vivado/tt_zu5ev.xsa"
WS = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build/board/periph_ws"
PLAT_NAME = "periph_plat"
DOMAIN = "standalone_domain"
CPU = "psu_cortexa53_0"
LWIP = "lwip220"


def norm_list(obj):
    if obj is None:
        return []
    return obj if isinstance(obj, list) else [obj]


def main():
    if WS.exists():
        raise SystemExit(f"REFUSE: workspace exists: {WS}; choose a new path")
    if not XSA.is_file():
        raise SystemExit(f"REFUSE: XSA missing: {XSA}")

    client = tt_vitis_client.create_client()
    client.set_workspace(path=str(WS))

    # Register the fixed lwip220 repo BEFORE platform creation (order verified).
    overlay = tt_vitis_client.prepare_lwip220_overlay(ROOT / "build/board/vendor_patches")
    print("PLAT: add_embedded_sw_repo ->", client.add_embedded_sw_repo(path=str(overlay)))

    print(f"PLAT: creating {PLAT_NAME} from {XSA}")
    platform = client.create_platform_component(
        name=PLAT_NAME, hw_design=str(XSA), cpu=CPU, os="standalone",
        domain_name=DOMAIN, is_pmufw_req=True)
    platform.report()
    dom = platform.get_domain(DOMAIN)

    libs = [str(x.get("name")) for x in norm_list(dom.get_applicable_libs()) if isinstance(x, dict)]
    print("PLAT: applicable libs:", ", ".join(libs))
    if "xilffs" not in libs or LWIP not in libs:
        raise SystemExit(f"PLAT FAIL: xilffs/{LWIP} not applicable; see docs/vitis2026_migration.md")

    print(f"PLAT: adding libs {LWIP} + xilffs")
    print("  set_lib xilffs ->", dom.set_lib(lib_name="xilffs"))
    print(f"  set_lib {LWIP} ->", dom.set_lib(lib_name=LWIP))

    def set_param(libname, suffix, value):
        for p in norm_list(dom.list_params(option="lib", lib_name=libname)):
            if not isinstance(p, dict):
                continue
            name = p.get("parameter_name", "")
            if name.lower().endswith(suffix.lower()):
                v = str(value)
                if str(p.get("datatype", "")).lower() == "boolean":
                    v = "true" if str(value).strip().lower() in ("1", "true") else "false"
                print(f"  set_config {name}={v} ({libname}) ->",
                      dom.set_config(option="lib", param=name, value=v, lib_name=libname))
                return True
        print(f"  WARN: no {libname} parameter ending with '{suffix}'; leaving default")
        return False

    set_param("xilffs", "use_lfn", "1")
    # C3 net stack settings carried over from the 2020.2 lwip211 platform.
    set_param(LWIP, "api_mode", "RAW_API")
    set_param(LWIP, "dhcp", "false")
    set_param(LWIP, "phy_link_speed", "CONFIG_LINKSPEED1000")
    set_param(LWIP, "n_rx_descriptors", "256")
    set_param(LWIP, "n_tx_descriptors", "256")
    set_param(LWIP, "pbuf_pool_size", "2048")
    set_param(LWIP, "mem_size", "524288")

    print("PLAT: generating (FSBL, PMUFW, BSP)")
    status = platform.build()
    print("PLAT: platform.build() ->", status)

    bsp = WS / PLAT_NAME / CPU / DOMAIN / "bsp"
    need = [bsp / "include/ff.h", bsp / "include/lwipopts.h", bsp / "include/xdppsu.h",
            bsp / "lib/libxil.a", bsp / "lib/libxilffs.a",
            WS / PLAT_NAME / "zynqmp_fsbl" / "build/fsbl.elf",
            WS / PLAT_NAME / "export" / PLAT_NAME / (PLAT_NAME + ".xpfm")]
    lwip_libs = sorted((bsp / "lib").glob("liblwip*.a"))
    pmufw_hits = [p for p in WS.rglob("pmufw.elf") if "qemu" not in str(p)]
    missing = [str(p) for p in need if not p.is_file()]
    if not lwip_libs:
        missing.append(str(bsp / "lib/liblwip*.a"))
    if not pmufw_hits:
        missing.append("<pmufw.elf under platform>")
    if missing:
        print("PLAT FAIL: missing artifacts:")
        for m in missing:
            print("   ", m)
        return 1

    print("PLAT PASS:", WS)
    print("  bsp include:", bsp / "include")
    print("  lwip libs:  ", [p.name for p in lwip_libs])
    print("  fsbl.elf:   ", need[5])
    print("  pmufw.elf:  ", [str(p.relative_to(WS)) for p in pmufw_hits])
    print("  xpfm:       ", need[6])
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
