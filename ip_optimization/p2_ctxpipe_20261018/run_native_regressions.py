import hashlib,json,os,subprocess
from pathlib import Path
candidate=Path(__file__).resolve().parent
project=candidate.parents[1];out=project/'.runtime-tmp'
env=dict(os.environ);env['PATH']='C:/msys64/mingw64/bin;'+env['PATH']
if not env.get('S2_ROOT'):raise SystemExit('Set S2_ROOT to the read-only golden vector project')
jobs=[(8,2,'sim/hls_tb/tb_m3_s2.cpp',['full','budget','stress','arbiter','load','drain']),
      (16,2,'sim/hls_tb/tb_m3_s2.cpp',['arbiter']),
      (8,1,'sim/hls_tb/tb_m3_s2.cpp',['arbiter']),
      (8,2,'tests/test_input_load.cpp',['']),
      (16,2,'tests/test_input_load.cpp',[''])]
records=[]
for index,(num,contexts,tb,modes) in enumerate(jobs):
    stem=out/f'p2_ctxpipe_final2_{index}';exe=stem.with_suffix('.exe')
    sources=[candidate/tb]+[candidate/'src/hls/m3_s2'/name for name in ('s2_projection.cpp','s2_exp.cpp')]+[candidate/'src/hls/m3_math/s2_math.cpp']
    if not tb.startswith('tests/'):sources+=[candidate/'src/hls/m3_s2/s2_engine.cpp']
    command=['C:/msys64/mingw64/bin/g++.exe','-O2','-std=c++14','-ffp-contract=off','-Wno-unknown-pragmas',f'-DS2_NUM={num}',f'-DS2_P={contexts}','-DS2_PACK=1','-DS2_NATIVE=1','-ID:/AMDDesignTools/2026.1/Vitis/include','-I'+str(candidate/'src/hls/m3_s2'),*map(str,sources),'-o',str(exe)]
    with Path(str(stem)+'_compile.log').open('wb') as log:subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    for mode in modes:
        path=Path(str(stem)+'_'+(mode or 'boundary')+'.log')
        with path.open('wb') as log:subprocess.run([str(exe)]+([mode] if mode else []),env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        data=path.read_bytes();assert b'S2_TEST_PASS' in data or b'INPUT_LOAD_BOUNDARY_PASS' in data
        records.append(dict(num=num,contexts=contexts,mode=mode or 'boundary',log=str(path),sha256=hashlib.sha256(data).hexdigest()))
    print('PASS',num,contexts,modes,flush=True)
inputs={str(v.relative_to(candidate)):hashlib.sha256(v.read_bytes()).hexdigest() for d in ('src','sim','tests') for v in (candidate/d).rglob('*') if v.is_file()}
(candidate/'native_verification.json').write_text(json.dumps(dict(inputs=inputs,tests=records),indent=2),encoding='utf-8')
print('Native regression complete; no hardware performance claim',flush=True)
