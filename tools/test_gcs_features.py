"""One offline delta-check entry. No Vitis Build, board, serial or UDP actions."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'report/gcs_roi/20261010_full_feature'/datetime.now().strftime('checks_%H%M%S_%f')
    out.mkdir(parents=True)
    commands=[]
    def run(name,args):
        p=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,timeout=180)
        (out/(name+'.log')).write_bytes(p.stdout+p.stderr)
        commands.append(dict(name=name,argv=list(map(str,args)),exit=p.returncode))
        print(f'{name}: {"PASS" if p.returncode==0 else "FAIL"}',flush=True)
        if p.returncode:raise RuntimeError(f'{name}: see {out/(name+".log")}')
    result='FAIL'
    try:
        run('s3_driver_delta',[sys.executable,'-B',ROOT/'tools/test_m3a_wait_service.py'])
        run('cpp_runtime_protocol_target_syntax',[sys.executable,'-B',ROOT/'tools/test_gcs_scene.py'])
        for name in ('test_gcs_roi','test_gcs_roi_server','test_gcs_probe','test_gcs_uart','test_gcs_scene_verify','test_gcs_board_batch'):
            run(name,[sys.executable,'-B',ROOT/f'sim/host/{name}.py'])
        for name in ('board','core','app','uart'):
            run('js_'+name,['node','--check',ROOT/f'gcs/web/{name}.js'])
        run('js_legacy_observer',['node','--check',ROOT/'tools/check_gcs_roi.cjs'])
        package=os.environ.get('PLAYWRIGHT_PACKAGE',str(Path.home()/'AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright'))
        if not Path(package).is_dir():raise RuntimeError('Set PLAYWRIGHT_PACKAGE to an already installed package; no auto-install')
        run('offline_browser',['node',ROOT/'tools/check_gcs_scene.cjs',package,out/'browser'])
        result='PASS'
    except Exception as exc:
        print(str(exc),file=sys.stderr)
    finally:
        paths=list((ROOT/'gcs').glob('board_*.py'))+[ROOT/'gcs/uart_capture.py',ROOT/'gcs/server.py']
        paths+=list((ROOT/'src/ps/s2c_roi_app').glob('roi_*.cpp'))
        paths+=[ROOT/p for p in ('src/ps/tt_m3a.cpp','src/ps/tt_m3a.h','src/ps/s2c_roi_app/main.cpp','src/ps/s2c_roi_app/roi_protocol.h',
            'tools/gcs_board_batch.py','tools/gcs_scene_verify.py','tools/gcs_probe_verify.py')]
        paths+=[ROOT/f'gcs/web/{name}' for name in ('app.js','board.js','core.js','uart.js','index.html')]
        sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='OFFLINE_DELTA_ONLY_NOT_BUILD_OR_BOARD_ACCEPTANCE',commands=commands,sources=sources),indent=2),encoding='utf-8')
        print(out)
    return 0 if result=='PASS' else 1


if __name__=='__main__':sys.exit(main())
