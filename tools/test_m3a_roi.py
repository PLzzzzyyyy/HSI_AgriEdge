"""S1a host PS ROI tests. Real numerics/driver; MMIO mock, no HLS/RTL/board tools."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
MODES = ("success", "numeric-prefix", "not-ready", "engine-error", "contract", "timeout")
SOURCES = ("sim/host/test_m3a_roi.cpp", "src/ps/system/m3a_roi.cpp", "src/ps/tt_net.cpp", "src/ps/tt_m3a.cpp")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default="D:/mingw64/bin/g++.exe")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    out = (args.out or ROOT / "build/host" / datetime.now().strftime("m3a_roi_%Y%m%d_%H%M%S")).resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = [ROOT / p for p in SOURCES]
    inputs += [ROOT / p for p in ("src/ps/system/m3a_roi.h", "src/ps/tt_net.h", "src/ps/tt_hw.h",
                                "src/ps/tt_m3a.h", "src/hls/tt_engine_regs.h", "tools/test_m3a_roi.py")]
    inputs += list((ROOT / "sim/host/xil_stubs").glob("*.h"))
    receipt = dict(scope="PS numerics + real driver + synthetic MMIO, NOT HLS/RTL/board/performance",
                   started=datetime.now().astimezone().isoformat(), commands=[], result="RUNNING",
                   inputs=[dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)) for p in inputs])

    def run(name, argv, required=None):
        start = time.monotonic()
        log = out / (name + ".txt")
        with log.open("wb") as f:
            try:
                code = subprocess.run(list(map(str, argv)), cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                      timeout=120).returncode
            except subprocess.TimeoutExpired:
                code = -1
        text = log.read_text(encoding="utf-8", errors="replace")
        ok = code == 0 and (required is None or required in text)
        receipt["commands"].append(dict(name=name, argv=list(map(str, argv)), exit=code, passed=ok,
                                        seconds=round(time.monotonic()-start, 3), log=log.name, sha256=sha(log)))
        (out / "manifest.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
        print(name, "PASS" if ok else "FAIL", flush=True)
        if not ok:
            print(text[-6000:])
            raise RuntimeError(name)

    try:
        run("compiler", [args.cxx, "--version"])
        inc = ["-I", ROOT / "src/ps", "-I", ROOT / "src/hls", "-I", ROOT / "sim/host/xil_stubs"]
        common = ["-std=c++14", "-Wall", "-Wextra", "-Werror", "-ffp-contract=off"]
        run("roi_syntax", [args.cxx, *common, *inc, "-fsyntax-only", ROOT / "src/ps/system/m3a_roi.cpp"])
        binary = out / "test_m3a_roi.exe"
        run("compile", [args.cxx, *common, "-O2", "-ffunction-sections", "-fdata-sections", *inc,
                        *(ROOT / p for p in SOURCES), "-Wl,--gc-sections", "-Wl,--image-base=0x10000000",
                        "-Wl,--disable-dynamicbase", "-o", binary])
        for mode in MODES:
            run(mode, [binary, mode], "M3A_ROI PASS ("+mode+")")
        receipt["result"] = "PASS"
    except (RuntimeError, OSError) as exc:
        receipt["result"] = "FAIL"
        receipt["error"] = str(exc)
    finally:
        receipt["finished"] = datetime.now().astimezone().isoformat()
        (out / "manifest.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print("M3A_ROI_SUITE", receipt["result"], out, flush=True)
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
