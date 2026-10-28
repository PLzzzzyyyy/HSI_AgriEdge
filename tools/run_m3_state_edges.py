"""Frozen real-worker extreme/terminal tests, no synthesis or board access."""
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
    files=[p for d in ['src/hls/m3_s2','src/hls/m3_math'] for p in (ROOT/d).glob('*') if p.is_file()]
    files += [ROOT/'sim/hls_tb/tb_m3_state_edges.cpp',Path(__file__)]
    for p in files:
        dst=snap/p.resolve().relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    manifest=dict(scope='real-worker C boundaries, NOT RTL or full network',sources={p.resolve().relative_to(ROOT).as_posix():sha(p) for p in files},runs=[])
    def run(label,cmd,marker=None):
        log=out/(label+'.log')
        with log.open('wb') as f:
            proc=subprocess.run(list(map(str,cmd)),cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=180)
        text=log.read_text(errors='replace');ok=proc.returncode==0 and (marker is None or marker in text)
        manifest['runs'].append(dict(label=label,command=list(map(str,cmd)),exit=proc.returncode,passed=ok,log=log.name,sha256=sha(log)))
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print(label,'PASS' if ok else 'FAIL',flush=True)
        if not ok:raise RuntimeError(text[-5000:])
    for num in (8,16):
        for native in (1,0):
            label=f'w{num}_native{native}';exe=out/(label+'.exe')
            run(label+'_compile',['D:/mingw64/bin/g++.exe','-O2','-std=c++14','-ffp-contract=off',f'-DS2_NUM={num}',f'-DS2_NATIVE={native}',
                '-I','D:/xilinx/Vitis_HLS/2020.2/include',snap/'sim/hls_tb/tb_m3_state_edges.cpp',
                snap/'src/hls/m3_s2/s2_projection.cpp',snap/'src/hls/m3_s2/s2_exp.cpp',snap/'src/hls/m3_math/s2_math.cpp','-o',exe])
            run(label,[exe],'M3_STATE_EDGES_PASS')
    manifest['passed']=True;(out/'manifest.json').write_text(json.dumps(manifest,indent=2));(out/'all.done').write_text('M3_STATE_EDGES_ALL_PASS')
if __name__=='__main__':main()
