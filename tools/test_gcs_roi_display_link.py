"""Compile/run the pure CPU canvas checks, never Vitis or a connected board.

Run: python tools/test_gcs_roi_display_link.py [--cxx PATH_TO_G++]
The temporary host executable is removed automatically.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cxx", default=shutil.which("g++") or "C:/msys64/mingw64/bin/g++.exe")
args = parser.parse_args()
source = ROOT / "src/ps/s2c_roi_app"
with tempfile.TemporaryDirectory(prefix=".gcs_canvas_check_", dir=ROOT) as temp:
    # Keep compiler outputs and automatic cleanup inside the verified workspace.
    assert Path(temp).resolve().parent == ROOT.resolve()
    exe = Path(temp) / ("canvas_check.exe" if os.name == "nt" else "canvas_check")
    subprocess.run([
        args.cxx, "-std=c++14", "-O2", "-Wall", "-Wextra", "-Werror", "-ffp-contract=off",
        "-I" + str(source), str(ROOT / "tools/tests/test_gcs_roi_display_link.cpp"),
        str(source / "roi_canvas.cpp"), str(source / "roi_models.cpp"), "-o", str(exe)
    ], check=True, cwd=ROOT, timeout=120)
    env = os.environ.copy()
    env["PATH"] = str(Path(shutil.which(args.cxx) or args.cxx).resolve().parent) + os.pathsep + env.get("PATH", "")
    subprocess.run([str(exe)], check=True, cwd=ROOT, env=env, timeout=60)
print("PASS: CPU canvas only; no target build or hardware access")
