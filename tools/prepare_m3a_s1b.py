"""S1b source-only package; reads frozen data/XSA, NEVER invokes hardware tools."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zlib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
XSA = Path("build/vivado/tt_m3a_zu5ev.xsa")
XSA_SHA = "9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652"
SCENE = Path("data/scenes/longkou")
FILES = ("cube_f32.bin", "weights/v2/cls_token.bin", "weights/v2/pos_embed.bin", "weights/v2/weights_engine.bin")
SIZES = (243794880, 10584, 63504, 480576)
SOURCES = ["src/ps/"+p for p in ("tt_m3a.cpp", "tt_m3a.h", "tt_net.cpp", "tt_net.h", "tt_hw.h")]
SOURCES += ["src/hls/tt_engine_regs.h"]  # pure C register contract, not HLS implementation
SOURCES += ["src/ps/system/"+p for p in ("m3a_roi.cpp", "m3a_roi.h", "m3a_sd.cpp", "m3a_sd.h", "m3a_app.cpp", "m3a_app.h", "s1b/main.cpp", "s1b/legacy_traps.cpp")]

def digest(path):
    h = hashlib.sha256()
    crc = 0
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
            crc = zlib.crc32(b, crc)
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size,
                sha256=h.hexdigest(), crc32=f"{crc:08x}")

def verify():
    meta = dict(line.split("=", 1) for line in (ROOT/SCENE/"meta.txt").read_text(encoding="utf-8").splitlines())
    for key, value in dict(scene="longkou", model="unoverlapping", H="550", W="400", pad="3", bands="270",
                           classes="9", N="6", D="2646", DF="12", WF="14", MF="14", weights_version="v2").items():
        if meta.get(key) != value:
            raise ValueError(f"Unsupported fixed profile: {key}")
    records = []
    for name, size in zip(FILES, SIZES):
        r = digest(ROOT/SCENE/name)
        if r["bytes"] != size or r["sha256"] != meta["sha256:"+name]:
            raise ValueError(f"Size/SHA mismatch: {name}")
        records.append(r)
    cube = np.memmap(ROOT/SCENE/FILES[0], dtype="<f4", mode="r", shape=(556,406,270))
    if not all(np.isfinite(cube[y:y+16]).all() for y in range(0,556,16)):
        raise ValueError("Cube contains NaN/Inf")
    if any(np.any(a != 0) for a in (cube[:3], cube[-3:], cube[:,:3], cube[:,-3:])):
        raise ValueError("Expected three zero border pixels")
    del cube
    cls = np.fromfile(ROOT/SCENE/FILES[1], dtype="<f4").astype(np.float64)
    pos = np.fromfile(ROOT/SCENE/FILES[2], dtype="<f4").astype(np.float64).reshape(2646,6)
    if not np.isfinite(cls).all() or not np.isfinite(pos).all():
        raise ValueError("Nonfinite embed parameters")
    package = (ROOT/SCENE/FILES[3]).read_bytes()
    if struct.unpack_from("<4I",package) != (0x32455454,2,9,16):
        raise ValueError("Not complete N6 int16 TTE2 weights")
    # Match exporter's double-precision addition, NOT PS Q3.12 rounding.
    pos[:,0] += cls
    emb = np.floor(pos*(1<<24)+0.5).astype("<i4")
    if emb.tobytes() != package[64:64+63504]:
        raise ValueError("cls/pos do not match the package EMB segment")
    proj = ROOT/SCENE/"weights/v2/weights_all.bin"
    pr = digest(proj)
    if pr["sha256"] != meta["sha256:weights/v2/weights_all.bin"] or proj.read_bytes() != package[191232:]:
        raise ValueError("Projection segment mismatch")
    xsa = digest(ROOT/XSA)
    old = json.loads((ROOT/"board/m3/20261007_system_impl/manifest.json").read_text(encoding="utf-8"))
    if xsa["sha256"] != XSA_SHA or old["xsa"]["sha256"] != XSA_SHA:
        raise ValueError("Frozen serial XSA identity mismatch")
    with zipfile.ZipFile(ROOT/XSA) as z:
        if z.testzip():
            raise ValueError("XSA zip CRC failure")
        hwh = ET.fromstring(z.read("design_1.hwh"))
        params = {e.get("NAME"):e.get("VALUE") for e in hwh.iter("PARAMETER")}
        if params.get("PSU__SD1__PERIPHERAL__ENABLE") != "1":
            raise ValueError("Frozen XSA lacks SD1")
        if "drivers/tt_engine_v2_0/src/xtt_engine.h" not in z.namelist():
            raise ValueError("Missing frozen engine driver")
    return dict(files=records, projection=pr, meta=digest(ROOT/SCENE/"meta.txt"), xsa=xsa,
        checks=["meta and exact size/SHA", "finite little-endian float32 HWC and 3-pixel zero border",
                "cls+pos matches Q24 EMB export exactly", "projection segment matches v2 int16 weights_all",
                "frozen serial XSA SHA and zip CRC", "SD1 enabled on MIO 46..51"],
        limitations="No SD/PL board verification; no numerical FULL inference; no BSP/final A53 link",
        bsp_action_pending="Independent platform only: xilffs 4.4, LFN, >=2 logical volumes and SD1 mapping; no BSP mutation authorized/executed")

def prepare(out):
    out = out.resolve()
    if out.exists():
        raise FileExistsError(f"Refusing overwrite: {out}")
    # Never package underneath an existing user platform/app.
    if (ROOT/"vitis").resolve() in out.parents or out == ROOT/"vitis":
        raise ValueError("Use an independent source output, not vitis/")
    audit = verify()
    src = out/"app_src"
    src.mkdir(parents=True)
    for p in SOURCES:
        shutil.copyfile(ROOT/p, src/Path(p).name)
    rev = subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    h = ['#ifndef S1B_PROFILE_H', '#define S1B_PROFILE_H', '#include "m3a_sd.h"',
         '#define S1B_CUBE_BYTES 243794880u', f'#define S1B_SOURCE_REV "{rev[:12]}+manifest"',
         'static const TTM3aSdProfile S1B_PROFILE={400,550,270,3,9,{']
    for name,r in zip(FILES,audit["files"]):
        h.append(f'    {{"1:/scenes/longkou/{name}",{r["bytes"]}u,0x{r["crc32"]}u}},')
    h += ['}};', '#endif', '']
    (src/"s1b_profile.h").write_text("\n".join(h),encoding="utf-8")
    (out/"hardware").mkdir()
    shutil.copyfile(ROOT/XSA,out/"hardware"/XSA.name)
    audit.update(created=datetime.now().astimezone().isoformat(),source_parent_commit=rev,
        status="SOURCE_ONLY; user BSP configuration + Build/download pending", sources=[digest(ROOT/p) for p in SOURCES],
        app_settings=dict(platform="NEW s1b_m3a_plat",app="NEW s1b_roi_app",processor="psu_cortexa53_0",os="standalone",
            flags=["-std=c++14","-O2","-mcpu=cortex-a53","-ffp-contract=off","-ffunction-sections","-fdata-sections","-Wall","-Wextra","-Werror"],
            link=["m","xilffs","-Wl,--gc-sections"],stdin="psu_uart_0",stdout="psu_uart_0",
            memory="All static buffers in low DDR; cube 243794880 B plus <1 MiB other buffers; verify final link map"))
    audit["outputs"] = [dict(path=p.relative_to(out).as_posix(),bytes=p.stat().st_size,
                             sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(out.rglob("*")) if p.is_file()]
    (out/"manifest.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    return audit

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    prepare(args.out)
    print("S1B_SOURCE_ONLY PASS",args.out)

if __name__ == "__main__":
    main()
