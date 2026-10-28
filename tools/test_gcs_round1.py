"""ABI4 offline gates. No App Build, device or production server.

A53 checks use the installed standalone BSP only for syntax; they are not an
ELF link or board acceptance. The all group also runs the existing private
protocol/runtime/interop and headless browser fixtures, on fresh output only.
"""
from pathlib import Path
from datetime import datetime
import argparse,ast,hashlib,json,subprocess,sys,time
from gcs_release import SOURCES

ROOT=Path(__file__).resolve().parents[1]
TESTS=('board_log','network_records','network_verifiers','network_owner','network_lifecycle','network_http','model_link','boot_discovery','boot_http','boot_tools','sd_identity','uart','engine_timing','attention','timing','roi_server','release','hardware_gate')
A53=tuple(p for p in SOURCES if p.endswith('.cpp'))
BSP=ROOT/'build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_plat/export/gcs_r1_abi4_plat/sw/gcs_r1_abi4_plat/standalone_domain/bspinclude/include'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--group',choices=('incremental','python','cpp','a53','browser','all'),default='all')
    p.add_argument('--bsp',type=Path,default=BSP,help='Read-only installed BSP include directory; no build')
    p.add_argument('--playwright',type=Path,default=Path.home()/'AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright')
    a=p.parse_args()
    out=a.out.resolve()
    if out==ROOT/'build/host' or not out.is_relative_to(ROOT/'build/host'):p.error('New build/host output required')
    out.mkdir(parents=True,exist_ok=False)
    receipt=dict(scope='OFFLINE_CANDIDATE_ONLY_NOT_APP_BUILD_OR_BOARD_ACCEPTANCE',started=datetime.now().isoformat(),commands=[],sources=[])
    inputs={Path(__file__).resolve()}
    for base,patterns in [('gcs',('*.py','web/*.js','web/*.html')),('src/ps',('*.h','*.cpp','s2c_roi_app/*','system/*.h','system/*.cpp')),
                          ('sim/host',('test_gcs_*','gcs_model_peer.cpp','gcs_model_stubs/*','xil_stubs/*')),
                          ('tools',('test_gcs_*.py','gcs_*.py','check_gcs_*.py','check_gcs_*.cjs')),
                          ('src/hls',('tt_engine_regs.h',))]:
        for pattern in patterns:inputs.update(f for f in (ROOT/base).glob(pattern) if f.is_file())
    for f in sorted(inputs):receipt['sources'].append(dict(path=f.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
    def save():(out/'checks.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    def run(name,argv,timeout=180):
        argv=list(map(str,argv));start=time.monotonic();log=out/(name+'.log')
        with log.open('wb') as f:
            try:code=subprocess.run(argv,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout).returncode
            except (OSError,subprocess.TimeoutExpired) as exc:f.write(str(exc).encode('utf-8'));code=-1
        receipt['commands'].append(dict(name=name,argv=argv,exit=code,seconds=round(time.monotonic()-start,3),log=log.name,sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        save();print(name,'PASS' if not code else 'FAIL',flush=True)
        if code:print(log.read_text(encoding='utf-8',errors='replace')[-5000:],flush=True)
        return code==0
    if a.group in ('incremental','python','all'):
        tests=TESTS if a.group=='incremental' else tuple(p.stem.removeprefix('test_gcs_') for p in sorted((ROOT/'sim/host').glob('test_gcs_*.py')) if p.stem!='test_gcs_model_interop')
        # This suite requires its compiled pipe peer; do not report skipped
        # interop tests as a passing Python gate.
        receipt['python_modules']=list(tests)
        if a.group!='incremental':receipt['python_deferred_to_cpp']=['model_interop']
        for test in tests:run(test,[sys.executable,'-X','utf8','-u','-B','-m','unittest','-v',f'sim.host.test_gcs_{test}'])
    if a.group in ('cpp','all'):
        run('private_models',[sys.executable,'-X','utf8','-B',ROOT/'tools/test_gcs_models.py','--out',out/'models'],timeout=600)
        run('private_interop',[sys.executable,'-X','utf8','-B',ROOT/'tools/test_gcs_interop.py','--out',out/'interop'],timeout=240)
        app=ROOT/'src/ps/s2c_roi_app';model=app/'roi_models.cpp';protocol=app/'roi_protocol.cpp'
        stubs=ROOT/'sim/host/gcs_model_stubs';ram=stubs/'ram_fs.cpp'
        flags=['-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror']
        includes=['-I'+str(ROOT/d) for d in ('src/ps/s2c_roi_app','src/ps/system','src/ps','src/hls','sim/host/gcs_model_stubs')]
        tests=[('board_log',[protocol,model],[[]]),('attention_protocol',[protocol,model],[[out]]),
               ('boot',[app/'roi_boot_id.cpp'],[[]]),
               ('boot_sd',[app/'roi_boot_id.cpp',app/'roi_boot_sd.cpp',ram],[[m] for m in
                   ('ok','missing','corrupt','mount','unmount','open','read','short_read','write','short_write','sync','close','write_close','readback')]),
               ('measure',[],[[]]),('release_layout',[],[[]]),('roi_prefix',[app/'roi_runtime.cpp',model],[[]])]
        for name,extra,cases in tests:
            exe=out/(name+'.exe')
            if run(name+'_compile',['D:/mingw64/bin/g++.exe',*flags,*includes,ROOT/f'sim/host/test_gcs_{name}.cpp',*extra,'-o',exe]):
                for n,args in enumerate(cases):run(name+'_run_'+str(n),[exe,*args])
    if a.group in ('a53','all'):
        compiler='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
        flags=['-std=c++11','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror','-mcpu=cortex-a53','-fsyntax-only']
        includes=['-I'+str(ROOT/d) for d in ('src/ps/s2c_roi_app','src/ps/s2b_idle_app','src/ps/system','src/ps','src/hls')]+['-I'+str(a.bsp.resolve())]
        receipt['a53_bsp']=str(a.bsp.resolve())
        for src in A53:run('a53_'+Path(src).stem,[compiler,*flags,*includes,ROOT/src])
    if a.group in ('browser','all'):
        for src in sorted((ROOT/'gcs/web').glob('*.js'))+sorted((ROOT/'tools').glob('check_gcs_*.cjs')):
            run('syntax_'+src.stem,['node','--check',src])
        run('browser',['node',ROOT/'tools/check_gcs_scene.cjs',a.playwright,out/'browser'])
    receipt['ast']=[]
    for src in sorted(p for p in inputs if p.suffix=='.py'):
        try:ast.parse(src.read_text(encoding='utf-8-sig'));error=None
        except (SyntaxError,UnicodeError) as exc:error=str(exc)
        receipt['ast'].append(dict(path=src.relative_to(ROOT).as_posix(),error=error))
    receipt.update(finished=datetime.now().isoformat(),result='FAIL' if any(c['exit'] for c in receipt['commands']) or any(r['error'] for r in receipt['ast']) else 'PASS');save()
    return int(receipt['result']!='PASS')
if __name__=='__main__':sys.exit(main())
