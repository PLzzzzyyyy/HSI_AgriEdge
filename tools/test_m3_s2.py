"""Compile/test the actual S2 C++ candidate; no hardware synthesis/build."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from m3_s1_candidate import load_engine
ROOT=Path(__file__).resolve().parents[1]
SOURCES=['src/hls/m3_s2/s2_engine.cpp','src/hls/m3_s2/s2_projection.cpp',
         'src/hls/m3_s2/s2_exp.cpp','src/hls/m3_math/s2_math.cpp','sim/hls_tb/tb_m3_s2.cpp']
CONFIGS=[('native8p1_pack',8,1,1,1,'stress'),('native8p2_pack',8,2,1,1,'stress'),
         ('native8p2_plain',8,2,0,1,'stress'),('native16p1_plain',16,1,0,1,'stress'),
         ('native16p2_plain',16,2,0,1,'stress'),('apint8p2_pack',8,2,1,0,'full'),
         ('apint8p2_plain',8,2,0,0,'full'),('apint16p2_plain',16,2,0,0,'full')]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def vectors():
    out=ROOT/'build/host/m3_s2_vectors';out.mkdir(parents=True,exist_ok=True)
    info=[]
    for num in (8,16):
        g=ROOT/'sim/golden'/('n6_engine_i8' if num==8 else 'n6_engine')/'batch_hanchuan'
        eng=load_engine(g/'weights_engine.bin')
        wins=np.fromfile(g/'wins_i16.bin','<i2').reshape(-1,7,7,272)
        raw=np.stack([eng.entry_b(w,bfp=True) for w in wins]).astype('<i4')
        path=out/('hanchuan_'+str(num)+'_raw.bin');raw.tofile(path)
        info.append(dict(num=num,count=len(wins),output=str(path.relative_to(ROOT)),sha256=sha(path),
                         inputs={str(f.relative_to(ROOT)):sha(f) for f in [g/'weights_engine.bin',g/'wins_i16.bin',ROOT/'model/engine_ref.py',ROOT/'tools/m3_s1_candidate.py']}))
    (out/'manifest.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    return info
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=ROOT/'build/host'/datetime.now().strftime('m3_s2_host_%Y%m%d_%H%M%S'))
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    manifest=dict(scope='C++ host/native+ap_int validation, NOT RTL or board',vectors=vectors(),
                  sources={str(p.relative_to(ROOT)):sha(p) for p in list((ROOT/'src/hls/m3_s2').glob('*'))+list((ROOT/'src/hls/m3_math').glob('*'))+[ROOT/'sim/hls_tb/tb_m3_s2.cpp',Path(__file__).resolve()]},runs=[])
    def save(): (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    def run(label,cmd,want=0,marker=None):
        t=time.monotonic();log=out/(label+'.txt')
        with log.open('wb') as f:
            proc=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=600)
        text=log.read_text(encoding='utf-8',errors='replace')
        ok=proc.returncode==want and (marker is None or marker in text)
        manifest['runs'].append(dict(name=label,argv=list(map(str,cmd)),exit=proc.returncode,passed=ok,
            log=log.name,sha256=sha(log),seconds=round(time.monotonic()-t,3)))
        save();print(label,'PASS' if ok else 'FAIL',flush=True)
        if not ok: print(text[-5000:]);raise SystemExit(1)
    compiler='D:/mingw64/bin/g++.exe'
    def compile(label,num,p,pack,native,fault=0):
        exe=out/(label+'.exe')
        cmd=[compiler,'-O2','-std=c++14','-ffp-contract=off','-Wall','-Wextra','-Wno-unknown-pragmas',
             '-DS2_NUM='+str(num),'-DS2_P='+str(p),'-DS2_PACK='+str(pack),'-DS2_NATIVE='+str(native),'-DS2_FAULT='+str(fault),
             '-I',ROOT/'src/hls/m3_s2','-I','D:/xilinx/Vitis_HLS/2020.2/include',*[ROOT/f for f in SOURCES],'-o',exe]
        run(label+'_compile',cmd);return exe
    for label,num,p,pack,native,mode in CONFIGS:
        exe=compile(label,num,p,pack,native)
        run(label+'_load',[exe,'load'],marker='S2_TEST_PASS mode=load')
        run(label,[exe,mode],marker='S2_TEST_PASS')
        if label in ('native8p1_pack','native8p2_pack','apint8p2_pack'):
            run(label+'_budget',[exe,'budget'],marker='S2_TEST_PASS mode=budget')
    for fault in (1,2,3):
        label='negative_'+str(fault);exe=compile(label,8,2,1,1,fault)
        run(label,[exe,'drain' if fault==3 else 'smoke'],want=90,marker='S2_INVARIANT')
    manifest['passed']=True;save();(out/'all.done').write_text('S2_HOST_ALL_PASS\n',encoding='utf-8')
    return 0
if __name__=='__main__':sys.exit(main())
