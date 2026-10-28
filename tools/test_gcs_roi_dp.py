"""Only new DP/canvas/accessor checks. No Vitis Build or device execution."""
from pathlib import Path
import subprocess,json,sys,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'report/gcs_roi/20261010_formal/dp_checks';out.mkdir(parents=True,exist_ok=True)
build=ROOT/'build/host/gcs_roi_dp';build.mkdir(parents=True,exist_ok=True)
private=ROOT/'src/ps/s2c_roi_app'
includes=[private,ROOT/'src/ps/system',ROOT/'src/ps',ROOT/'src/hls']
common=['-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror']+['-I'+str(p) for p in includes]
commands=[]
def run(name,args):
    p=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,timeout=120)
    (out/(name+'.log')).write_bytes(p.stdout+p.stderr)
    commands.append(dict(name=name,argv=list(map(str,args)),exit=p.returncode))
    if p.returncode:raise RuntimeError(name+': '+p.stderr.decode(errors='replace'))
    print(name+': PASS')
try:
    host='D:/mingw64/bin/g++.exe'
    for name,sources in [('canvas',[ROOT/'sim/host/test_gcs_roi_canvas.cpp',private/'roi_canvas.cpp']),('prefix',[ROOT/'sim/host/test_gcs_roi_prefix.cpp',private/'roi_runtime.cpp'])]:
        run(name+'_compile',[host,*common,*sources,private/'roi_models.cpp','-o',build/(name+'.exe')]);run(name,[build/(name+'.exe')])
    target='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
    bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
    for name in ('main','roi_canvas','roi_display','roi_runtime'):
        run('syntax_'+name,[target,*common,'-mcpu=cortex-a53','-fsyntax-only','-I'+str(bsp),'-I'+str(ROOT/'src/ps/s2b_idle_app'),private/(name+'.cpp')])
    result='PASS'
except Exception as exc:
    result='FAIL';print(exc);raise
finally:
    (out/'checks.json').write_text(json.dumps(dict(result=result,scope='HOST_AND_TARGET_SYNTAX_ONLY_NOT_BUILD_OR_BOARD',commands=commands),indent=2),encoding='utf-8')
