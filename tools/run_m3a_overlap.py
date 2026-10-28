"""Run one isolated overlap HLS stage; exit=0 alone is NOT success in 2020.2.

No baseline build, no Vitis workspace/board operations. Tcl owns snapshots.
Do not run another stage until this process has exited and its receipt passes.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = "tt_engine_m3_k7_overlap_v2"
BUILD = ROOT / "build/hls/optimization_build" / NAME
XSA = ROOT / "build/vivado/tt_m3a_zu5ev.xsa"
XSA_SHA = "9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("synth", "cosim", "export"))
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--hls", default="D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat")
    a = p.parse_args()
    if sha(XSA) != XSA_SHA: p.error("Serial XSA changed; stop")
    if (a.stage == "synth" and BUILD.exists()) or (BUILD / (a.stage + ".done")).exists():
        p.error("Refusing to overwrite existing build/stage")
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(stage=a.stage, candidate=NAME, cwd=str(out), started=datetime.now().isoformat(),
        runner_pid=os.getpid(), status="RUNNING", baseline_xsa_sha256=XSA_SHA,
        script_sha256=sha(ROOT/"build/hls/run_m3a_overlap.tcl"))
    def save(): (out/"run.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    env = dict(os.environ, TT_M3A_STAGE=a.stage, TT_TB_LAYERS="12")
    command = [a.hls, "-f", str(ROOT/"build/hls/run_m3a_overlap.tcl")]
    receipt["command"] = command
    save()
    with (out/"console.log").open("wb") as log:
        proc = subprocess.Popen(command,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT)
        receipt["tool_launcher_pid"] = proc.pid
        save()
        code = proc.wait()
    text = (out/"console.log").read_text(encoding="utf-8",errors="replace")
    marker = f"M3A_OVERLAP_STAGE_PASS stage={a.stage} name={NAME}"
    ok = code == 0 and marker in text and not re.search(r"(?m)^\s*(ERROR:|FATAL:)",text)
    ok = ok and (BUILD/(a.stage+".done")).is_file() and sha(XSA)==XSA_SHA
    receipt.update(exit=code, finished=datetime.now().isoformat(), status="PASS" if ok else "FAIL",
        log_sha256=sha(out/"console.log"), baseline_xsa_unchanged=sha(XSA)==XSA_SHA)
    save()
    (out/"exit_code.txt").write_text(str(code)+"\n",encoding="ascii")
    print(f"OVERLAP_{a.stage.upper()} {'PASS' if ok else 'FAIL'}: {out}",flush=True)
    print(text[-3000:])
    sys.exit(0 if ok else 1)

if __name__ == "__main__": main()
