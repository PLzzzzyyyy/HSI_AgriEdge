#!/usr/bin/env python3
r"""E 正式系统（ABI4）平台在 Vitis 2026.1 上的重建：gcs_r1_abi4_plat。

硬体输入 = 冻结发布包里的 XSA
build/host/gcs_r1_abi4_release_v6/hardware/tt_gcs_r1_abi4_zu5ev.xsa
（与 build/vivado/tt_gcs_r1_abi4_zu5ev.xsa 逐字节同 SHA）。
BSP 配置对齐 2020.2 的 prepare_gcs_platform.tcl：xilffs(use_lfn) + lwip RAW_API、
无 DHCP、1000M、256/256 描述符、pbuf 2048、mem 524288、psu_dp 默认 dppsu。
2026.1 差异：lwip211 改成 lwip220（项目内覆盖仓库，见 docs/vitis2026_migration.md §4.3）。

注意：本脚本产出的是 2026.1 开发/验证平台，不进入 ABI4 发布审计链
（那条链要求用户在 GUI 建平台并按身份登记）。

Usage: vitis -s tools/vitis_py/build_abi4_platform.py [ws]
ws 默认 build/board/abi4_ws；已存在即拒绝。
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
XSA = Path(os.environ.get('HSI_ABI4_XSA') or ROOT / "build/host/gcs_r1_abi4_release_v6/hardware/tt_gcs_r1_abi4_zu5ev.xsa").resolve()
WS = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build/board/abi4_ws"
PLAT_NAME = "gcs_r1_abi4_plat"
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
        raise SystemExit(f"REFUSE: frozen ABI4 XSA missing: {XSA}")

    client = tt_vitis_client.create_client()
    client.set_workspace(path=str(WS))

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
        raise SystemExit("PLAT FAIL: xilffs/lwip220 not applicable; see docs/vitis2026_migration.md")

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
    set_param(LWIP, "api_mode", "RAW_API")
    set_param(LWIP, "dhcp", "false")
    set_param(LWIP, "phy_link_speed", "CONFIG_LINKSPEED1000")
    set_param(LWIP, "n_rx_descriptors", "256")
    set_param(LWIP, "n_tx_descriptors", "256")
    set_param(LWIP, "pbuf_pool_size", "2048")
    set_param(LWIP, "mem_size", "524288")

    print("PLAT: generating (FSBL, PMUFW, BSP)")
    print("PLAT: platform.build() ->", platform.build())

    bsp = WS / PLAT_NAME / CPU / DOMAIN / "bsp"
    need = [bsp / "include/ff.h", bsp / "include/lwipopts.h", bsp / "include/xdppsu.h",
            bsp / "lib/libxil.a", bsp / "lib/libxilffs.a",
            WS / PLAT_NAME / "zynqmp_fsbl" / "build/fsbl.elf",
            WS / PLAT_NAME / "export" / PLAT_NAME / (PLAT_NAME + ".xpfm")]
    lwip_libs = sorted((bsp / "lib").glob("liblwip*.a"))
    pmufw_hits = [p for p in WS.rglob("pmufw.elf") if "qemu" not in str(p)]
    drv_dirs = sorted(d.name for d in (bsp / "hw_artifacts/drivers").glob("*")) \
        if (bsp / "hw_artifacts/drivers").is_dir() else []
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
    print("  lwip libs:  ", [p.name for p in lwip_libs])
    print("  hw_artifacts drivers:", drv_dirs)
    print("  pmufw.elf:  ", [str(p.relative_to(WS)) for p in pmufw_hits])
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
