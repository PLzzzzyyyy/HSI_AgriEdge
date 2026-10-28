#!/usr/bin/env python3
"""Read-only new ELF/source audit. Does NOT Build, relink or execute the App."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BIN = Path("D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin")


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(elf, bundle, out):
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(result="RUNNING", scope="READ_ONLY_ELF_NOT_BOARD_ACCEPTANCE", files=[], commands=[])
    def run(name, args):
        args = list(map(str,args))
        p = subprocess.run(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        (out/(name+".txt")).write_bytes(p.stdout)
        (out/(name+".stderr")).write_bytes(p.stderr)
        manifest["commands"].append(dict(argv=args,exit=p.returncode,stdout_sha256=hashlib.sha256(p.stdout).hexdigest()))
        if p.returncode: raise RuntimeError(name+": "+p.stderr.decode(errors="replace"))
        return p.stdout.decode("utf-8",errors="replace")
    try:
        package=json.loads((bundle/"manifest.json").read_text())
        for r in package["files"]:
            p=ROOT/"vitis/s2c_roi_app/src"/Path(r["source"]).name
            if sha(p)!=r["sha256"]: raise ValueError("Build source drift: "+p.name)
            manifest["files"].append(dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)))
        # Reuse the existing proven read-only ELF64 parser, not its old result.
        base=run("elf_layout",[sys.executable,"-B",ROOT/"report/system_s2b/20261010_connected_source/user_build/audit_elf.py",elf])
        manifest["layout"]=json.loads(base)
        symbols=run("symbols",[BIN/"aarch64-none-elf-nm.exe","-S","-C","--defined-only",elf])
        records=[]
        for line in symbols.splitlines():
            m=re.match(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\S)\s+(.+)$",line)
            if m: records.append(dict(address=int(m[1],16),size=int(m[2],16),kind=m[3],name=m[4]))
        required=("s2c::run_once(","s2c::load_scene(","s2c::copy_row(","tt_m3a_sd_load(",
                  "tt_m3a_roi_run(","tt_m3a_init(","tt_m3a_load_weights(","tt_m3a_run(",
                  "tt_patch_extract(","tt_embed(")
        expects_dp=any(Path(r['source']).name=='roi_display.cpp' for r in package['files'])
        if expects_dp:
            required += ('s2c::display_init(', 's2c::display_update(', 's2c::render(', 's2c::copy_pixel(')
        manifest["required_symbols"]={p:[s for s in records if s["name"].startswith(p)] for p in required}
        if not all(manifest["required_symbols"].values()): raise ValueError("missing real inference/loading symbol")
        arrays=dict(cube=243794880,cls=10584,pos=63504,weights=480576,patch=52920,output=64,results=180)
        expects_scene=any(s['name'].startswith('s2c::step_scene(') for s in records)
        if expects_scene:arrays['results']=400*550*12
        regs=(ROOT/"src/hls/tt_engine_regs.h").read_text(encoding="utf-8")
        stride=re.search(r"#define\s+TT_ENGINE_IN_STRIDE\s+([0-9]+)",regs)
        if not stride: raise ValueError("cannot read frozen input-stride contract")
        arrays["input"]=4*int(stride[1])
        buffers=[]
        for name,size in arrays.items():
            candidates=[s for s in records if s["name"]=="s2c::(anonymous namespace)::"+name]
            if len(candidates)!=1: raise ValueError("buffer symbol missing: "+name)
            s=candidates[0]
            if s["size"]!=size or s["address"]+size>0x100000000: raise ValueError("buffer span: "+name)
            if name!="results" and s["address"]%64: raise ValueError("buffer alignment: "+name)
            buffers.append(s)
        manifest["buffers"]=buffers
        if expects_dp:
            frames=[s for s in records if s['name']=='(anonymous namespace)::g_frame']
            if len(frames)!=1: raise ValueError('missing private DP frame')
            f=frames[0]
            if f['size']!=1920*1080*4 or f['address']%256 or f['address']+f['size']>0x100000000:
                raise ValueError('DP frame span/alignment')
            if any(f['address']<b['address']+b['size'] and b['address']<f['address']+f['size'] for b in buffers):
                raise ValueError('DP frame aliases inference buffers')
            manifest['dp_frame']=f
        run("disassembly",[BIN/"aarch64-none-elf-objdump.exe","-d","-C",elf])
        manifest["elf_sha256"]=sha(elf); manifest["result"]="ELF_READ_ONLY_PASS"
        manifest["not_covered"]="Build flags/log receipt reviewed separately; board execution/stack margin/PHY/entropy not proven"
    except Exception as exc:
        manifest["result"]="FAIL"; manifest["error"]=str(exc)
        raise
    finally:
        (out/"audit.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print(out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--elf",type=Path,default=ROOT/"vitis/s2c_roi_app/Debug/s2c_roi_app.elf")
    p.add_argument("--bundle",type=Path,default=ROOT/"build/host/s2c_sources_20261010")
    p.add_argument("--out",type=Path,default=ROOT/"build/host"/datetime.now().strftime("s2c_elf_%Y%m%d_%H%M%S_%f"))
    a=p.parse_args(); audit(a.elf,a.bundle,a.out)
