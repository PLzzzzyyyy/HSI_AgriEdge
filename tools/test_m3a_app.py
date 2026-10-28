"""Verify packaged M3a App on host and compile A53 objects; NO Vitis build/link/download.

Serial HLS C model is used only for correctness calls. Performance-loop transport
and timer are synthetic, for checking App gating/accounting rather than speed.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
from prepare_m3a_sources import ROOT, APP, SOURCES, SETTINGS, sha

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT/"build/host"/datetime.now().strftime("m3a_app_%Y%m%d_%H%M%S"))
    ap.add_argument("--cxx", default="D:/mingw64/bin/g++.exe")
    ap.add_argument("--hls-include", default="D:/xilinx/Vitis_HLS/2020.2/include")
    ap.add_argument("--a53-bin", type=Path, default=Path("D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin"))
    ap.add_argument("--common-bsp-include", type=Path, default=ROOT/"build/vivado/chk_m2_zu5ev/chk_plat/export/chk_plat/sw/chk_plat/standalone_domain/bspinclude/include")
    args = ap.parse_args()
    bundle, out = args.bundle.resolve(), args.out.resolve()
    src = bundle/APP/"src"
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(scope="host correctness + synthetic timing-control tests + A53 object compile only; NOT RTL/board or final BSP link",
                   bundle=str(bundle), bundle_manifest_sha256=sha(bundle/"manifest.json"), commands=[], inputs=[])
    inputs = [ROOT/"sim/host/test_m3a_app.cpp", Path(__file__).resolve(), ROOT/"tools/test_m3a_sources.py"]
    inputs += list((ROOT/"src/hls").glob("*.h")) + [ROOT/"src/hls/tt_engine.cpp", ROOT/"src/hls/tt_attn.cpp"]
    inputs += list((ROOT/"sim/host/xil_stubs").glob("*.h"))
    for p in inputs: receipt["inputs"].append(dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)))
    def save(): (out/"manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    def run(name, cmd, required=None, timeout=300):
        cmd = list(map(str, cmd))
        start = time.monotonic()
        log = out/(name + ".txt")
        with log.open("wb") as f:
            try: code = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
            except subprocess.TimeoutExpired: code = -1
        text = log.read_text(encoding="utf-8", errors="replace")
        ok = code == 0 and (required is None or required in text)
        receipt["commands"].append(dict(name=name, argv=cmd, exit=code, seconds=round(time.monotonic()-start,3),
                                        passed=ok, log=log.name, sha256=sha(log)))
        save()
        print(name, "PASS" if ok else "FAIL", flush=True)
        if not ok:
            print(text[-8000:]); raise SystemExit(1)
        return text
    run("package_tests", [sys.executable, ROOT/"tools/test_m3a_sources.py", bundle], "OK")
    exe = out/"test_m3a_app.exe"
    units = [src/p.name for p in SOURCES if p.suffix in (".cpp", ".c") and p.name != "main.cpp"]
    units += [src/"m3a_vectors.c", ROOT/"sim/host/test_m3a_app.cpp", ROOT/"src/hls/tt_engine.cpp", ROOT/"src/hls/tt_attn.cpp"]
    run("host_compile", [args.cxx, "-O2", "-std=c++14", "-ffp-contract=off", "-include", "array",
        "-DM3A_MAX_POLLS=8", "-DTT_DB=18", "-DTT_K3=7", "-DTT_M3_OVERLAP=0",
        "-I", src, "-I", ROOT/"sim/host/xil_stubs", "-I", ROOT/"src/hls", "-I", args.hls_include,
        *units, "-Wl,--image-base=0x10000000", "-Wl,--disable-dynamicbase", "-o", exe])
    for mode in ("none", "load-timeout", "timeout", "contract", "mismatch", "timed-mismatch", "guard"):
        text = run("host_" + mode, [exe, mode], "M3A_APP_HOST PASS mode=" + mode)
        if mode == "none":
            perf = re.findall(r"^PERF scope=(\w+) out=(\w+) n=(\d+) runs=(\d+) total_ticks=(\d+).*?ms_per_patch=([\d.]+) patches_per_s=([\d.]+)$", text, re.M)
            expected = {(s,k,n) for s in ("PREEMBED_FULL", "PS_EMBED_PLUS_FULL") for k in ("LOGITS","CLASS") for n in (1,3,16)}
            if {(s,k,int(n)) for s,k,n,*_ in perf} != expected or len(perf) != 12:
                raise RuntimeError("Missing/duplicate timing cases")
            samples = re.findall(r"^SAMPLE scope=(\w+) out=(\w+) n=(\d+) run=(\d+) ticks=(\d+)$", text, re.M)
            if len(samples) != 120: raise RuntimeError("Missing samples")
            for scope,kind,n,runs,ticks,each,rate in perf:
                data = [(int(r),int(t)) for s,k,b,r,t in samples if (s,k,b) == (scope,kind,n)]
                if sorted(r for r,_ in data) != list(range(10)) or sum(t for _,t in data) != int(ticks):
                    raise RuntimeError("Sample/summary mismatch")
                # Synthetic clock frequency is 1 MHz. Do not interpret as performance.
                seconds = int(ticks)/1000000
                if abs(float(each) - seconds*1000/(int(n)*int(runs))) > 1e-6 or abs(float(rate) - int(n)*int(runs)/seconds) > .001:
                    raise RuntimeError("Timing denominator mismatch")
        elif "M3A_BASELINE PASS" in text or "\nPERF " in text:
            raise RuntimeError("Failure published a performance result")

    # Only compile objects. Borrow common standalone headers read-only, NEVER use
    # its old IP headers, libxil, linker script or ELF to claim an M3a final build.
    headers = out/"frozen_xsa_driver_headers"
    headers.mkdir()
    with zipfile.ZipFile(bundle/"tt_m3a_zu5ev/tt_m3a_zu5ev.xsa") as z:
        for name in ("xtt_engine.h", "xtt_engine_hw.h"):
            member = "drivers/tt_engine_v2_0/src/" + name
            (headers/name).write_bytes(z.read(member))
    receipt["a53_common_headers_only"] = str(args.common_bsp_include)
    receipt["a53_common_headers"] = [dict(name=p.name, sha256=sha(p)) for p in sorted(args.common_bsp_include.glob("*.h"))]
    receipt["frozen_driver_headers"] = [dict(name=p.name, sha256=sha(p)) for p in sorted(headers.glob("*.h"))]
    for p in sorted(src.iterdir()):
        if p.suffix not in (".c", ".cpp"): continue
        cc = "gcc" if p.suffix == ".c" else "g++"
        flags = SETTINGS["c_flags" if p.suffix == ".c" else "cxx_flags"]
        text = run("a53_" + p.stem, [args.a53_bin/f"aarch64-none-elf-{cc}.exe", *SETTINGS["compiler_flags"], *flags,
            "-I", src, "-I", headers, "-I", args.common_bsp_include, "-c", p, "-o", out/(p.stem+".o")])
        if re.search(r"warning:", text, re.I): raise RuntimeError("Unexpected A53 warning")
    receipt["result"] = "PASS; final Vitis BSP link and board execution still user-owned/pending"
    save()
    print("M3A_APP_SUITE PASS:", out, flush=True)

if __name__ == "__main__": main()
