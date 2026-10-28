#!/usr/bin/env python3
r"""Platform check on Vitis 2026.1: create a plain standalone platform from a
candidate XSA and generate (BSP + boot) so the custom HLS driver in the XSA is
exercised end to end. Prints CHECK PASS with the driver headers found.
Mirrors the 2020.2 tools/check_xsa_platform.tcl.

Usage (from an ASCII path):
  vitis -s tools/vitis_py/check_xsa_platform.py <xsa> <out_dir> [proc] [driver]
  proc default psu_cortexa53_0 (ZU5EV); driver default tucker_proj (M2: tt_engine).
The output directory must not exist yet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt_vitis_client  # noqa: E402


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    xsa = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    proc = sys.argv[3] if len(sys.argv) > 3 else "psu_cortexa53_0"
    drv = sys.argv[4] if len(sys.argv) > 4 else "tucker_proj"
    if xsa.suffix.lower() != ".xsa" or not xsa.is_file():
        raise SystemExit(f"REFUSE: XSA not found: {xsa}")
    if out.exists():
        raise SystemExit(f"REFUSE: output dir exists: {out}; choose a new path")

    client = tt_vitis_client.create_client()
    client.set_workspace(path=str(out))
    print(f"CHECK: creating platform from {xsa} (proc {proc})")
    platform = client.create_platform_component(
        name="chk_plat", hw_design=str(xsa), cpu=proc, os="standalone",
        domain_name="standalone_domain")
    print("CHECK: generating platform (BSP + drivers)")
    platform.build()

    bsp = out / "chk_plat" / proc / "standalone_domain" / "bsp"
    libxil = bsp / "lib/libxil.a"
    # 2026.1：SDT BSP 不把 HLS 自定义驱动并入 libsrc/include，而是把源码放到
    # hw_artifacts/drivers/<drv>_v*/src（bsp.yaml 里该驱动为 None），由应用自行导入编译。
    drv_dirs = sorted(d for d in (bsp / "hw_artifacts/drivers").glob("*")
                      if drv in d.name.lower() and (d / "src").is_dir())
    drv_hdrs = sorted(f for d in drv_dirs for f in (d / "src").glob(f"x{drv}*.h"))
    inc = sorted((bsp / "include").glob(f"x{drv}*.h"))  # 经典布局（2020.2）参考点
    print("CHECK: driver dirs (hw_artifacts):", [d.name for d in drv_dirs])
    print("CHECK: driver headers:", [f.name for f in drv_hdrs])
    print("CHECK: classic include headers:", [f.name for f in inc])
    print("CHECK: libxil:", libxil.is_file())
    if len(drv_hdrs) < 2 or not libxil.is_file():
        print(f"CHECK FAIL: platform generated but {drv} driver sources/libxil missing")
        return 1
    print(f"CHECK PASS: platform generated, {drv} driver sources staged ({out})")
    return 0


if __name__ == "__main__":
    rc = main()
    import vitis

    vitis.dispose()
    sys.exit(rc)
