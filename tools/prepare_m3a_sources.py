"""Package ONLY the frozen serial M3a XSA and standalone App sources. No builds."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
XSA = Path("build/vivado/tt_m3a_zu5ev.xsa")
SYSTEM = Path("board/m3/20261007_system_impl/manifest.json")
FROZEN = Path("board/m3/20261007_driver_preflight/host_manifest.json")
GOLDEN = Path("sim/golden/n6_engine")
XSA_SHA = "9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652"
DN = 15876
APP = Path("tt_m3a_zu5ev/test_m3a")
SOURCES = [Path("src/ps") / f for f in (
    "tt_m3a.cpp tt_m3a.h tt_net.cpp tt_net.h tt_hw.h tt_hw_sim.cpp tt_ref_int.h tt_data.c tt_data.h"
).split()] + [Path("src/hls/tt_engine_regs.h")] + [Path("src/ps/m3a") / f for f in (
    "main.cpp m3a_bench.cpp m3a_bench.h m3a_vectors.h"
).split()]
SETTINGS = dict(processor="psu_cortexa53_0", os="standalone", language="c++",
    stdin="psu_uart_0", stdout="psu_uart_0", defines=[], extra_libraries=["m"],
    compiler_flags=["-O2", "-mcpu=cortex-a53", "-ffp-contract=off", "-ffunction-sections",
                    "-fdata-sections", "-Wall", "-Wextra", "-Werror"],
    c_flags=["-std=c11"], cxx_flags=["-std=c++14"], linker_flags=["-Wl,--gc-sections"],
    default_runs=10, default_batch=16, max_polls=100000000)

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def vectors(root=ROOT):
    """Return typed arrays AND exact input paths. Validate narrowing, sizes, weights."""
    used = []
    def read(rel, code, count):
        p = GOLDEN / rel
        data = (root / p).read_bytes()
        if len(data) != struct.calcsize("<" + code) * count:
            raise ValueError(f"Unexpected golden size: {p}")
        used.append(p)
        return list(struct.unpack("<" + str(count) + code, data))
    weights = read("weights_engine.bin", "I", 480576 // 4)
    if weights[:4] != [0x32455454, 2, 9, 16]:
        raise ValueError("Not the complete LongKou int16 M3a weight package")
    a = read("a/x_in_i16.bin", "h", DN)
    b = read("b/x_embed_i32.bin", "i", DN)
    if any(v < -32768 or v > 32767 for v in b):
        raise ValueError("Golden B cannot be narrowed to M3a int16 input")
    layers = sum((read(f"a/L{l}_x_out_i4.bin", "i", DN) for l in range(12)), [])
    if any(v < -32768 or v > 32767 for v in layers[4*DN:5*DN]):
        raise ValueError("Resume L4 cannot be narrowed without losing bits")
    logits = read("a/logits_q16_i32.bin", "i", 32) + read("b/logits_q16_i32.bin", "i", 32)
    classes = read("a/class_u32.bin", "I", 1) + read("b/class_u32.bin", "I", 1)
    return [("uint32_t", "m3a_weights", weights), ("int16_t", "m3a_input_a", a),
            ("int16_t", "m3a_input_b", b), ("int32_t", "m3a_layers_a", layers),
            ("int32_t", "m3a_logits", logits), ("uint32_t", "m3a_classes", classes)], used

def verify_frozen(root, golden):
    record = json.loads((root / SYSTEM).read_text(encoding="utf-8"))
    if record["xsa"]["sha256"] != XSA_SHA or sha(root / XSA) != XSA_SHA:
        raise ValueError("Serial XSA hash mismatch: refuse candidate/replacement XSA")
    with zipfile.ZipFile(root / XSA) as z:
        if z.testzip() is not None: raise ValueError("XSA ZIP CRC error")
    frozen = {f["path"]: f["sha256"] for f in json.loads((root / FROZEN).read_text())["files"]}
    for rel in golden + [Path("src/hls/tt_engine_regs.h")]:
        if frozen.get(rel.as_posix()) != sha(root / rel):
            raise ValueError(f"Serial golden/contract snapshot mismatch: {rel}")

def stage(out: Path, root=ROOT):
    out = out.resolve()
    if out.exists(): raise FileExistsError(f"Refusing to overwrite {out}")
    arrays, golden = vectors(root)
    verify_frozen(root, golden)
    paths = SOURCES + golden + [XSA, SYSTEM, FROZEN, Path("board/m3/app_readme.md"),
                               Path("tools/prepare_m3a_sources.py")]
    inputs = [dict(path=p.as_posix(), bytes=(root/p).stat().st_size, sha256=sha(root/p)) for p in paths]
    digest = hashlib.sha256(json.dumps([inputs, SETTINGS], sort_keys=True).encode()).hexdigest()
    rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    manifest = dict(status="source-only; user Build/download pending; not board evidence",
        package_id=digest[:16], source_parent_commit=rev, inputs_digest=digest,
        xsa_sha256=XSA_SHA, app_directory=APP.as_posix(), inputs=inputs, files=[])
    src = out / APP / "src"
    src.mkdir(parents=True)
    for p in SOURCES: shutil.copyfile(root/p, src/p.name)
    shutil.copyfile(root/XSA, out/"tt_m3a_zu5ev"/XSA.name)
    shutil.copyfile(root/"board/m3/app_readme.md", out/"README.md")
    with (src/"m3a_vectors.c").open("w", encoding="utf-8", newline="\n") as f:
        f.write('// Generated from frozen golden binaries; do not hand edit.\n#include "m3a_vectors.h"\n')
        for typ, name, values in arrays:
            f.write(f"const {typ} {name}[{len(values)}] __attribute__((aligned(64))) = {{\n")
            for i in range(0, len(values), 16):
                f.write("  " + ",".join(str(x) + ("u" if typ == "uint32_t" else "") for x in values[i:i+16]) + ",\n")
            f.write("};\n")
    (src/"m3a_package.h").write_text(
        f'#define M3A_PACKAGE_ID "{digest[:16]}"\n#define M3A_SOURCE_REV "{rev[:12]}+manifest"\n'
        f'#define M3A_XSA_SHA256 "{XSA_SHA}"\n', encoding="utf-8")
    (out/APP/"settings.json").write_text(json.dumps(SETTINGS, indent=2) + "\n", encoding="utf-8")
    for p in sorted(out.rglob("*")):
        if p.is_file(): manifest["files"].append(dict(path=p.relative_to(out).as_posix(), bytes=p.stat().st_size, sha256=sha(p)))
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"M3A SOURCE PACKAGE READY: {out}\npackage_id={digest[:16]}; frozen serial XSA; no workspace/build/download")
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT/"build/board"/datetime.now().strftime("m3a_sources_%Y%m%d_%H%M%S"))
    stage(parser.parse_args().out)
