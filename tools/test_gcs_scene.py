"""Full scene delta checks only, not target Build or device execution."""
from pathlib import Path
from datetime import datetime
import subprocess,json,sys
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'report/gcs_roi/20261010_full_scene'/datetime.now().strftime('checks_%H%M%S')
out.mkdir(parents=True,exist_ok=False)
build=ROOT/'build/host/gcs_scene';build.mkdir(parents=True,exist_ok=True)
p=ROOT/'src/ps/s2c_roi_app';inc=[p,ROOT/'src/ps/system',ROOT/'src/ps',ROOT/'src/hls']
base=['-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror']+['-I'+str(i) for i in inc]
commands=[];result='FAIL'
def run(name,args):
    cmd=list(map(str,args));r=subprocess.run(cmd,cwd=ROOT,capture_output=True,timeout=120)
    (out/(name+'.log')).write_bytes(r.stdout+r.stderr);commands.append(dict(name=name,argv=cmd,exit=r.returncode))
    if r.returncode:raise RuntimeError(name+': '+(r.stdout+r.stderr).decode(errors='replace'))
    print(name+': PASS')
try:
    host='D:/mingw64/bin/g++.exe'
    for n,extra in [('runtime',[p/'roi_runtime.cpp']),('protocol',[p/'roi_protocol.cpp'])]:
        run(n+'_compile',[host,*base,ROOT/f'sim/host/test_gcs_scene_{n}.cpp',*extra,p/'roi_models.cpp','-o',build/(n+'.exe')])
    run('runtime_success',[build/'runtime.exe','success']);run('runtime_failure',[build/'runtime.exe','fail']);run('protocol',[build/'protocol.exe'])
    for case in ('probe_early','probe_ok','probe_class','probe_short','probe_size','probe_dma'):
        run(case,[build/'runtime.exe',case])
    run('pc_receiver',[sys.executable,'-B',ROOT/'sim/host/test_gcs_scene.py'])
    target='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
    bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
    for n in ('main','roi_runtime','roi_protocol','roi_display'):
        run('syntax_'+n,[target,*base,'-mcpu=cortex-a53','-fsyntax-only','-I'+str(bsp),'-I'+str(ROOT/'src/ps/s2b_idle_app'),p/(n+'.cpp')])
    result='PASS'
finally:
    (out/'checks.json').write_text(json.dumps(dict(result=result,scope='FULL_SCENE_DELTA_HOST_AND_SYNTAX_ONLY',commands=commands),indent=2),encoding='utf-8');print(out)
