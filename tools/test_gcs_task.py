"""Offline lifecycle verification. NEVER prepare/sync/Build/open UART/device UDP."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,subprocess,sys,os

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path)
    out=parser.parse_args().out or ROOT/'build/host/gcs_task_checks'/datetime.now().strftime('%Y%m%d_%H%M%S')
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    commands=[]
    def run(name,args):
        args=list(map(str,args));p=subprocess.run(args,cwd=ROOT,capture_output=True,timeout=240,
            env={**os.environ,'PYTHONIOENCODING':'utf-8','GCS_PHASE_ARTIFACTS':str(out/'phase_report')})
        (out/(name+'.log')).write_bytes(p.stdout+p.stderr);commands.append(dict(name=name,argv=args,exit=p.returncode))
        print(name+': '+('PASS' if not p.returncode else 'FAIL'),flush=True)
        if p.returncode:raise RuntimeError(name+'; see '+str(out/(name+'.log')))
    result='FAIL'
    try:
        run('private_model_bundle',[sys.executable,'-B',ROOT/'tools/test_gcs_models.py','--out',out/'models'])
        run('model_peer_interop',[sys.executable,'-B',ROOT/'tools/test_gcs_interop.py','--out',out/'interop'])
        run('python_tests',[sys.executable,'-B','-m','unittest','sim.host.test_gcs_task_transport','sim.host.test_gcs_task_verify','sim.host.test_gcs_agri','sim.host.test_gcs_roi_server','sim.host.test_gcs_uart','sim.host.test_gcs_board_metrics','sim.host.test_gcs_scene',
                           'sim.host.test_gcs_model_transport','sim.host.test_gcs_upload','sim.host.test_gcs_model_link','sim.host.test_gcs_model_business','sim.host.test_gcs_model_delivery','sim.host.test_gcs_data_inventory','sim.host.test_gcs_timing'])
        run('legacy_probe_tests',[sys.executable,'-B',ROOT/'sim/host/test_gcs_probe.py'])
        for name in ('app','board','core','panels','panels2','agri','map','uart','loop','timing'):
            run('js_'+name,['node','--check',ROOT/f'gcs/web/{name}.js'])
        package=Path.home()/'AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright'
        run('browser',['node',ROOT/'tools/check_gcs_scene.cjs',package,out/'browser'])
        result='PASS'
    finally:
        paths=[*Path('src/ps/s2c_roi_app').glob('roi_*'),Path('src/ps/s2c_roi_app/main.cpp'),Path('gcs/board_task.py'),Path('gcs/server.py'),Path('gcs/uart_capture.py'),*Path('gcs/web').glob('*.js'),Path('gcs/web/index.html'),Path('gcs/web/style.css'),Path('tools/check_gcs_scene.cjs'),*Path('sim/host').glob('test_gcs_task*'),Path('sim/host/test_gcs_scene_canvas.cpp'),Path('sim/host/test_gcs_uart.py'),Path('sim/host/test_gcs_roi_server.py'),Path(__file__).resolve()]
        paths += [Path(p) for p in ('gcs/board_history.py','gcs/board_metrics.py','gcs/board_agri.py','gcs/analysis.py','tools/gcs_task_verify.py','tools/check_gcs_agri.cjs','sim/host/test_gcs_agri.py')]
        paths += [Path(p) for p in ('gcs/board_models.py','gcs/board_link.py','gcs/board_upload.py','gcs/engine.py','tools/gcs_model_verify.py',
                                   'tools/check_gcs_models.cjs','tools/generate_gcs_eval_manifests.py','model/export_board_candidate.py','model/finetune_region.py')]
        paths += list(Path('sim/host').glob('test_gcs_model*.py'))+[Path('sim/host/test_gcs_upload.py')]+list(Path('gcs').glob('eval_*.json'))
        paths += [Path(p) for p in ('tools/gcs_data_inventory.py','tools/test_gcs_interop.py','sim/host/test_gcs_data_inventory.py')]
        paths += [Path(p) for p in ('gcs/board_timing.py','sim/host/test_gcs_timing.py')]
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='OFFLINE_FIXTURES_AND_A53_SYNTAX_NOT_BUILD_OR_BOARD_ACCEPTANCE',commands=commands,sources=sources),indent=2),encoding='utf-8')
        print(out)
    return 0 if result=='PASS' else 1

if __name__=='__main__':sys.exit(main())
