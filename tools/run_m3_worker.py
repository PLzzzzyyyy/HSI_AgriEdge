"""Freeze/run worker ownership, two-read, backpressure and negative tests."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);snap=out/'snapshot'
    files=list((ROOT/'src/hls/m3_s2').glob('*'))+[ROOT/'sim/hls_tb/tb_m3_worker.cpp',Path(__file__).resolve()]
    for p in files:
        dst=snap/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    manifest=dict(scope='worker C protocol/boundaries, NOT RTL or hardware performance',sources={p.relative_to(ROOT).as_posix():sha(p) for p in files},runs=[])
    def run(label,cmd,want=0,marker=None):
        log=out/(label+'.log')
        with log.open('wb') as f:proc=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=180)
        text=log.read_text(errors='replace');ok=proc.returncode==want and (marker is None or marker in text)
        manifest['runs'].append(dict(label=label,command=list(map(str,cmd)),exit=proc.returncode,passed=ok,log=log.name,sha256=sha(log)))
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print(label,'PASS' if ok else 'FAIL',flush=True)
        if not ok:raise RuntimeError(text[-5000:])
    for num in (8,16):
        for native in (1,0):
            label=f'w{num}_native{native}';exe=out/(label+'.exe')
            run(label+'_compile',['D:/mingw64/bin/g++.exe','-O2','-std=c++14','-ffp-contract=off',f'-DS2_NUM={num}',f'-DS2_NATIVE={native}',
                '-I','D:/xilinx/Vitis_HLS/2020.2/include',snap/'sim/hls_tb/tb_m3_worker.cpp',snap/'src/hls/m3_s2/s2_projection.cpp','-o',exe])
            run(label,[exe],marker='M3_WORKER_PASS')
            for fault in ('duplicate','early_read','wrong_owner','early_release'):
                run(label+'_'+fault,[exe,fault],90,'S2_INVARIANT')
    manifest['passed']=True;(out/'manifest.json').write_text(json.dumps(manifest,indent=2));(out/'all.done').write_text('M3_WORKER_ALL_PASS\n')
if __name__=='__main__':main()
