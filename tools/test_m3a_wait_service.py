"""Focused S3 driver delta checks. No Vitis Build/link or device execution."""
from datetime import datetime
import hashlib,json,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'report/gcs_roi/20261010_s3'/datetime.now().strftime('driver_%H%M%S_%f')
    out.mkdir(parents=True);build=ROOT/'build/host/m3a_wait_service';build.mkdir(exist_ok=True)
    commands=[];result='FAIL'
    def run(name,argv):
        argv=list(map(str,argv));p=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=120)
        (out/(name+'.log')).write_bytes(p.stdout+p.stderr);commands.append(dict(name=name,argv=argv,exit=p.returncode))
        if p.returncode:raise RuntimeError(name+': '+(p.stdout+p.stderr).decode(errors='replace'))
        print(name+': PASS')
    try:
        common=['-std=c++14','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
            '-I'+str(ROOT/'src/ps'),'-I'+str(ROOT/'src/hls')]
        common+=['-I'+str(ROOT/'src/ps/s2c_roi_app')]
        run('compile',['D:/mingw64/bin/g++.exe',*common,'-I'+str(ROOT/'sim/host/xil_stubs'),
            ROOT/'sim/host/test_m3a_wait_service.cpp',ROOT/'src/ps/tt_m3a.cpp',ROOT/'src/ps/s2c_roi_app/roi_protocol.cpp',
            ROOT/'src/ps/s2c_roi_app/roi_models.cpp',
            '-Wl,--image-base=0x10000000','-Wl,--disable-dynamicbase','-o',build/'test.exe'])
        for case in ('disabled','enabled','immediate','timeout','contract'):
            run(case,[build/'test.exe',case])
        bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
        run('target_syntax',['D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe',
            *common,'-mcpu=cortex-a53','-I'+str(bsp),'-fsyntax-only',ROOT/'src/ps/tt_m3a.cpp'])
        result='PASS'
    finally:
        files=['src/ps/tt_m3a.cpp','src/ps/tt_m3a.h','sim/host/test_m3a_wait_service.cpp']
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='WAIT_SERVICE_HOST_AND_TARGET_SYNTAX_ONLY',
            commands=commands,sources={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}),indent=2),encoding='utf-8')
        print(out)
if __name__=='__main__':main()
