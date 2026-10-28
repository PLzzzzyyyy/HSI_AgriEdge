"""Build/run the isolated M3a driver against the HLS C model, never a board App.

Windows defaults match this project. Override --cxx / --hls-include as needed.
A new output directory is required: no deletion, no old evidence overwritten.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
MODES = ("load-contract", "load-timeout", "timeout", "contract", "engine-error", "cycles-zero", "cycles-overflow", "full")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="D:/mingw64/bin/g++.exe")
    parser.add_argument("--hls-include", default="D:/xilinx/Vitis_HLS/2020.2/include")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--overlap", type=int, choices=(0, 1), default=0,
                        help="M3a attention/V-projection overlap candidate; baseline remains 0")
    args = parser.parse_args()
    out = (args.out or ROOT / "build/host" / datetime.datetime.now().strftime("m3a_driver_%Y%m%d_%H%M%S")).resolve()
    if not Path(args.cxx).is_file() or not (Path(args.hls_include) / "ap_int.h").is_file():
        parser.error("compiler or HLS headers not found")
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"scope": "host model, not RTL/board", "overlap": args.overlap, "commands": [], "files": []}
    sources = ["sim/host/test_m3a_driver.cpp", "src/ps/tt_m3a.cpp", "src/hls/tt_engine.cpp", "src/hls/tt_attn.cpp"]
    inputs = set(ROOT / f for f in sources)
    inputs.update((ROOT / "src/hls").glob("*.h"))
    inputs.add(ROOT / "src/ps/tt_m3a.h")
    inputs.add(Path(__file__).resolve())
    inputs.update(p for p in (ROOT / "sim/host/xil_stubs").glob("*.h"))
    inputs.update(p for p in (ROOT / "sim/golden/n6_engine").rglob("*") if p.is_file())
    for p in sorted(inputs):
        data = p.read_bytes()
        receipt["files"].append({"path": p.relative_to(ROOT).as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    def run(name, command, required=None, timeout=1200):
        start = time.monotonic()
        log = out / (name + ".log")
        with log.open("wb") as stream:
            try:
                code = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                code = -1
        text = log.read_text(encoding="utf-8", errors="replace")
        ok = code == 0 and (required is None or required in text)
        receipt["commands"].append({"name": name, "argv": command, "exit": code, "seconds": round(time.monotonic()-start, 3), "pass": ok, "log": log.name, "sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(name, "PASS" if ok else "FAIL", flush=True)
        if not ok:
            print(text[-6000:])
            raise SystemExit(1)

    includes = ["-I", str(ROOT / "sim/host/xil_stubs"), "-I", str(ROOT / "src/ps"), "-I", str(ROOT / "src/hls")]
    run("driver_syntax", [args.cxx, "-std=c++14", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", *includes, str(ROOT / "src/ps/tt_m3a.cpp")])
    binary = out / "test_m3a_driver.exe"
    run("compile", [args.cxx, "-O2", "-std=c++14", "-ffp-contract=off", "-include", "array", "-DTT_DB=18", "-DTT_K3=7", "-DTT_M3_OVERLAP=" + str(args.overlap), *includes,
                    "-I", args.hls_include, *(str(ROOT / p) for p in sources), "-Wl,--image-base=0x10000000", "-Wl,--disable-dynamicbase", "-o", str(binary)])
    for mode in MODES:
        run(mode, [str(binary), mode], "M3A_DRIVER PASS (" + mode + ")")
    print("M3A_DRIVER_SUITE PASS:", out, flush=True)


if __name__ == "__main__":
    main()
