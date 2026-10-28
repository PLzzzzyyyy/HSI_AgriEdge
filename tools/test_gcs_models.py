"""Offline private-App model checks; NO service, socket, SD device, sync or Build.

PASS here is not GCS upload integration, real numeric inference, SD persistence,
activation, hardware/DP acceptance, or completion of group D / first release.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path)
    out=(parser.parse_args().out or ROOT/'build/host/gcs_models_checks'/datetime.now().strftime('%Y%m%d_%H%M%S')).resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()):raise ValueError('Output must be below build/host')
    out.mkdir(parents=True,exist_ok=False);commands=[];result='FAIL'
    def run(name,cmd):
        cmd=list(map(str,cmd));p=subprocess.run(cmd,cwd=ROOT,capture_output=True,timeout=180)
        (out/(name+'.log')).write_bytes(p.stdout+p.stderr);commands.append(dict(name=name,argv=cmd,exit=p.returncode))
        print(name+(': PASS' if not p.returncode else ': FAIL'),flush=True)
        if p.returncode:raise RuntimeError(name+': '+(p.stdout+p.stderr).decode(errors='replace')[-3000:])
    flags=['-std=c++14','-O2','-ffp-contract=off','-Wall','-Wextra','-Werror']
    inc=['-I'+str(ROOT/p) for p in ['src/ps/s2c_roi_app','src/ps/system','src/ps','src/hls']]
    app=ROOT/'src/ps/s2c_roi_app';model=app/'roi_models.cpp'
    try:
        run('host_compiler',['D:/mingw64/bin/g++.exe','--version'])
        tests=[('phase_timing','test_gcs_phase_timing',[]),('model_store','test_gcs_model_store',[]),('model_sd','test_gcs_model_sd',[app/'roi_model_sd.cpp',ROOT/'sim/host/gcs_model_stubs/ram_fs.cpp']),
               ('model_protocol','test_gcs_model_protocol',[app/'roi_protocol.cpp']),
               ('task_protocol','test_gcs_task_protocol',[app/'roi_protocol.cpp']),
               ('legacy_protocol','test_s2c_protocol',[app/'roi_protocol.cpp']),
               ('scene_protocol','test_gcs_scene_protocol',[app/'roi_protocol.cpp']),
               ('model_canvas','test_gcs_model_canvas',[app/'roi_canvas.cpp']),
               ('scene_canvas','test_gcs_scene_canvas',[app/'roi_canvas.cpp']),
               ('legacy_canvas','test_gcs_roi_canvas',[app/'roi_canvas.cpp'])]
        for name,test,extra in tests:
            run(name+'_compile',['D:/mingw64/bin/g++.exe',*flags,*inc,'-I'+str(ROOT/'sim/host/gcs_model_stubs'),ROOT/f'sim/host/{test}.cpp',model,*extra,'-o',out/(name+'.exe')])
            args=[out] if name=='model_canvas' else [ROOT/'data/scenes/longkou/cube_f32.bin'] if name=='model_sd' else []
            run(name,[out/(name+'.exe'),*args])
        run('runtime',[sys.executable,'-B',ROOT/'tools/check_gcs_runtime.py','--out',out/'runtime'])
        run('wait_service_compile',['D:/mingw64/bin/g++.exe',*flags,*inc,'-I'+str(ROOT/'sim/host/xil_stubs'),
            ROOT/'sim/host/test_m3a_wait_service.cpp',ROOT/'src/ps/tt_m3a.cpp',app/'roi_protocol.cpp',model,
            '-Wl,--image-base=0x10000000','-Wl,--disable-dynamicbase','-o',out/'wait_service.exe'])
        for mode in ['disabled','enabled','immediate','timeout','contract']:run('wait_service_'+mode,[out/'wait_service.exe',mode])
        run('python_models',[sys.executable,'-B','-m','unittest','sim.host.test_gcs_models','-v'])
        # Newly implemented C++ validation must also agree on the actual local
        # paired exports, not only zero/small synthetic fixtures. No inference.
        sys.path.insert(0,str(ROOT/'gcs'));import board_models as models
        actual=[];required={('longkou','v2'),('honghu','v1'),('hanchuan','v1')};available=set()
        for scene in models.SCENES:
            for engine in sorted((ROOT/'data/scenes'/scene/'weights').glob('*/weights_engine.bin')):
                tag=engine.parent.name
                if tag.startswith('.'):continue # aborted exporter staging is not a model tag
                try:
                    candidate=models.load_candidate(ROOT/'data/scenes',scene,tag);candidate['available']=True;available.add((scene,tag))
                except (OSError,KeyError,TypeError,ValueError) as exc:
                    candidate=dict(scene=scene,tag=tag,available=False,error=str(exc),board_registered=False,board_persisted=None,board_activated=None)
                raw=engine.read_bytes()
                if len(raw)!=models.ENGINE_BYTES:
                    candidate['pair_validation']='NOT_APPLICABLE_TO_CURRENT_INT16_ENGINE';actual.append(candidate);continue
                # Legacy LongKou/v1 has an int16 engine but incomplete package
                # SHA provenance. Pair structure may be checked independently;
                # that MUST NOT turn it into an upload-qualified candidate.
                parts=(b''.join((engine.parent/n).read_bytes() for n,_ in models.part_files(scene)),raw)
                files=[]
                for i,data in enumerate(parts):
                    path=out/f'{scene}_{tag}_kind{i}.bin';path.write_bytes(data);files.append(path)
                run('pair_'+scene+'_'+tag,[out/'model_store.exe',models.scene_spec(scene)['id'],*files])
                candidate['pair_validation']='LOCAL_CPP_PAIR_PASS_NOT_BOARD_OR_PROVENANCE';actual.append(candidate)
        (out/'local_pairs.json').write_text(json.dumps(actual,indent=2),encoding='utf-8')
        if not required<=available:raise ValueError('Required registered three-scene local candidates missing: '+str(required-available))
        target='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-g++.exe'
        bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
        run('target_compiler',[target,'--version'])
        # Actual user App language is C++11. This remains syntax-only; no App
        # link, ELF, BSP rebuild, Vitis project mutation, deployment or board.
        for name in ['main','roi_protocol','roi_runtime','roi_models','roi_model_sd','roi_canvas','roi_display']:
            run('a53_'+name,[target,'-std=c++11',*flags[1:],*inc,'-mcpu=cortex-a53','-fsyntax-only','-I'+str(bsp),'-I'+str(ROOT/'src/ps/s2b_idle_app'),app/(name+'.cpp')])
        from PIL import Image,ImageDraw,ImageFont
        font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',24)
        for scene in models.SCENES:
            im=Image.open(out/(scene+'.ppm'));draw=ImageDraw.Draw(im)
            draw.rectangle((0,1048,1920,1079),fill='#351019')
            draw.text((12,1050),'OFFLINE SYNTHETIC FIXTURE - class map/counts/timing are test data; NOT DP BOARD ACCEPTANCE',font=font,fill='white')
            im.save(out/(scene+'.png'))
        result='PASS'
    finally:
        sources=[*app.glob('*.cpp'),*app.glob('*.h'),*ROOT.glob('sim/host/test_gcs_model*'),
                 ROOT/'sim/host/test_gcs_phase_timing.cpp',
                 *ROOT.glob('sim/host/gcs_model_stubs/*'),ROOT/'tools/check_gcs_runtime.py',Path(__file__).resolve(),
                 ROOT/'gcs/board_models.py',ROOT/'tools/generate_gcs_dp_labels.py']
        hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
        (out/'checks.json').write_text(json.dumps(dict(result=result,scope='PRIVATE_APP_HOST_FIXTURES_LOCAL_FILES_AND_A53_SYNTAX_ONLY_NOT_GCS_OR_BOARD_ACCEPTANCE',
            commands=commands,sources=hashes),indent=2),encoding='utf-8');print(out,flush=True)
    return 0 if result=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
