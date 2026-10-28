"""Build/run pipe-only GCS <-> actual private C++ protocol interop.

Does not start an HTTP service, create device sockets, Build App, sync sources,
access UART/SD, execute HLS/driver, or infer scene data. Test doubles are explicit.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path)
    out=(p.parse_args().out or ROOT/'build/host/gcs_interop'/datetime.now().strftime('%Y%m%d_%H%M%S')).resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()):raise ValueError('Output must stay below build/host')
    out.mkdir(parents=True,exist_ok=False);commands=[];result='FAIL';exe=out/'model_peer.exe'
    env={**os.environ,'GCS_MODEL_PEER':str(exe),'GCS_INTEROP_OUT':str(out/'cases'),'PYTHONIOENCODING':'utf-8'}
    sources=['sim/host/gcs_model_peer.cpp','src/ps/s2c_roi_app/roi_protocol.cpp','src/ps/s2c_roi_app/roi_models.cpp',
             'src/ps/s2c_roi_app/roi_model_sd.cpp','sim/host/gcs_model_stubs/ram_fs.cpp']
    def run(name,args):
        r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=180)
        (out/(name+'.log')).write_bytes(r.stdout+r.stderr);commands.append(dict(name=name,argv=list(map(str,args)),exit=r.returncode))
        print(name+(': PASS' if r.returncode==0 else ': FAIL'),flush=True)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode('utf-8',errors='replace')[-5000:])
    try:
        run('compile',['D:/mingw64/bin/g++.exe','-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror','-Isrc/ps/s2c_roi_app','-Isim/host/gcs_model_stubs',*sources,'-o',exe])
        run('interop',[sys.executable,'-B','-m','unittest','sim.host.test_gcs_model_interop','-v'])
        result='PASS'
    finally:
        sources+=['src/ps/s2c_roi_app/roi_protocol.h','src/ps/s2c_roi_app/roi_models.h','src/ps/s2c_roi_app/roi_results.h',
                  'src/ps/s2c_roi_app/roi_model_sd.h','sim/host/gcs_model_stubs/ram_fs.h','sim/host/gcs_model_stubs/ff.h',
                  'sim/host/test_gcs_model_interop.py','sim/host/test_gcs_upload.py','tools/test_gcs_interop.py',
                  'gcs/board_link.py','gcs/board_task.py','gcs/board_upload.py','gcs/board_models.py','gcs/board_history.py',
                  'tools/gcs_task_verify.py','tools/gcs_model_verify.py']
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='OFFLINE_PIPE_PROTOCOL_MODELS_WITH_SYNTHETIC_IO_NUMERICS_NOT_BOARD_ACCEPTANCE',
            commands=commands,sources={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources}),indent=2),encoding='utf-8')
        print(out)

if __name__=='__main__':main()
