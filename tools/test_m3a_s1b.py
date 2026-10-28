"""Targeted S1b host suite only. No S1a rerun, BSP build, HLS/Vivado/Vitis/XSCT."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import prepare_m3a_s1b as package

ROOT=Path(__file__).resolve().parents[1]
SIMPLE=("success","mount","unmount","alias","high","overflow","shape","pad","mismatch",
        "init","load-error","load-timeout","full-error","full-timeout","app-mount")
EACH=("open","size-short","size-long","size-wide","short","read-error","close","crc","capacity","align","profile-size","header")

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path)
    ap.add_argument("--cxx",default="D:/mingw64/bin/g++.exe")
    args=ap.parse_args()
    out=(args.out or ROOT/"build/host"/datetime.now().strftime("m3a_s1b_%Y%m%d_%H%M%S")).resolve()
    out.mkdir(parents=True,exist_ok=False)
    files=[ROOT/p for p in package.SOURCES]+[ROOT/p for p in (
        "sim/host/test_m3a_s1b.cpp","sim/host/s1b_stubs/ff.h","tools/prepare_m3a_s1b.py","tools/test_m3a_s1b.py")]
    files+=list((ROOT/"sim/host/xil_stubs").glob("*.h"))
    receipt=dict(scope="S1b HOST ONLY: synthetic FatFs/MMIO + real PS/driver; not SD, PL, BSP, board or performance",
        started=datetime.now().astimezone().isoformat(),inputs=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in files],
        commands=[],result="RUNNING")
    def save():
        (out/"manifest.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    def run(name,argv,marker=None):
        log=out/(name+".txt"); start=time.monotonic()
        with log.open("wb") as f:
            try:
                code=subprocess.run(list(map(str,argv)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=120).returncode
            except subprocess.TimeoutExpired:
                code=-1
        text=log.read_text(encoding="utf-8",errors="replace")
        ok=code==0 and (marker is None or marker in text)
        receipt["commands"].append(dict(name=name,argv=list(map(str,argv)),exit=code,passed=ok,
            seconds=round(time.monotonic()-start,3),log=log.name,sha256=sha(log)))
        save(); print(name,"PASS" if ok else "FAIL",flush=True)
        if not ok:
            print(text[-7000:]); raise RuntimeError(name)
    try:
        import sys
        run("prepare",[sys.executable,ROOT/"tools/prepare_m3a_s1b.py","--out",out/"source_package"],"S1B_SOURCE_ONLY PASS")
        # Preparation never overwrites even its own prior output.
        try:
            package.prepare(out/"source_package")
        except FileExistsError:
            receipt["no_overwrite"]="PASS"
        else:
            raise RuntimeError("missing overwrite refusal")
        run("compiler",[args.cxx,"--version"])
        src=out/"source_package/app_src"
        common=["-std=c++14","-O2","-Wall","-Wextra","-Werror","-ffp-contract=off",
            "-ffunction-sections","-fdata-sections","-I",src,"-I",ROOT/"sim/host/s1b_stubs","-I",ROOT/"sim/host/xil_stubs"]
        run("app_object",[args.cxx,*common,"-Dmain=s1b_prepared_main","-c",src/"main.cpp","-o",out/"main.o"])
        binary=out/"test_m3a_s1b.exe"
        sources=[src/p for p in ("m3a_sd.cpp","m3a_app.cpp","m3a_roi.cpp","tt_net.cpp","tt_m3a.cpp","legacy_traps.cpp")]
        run("compile_link",[args.cxx,*common,ROOT/"sim/host/test_m3a_s1b.cpp",*sources,out/"main.o",
            "-Wl,--gc-sections","-Wl,--image-base=0x10000000","-Wl,--disable-dynamicbase","-o",binary])
        for mode in SIMPLE:
            run(mode,[binary,mode],"S1B PASS "+mode)
        for mode in EACH:
            for i in range(4):
                run(f"{mode}_{i}",[binary,mode,str(i)],"S1B PASS "+mode)
        receipt["result"]="PASS"
        receipt["cases"]=len(SIMPLE)+4*len(EACH)
    except (RuntimeError,OSError,ValueError) as exc:
        receipt["result"]="FAIL"; receipt["error"]=str(exc)
    finally:
        receipt["finished"]=datetime.now().astimezone().isoformat(); save()
    print("M3A_S1B_SUITE",receipt["result"],out)
    return 0 if receipt["result"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
