"""Focused metrics/DP checks. No board Build, sync, serial, UDP or model inference."""
import argparse
from pathlib import Path
import subprocess
import sys
import json

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    commands=[];result='FAIL'
    def run(name,argv):
        argv=list(map(str,argv));p=subprocess.run(argv,capture_output=True,cwd=ROOT,timeout=120)
        (out/(name+'.log')).write_bytes(p.stdout+p.stderr);commands.append(dict(name=name,argv=argv,exit=p.returncode))
        if p.returncode:raise RuntimeError(name+': '+(p.stdout+p.stderr).decode(errors='replace')[-2500:])
        print(name+': PASS')
    try:
        inc=['-Isrc/ps/s2c_roi_app','-Isrc/ps/system','-Isrc/ps','-Isrc/hls']
        base=['-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror',*inc]
        for name in ('scene','roi'):
            run(name+'_canvas_compile',['D:/mingw64/bin/g++.exe',*base,f'sim/host/test_gcs_{name}_canvas.cpp',
                'src/ps/s2c_roi_app/roi_canvas.cpp','src/ps/s2c_roi_app/roi_models.cpp','-o',out/(name+'.exe')])
            run(name+'_canvas',[out/(name+'.exe')])
        target='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
        bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
        for name in ('main','roi_canvas','roi_display'):
            run('a53_syntax_'+name,[target,*base,'-mcpu=cortex-a53','-fsyntax-only','-I'+str(bsp),'-Isrc/ps/s2b_idle_app',
                'src/ps/s2c_roi_app/'+name+'.cpp'])
        for name in ('test_gcs_board_metrics','test_gcs_roi_server'):
            run(name,[sys.executable,'-B','sim/host/'+name+'.py'])
        for name in ('app','board','panels','panels2'):
            run('syntax_'+name,['node','--check','gcs/web/'+name+'.js'])
        result='PASS'
    finally:
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='HOST_AND_BSP_SYNTAX_NOT_BOARD_BUILD',commands=commands),indent=2),encoding='utf-8')


if __name__=='__main__':main()
