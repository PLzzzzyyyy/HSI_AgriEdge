"""Focused software regressions for the paired physical-key candidate."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime-tmp/keys_checks';OUT.mkdir(exist_ok=True)
env=dict(os.environ);env['PATH']='C:/msys64/mingw64/bin;'+env['PATH']
CXX='C:/msys64/mingw64/bin/g++.exe'
NODE='C:/Users/PLzzy/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
def main():
    commands=[]
    for name,sources in [('keys',['test_keys.cpp']),('key_protocol',['test_key_protocol.cpp','roi_protocol.cpp','roi_models.cpp']),
                         ('dp_keys',['test_dp_parcel.cpp','roi_canvas.cpp','roi_models.cpp'])]:
        src=[str(ROOT/('tools/tests' if x.startswith('test_') else 'src/ps/s2c_roi_app')/x) for x in sources]
        exe=str(OUT/(name+'.exe'))
        commands.extend([(name+'_compile',[CXX,'-std=c++14','-Wall','-Wextra','-Werror','-I'+str(ROOT/'src/ps/s2c_roi_app'),*src,'-o',exe]),(name,[exe])])
    for name in ('test_board_keys','test_key_dispatch','test_board_display','test_point_probe'):
        commands.append((name,[sys.executable,str(ROOT/'tools/tests'/(name+'.py'))]))
    commands.extend([('web_syntax',[NODE,'--check',str(ROOT/'gcs/web/app.js')]),
                     ('target_syntax',[sys.executable,str(ROOT/'tools/check_keys_target.py')])])
    results=[]
    for name,argv in commands:
        run=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,timeout=120)
        log=OUT/(name+'.log');log.write_bytes(run.stdout+run.stderr)
        results.append(dict(name=name,exit=run.returncode,log=str(log),sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(name,run.returncode,flush=True)
        (OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
        if run.returncode:print(log.read_text(errors='replace')[-4000:]);raise SystemExit(1)
    print('KEYS_SOFTWARE_CHECKS_PASS')
if __name__=='__main__':main()
