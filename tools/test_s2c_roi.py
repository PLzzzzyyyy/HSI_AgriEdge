#!/usr/bin/env python3
"""New integration checks only. No Vitis Build, device access or live UDP."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / "build/host" / datetime.now().strftime("s2c_checks_%Y%m%d_%H%M%S_%f")
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(scope="NEW_INTEGRATION_HOST_AND_SYNTAX_ONLY", result="RUNNING", commands=[],
                    old_baselines="NOT_RERUN", target_build="NOT_RUN", board="NOT_RUN")
    def run(name, args):
        args = [str(a) for a in args]
        p = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        log = out / (name + ".log"); log.write_bytes(p.stdout)
        manifest["commands"].append(dict(name=name, argv=args, exit=p.returncode,
            log=log.name, sha256=hashlib.sha256(p.stdout).hexdigest()))
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if p.returncode: raise RuntimeError(name + ": " + p.stdout.decode(errors="replace"))
    try:
        host = Path("D:/mingw64/bin/g++.exe")
        private = ROOT / "src/ps/s2c_roi_app"
        common = [host,"-std=c++14","-O2","-ffp-contract=off","-Wall","-Wextra","-Werror","-I"+str(private)]
        run("protocol_compile", common + [ROOT/"sim/host/test_s2c_protocol.cpp", private/"roi_protocol.cpp",private/"roi_models.cpp", "-o",out/"protocol.exe"])
        run("protocol_test", [out/"protocol.exe"])
        run("runtime_compile",common + ["-I"+str(ROOT/"src/ps/system"),"-I"+str(ROOT/"src/ps"),"-I"+str(ROOT/"src/hls"),
            ROOT/"sim/host/test_s2c_runtime.cpp",private/"roi_runtime.cpp",private/"roi_models.cpp","-o",out/"runtime.exe"])
        for case in ("success","sd","load","roi"): run("runtime_"+case,[out/"runtime.exe",case])
        run("client_tests",[sys.executable,"-B",ROOT/"sim/host/test_s2c_client.py","-v"])
        target = Path("D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe")
        bsp = ROOT/"vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include"
        target_args = [target,"-fsyntax-only","-std=c++14","-O2","-mcpu=cortex-a53","-ffp-contract=off",
                       "-ffunction-sections","-fdata-sections","-Wall","-Wextra","-Werror"]
        for include in (private,bsp,ROOT/"src/ps/s2b_idle_app",ROOT/"src/ps/system",ROOT/"src/ps",ROOT/"src/hls"):
            target_args += ["-I"+str(include)]
        for name in ("main","roi_runtime","roi_protocol"):
            run("target_syntax_"+name,target_args+[private/(name+".cpp")])
        manifest["result"]="PASS"
    except Exception as exc:
        manifest["result"]="FAIL"; manifest["error"]=str(exc)
        raise
    finally:
        (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print(out)


if __name__ == "__main__": main()
