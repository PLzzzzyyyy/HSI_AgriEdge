"""Current private runtime ownership regressions. No board, UART, sync or Build."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    out=p.parse_args().out.resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()):raise ValueError('Output must be under build/host')
    out.mkdir(parents=True,exist_ok=False);commands=[];result='FAIL'
    def run(name,args):
        args=list(map(str,args));r=subprocess.run(args,cwd=ROOT,capture_output=True,timeout=90)
        (out/(name+'.log')).write_bytes(r.stdout+r.stderr);commands.append(dict(name=name,argv=args,exit=r.returncode))
        print(name+(': PASS' if not r.returncode else ': FAIL'),flush=True)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    flags=['-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror']
    inc=['-I'+p for p in ['src/ps/s2c_roi_app','src/ps/system','src/ps','src/hls']]
    sources=['src/ps/s2c_roi_app/roi_runtime.cpp','src/ps/s2c_roi_app/roi_runtime.h',
             'src/ps/s2c_roi_app/roi_models.cpp','src/ps/s2c_roi_app/roi_models.h']
    try:
        modes=dict(task=['ok','fault','probe_fault','load_fault'],scene=['success','fail','probe_early','probe_ok','probe_class','probe_short','probe_size','probe_dma'],
                   model=['ok','load_fault','probe_input_fail','probe_load_fault','probe_run_fault','attention','attention_header_fault','attention_restore_fault'])
        for kind,tests in modes.items():
            test=f'sim/host/test_gcs_{kind}_runtime.cpp';sources.append(test)
            run(kind+'_compile',['D:/mingw64/bin/g++.exe',*flags,*inc,test,sources[0],sources[2],'-o',out/(kind+'.exe')])
            for test in tests:run(kind+'_'+test,[out/(kind+'.exe'),test])
        target='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
        bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
        run('a53_runtime',[target,*flags,*inc,'-mcpu=cortex-a53','-fsyntax-only','-I'+str(bsp),sources[0]])
        result='PASS'
    finally:
        sources.append('tools/check_gcs_runtime.py')
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='OFFLINE_SCHEDULER_STUBS_AND_A53_SYNTAX_NOT_BOARD_OR_NUMERIC_ACCEPTANCE',
            commands=commands,sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}),indent=2),encoding='utf-8')

if __name__=='__main__':main()
