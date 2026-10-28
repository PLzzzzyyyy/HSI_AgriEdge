"""Archive S1 final host + isolated micro-HLS/OOC evidence, preserving bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from run_m3_s1_hls import CONFIGS, ROOT

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--tag',required=True)
    ap.add_argument('--tests',default='build/host/m3_s1_host/tests_r3.txt')
    args=ap.parse_args()
    out=ROOT/'report/m3_s1'
    if out.exists(): raise RuntimeError('Refusing to overwrite evidence')
    run=ROOT/'build/host'/('m3_s1_hls_'+args.tag)
    mapping=ROOT/'build/host'/('m3_s1_mapping_'+args.tag)
    assert (run/'all.done').exists() and (mapping/'all.done').exists()
    results=json.loads((run/'results.json').read_text())
    assert len(results)==len(CONFIGS) and all(r['passed'] for r in results)
    host=ROOT/'build/host/m3_s1_host/summary.json'
    assert json.loads(host.read_text())['passed']
    baseline=ROOT/'build/vivado/tt_m3a_zu5ev.xsa'
    assert sha(baseline)=='9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652'
    out.mkdir(parents=True)
    (out/'.gitattributes').write_bytes(b'* -text\n')
    def copy(src,dst):
        target=out/dst; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,target)
    copy(host,'host_summary.json'); copy(ROOT/args.tests,'host_tests.txt')
    copy(run/'results.json','hls_results.json'); copy(run/'all.done','hls_all.done')
    copy(mapping/'all.done','mapping_all.done')
    copy(ROOT/'build/host'/('m3_s1_mapping_launch_'+args.tag)/'mapping.log','mapping.log')
    sources=['src/hls/m3_s1/s1_micro.h','src/hls/m3_s1/s1_micro.cpp',
        'sim/hls_tb/tb_m3_s1.cpp','build/hls/run_m3_s1.tcl','build/hls/map_m3_s1.tcl',
        'tools/m3_s1_candidate.py','tools/test_m3_s1.py','tools/run_m3_s1_hls.py','tools/capture_m3_s1.py']
    for f in sources: copy(ROOT/f,'source/'+f)
    rtl_inputs={}
    for label,top,*_ in CONFIGS:
        name='m3_s1_'+label+'_'+args.tag
        build=ROOT/'build/hls/optimization_build'/name
        copy(run/(label+'.log'),label+'/hls.log')
        copy(run/(label+'_occupancy.txt'),label+'/occupancy.txt')
        for stage in ('csim','csynth','cosim'): copy(build/(stage+'.done'),label+'/'+stage+'.done')
        for f in (build/'snapshot').glob('*'):
            if f.is_file(): copy(f,label+'/snapshot/'+f.name)
        for suffix in ('xml','rpt'):
            copy(build/'sol/syn/report'/(top+'_csynth.'+suffix),label+'/csynth.'+suffix)
        copy(build/'sol/sim/report'/(top+'_cosim.rpt'),label+'/cosim.rpt')
        copy(build/'sol/sim/report/verilog/result.transaction.rpt',label+'/rtl_transactions.rpt')
        copy(mapping/(label+'_primitives.txt'),label+'/primitives.txt')
        copy(mapping/(label+'_utilization.rpt'),label+'/ooc_utilization.rpt')
        rtl_inputs[name]={str(f.relative_to(ROOT)).replace('\\','/'):sha(f) for f in (build/'sol/syn/verilog').glob('*.v')}
    inputs=[ROOT/'sim/golden/n6_engine_i8'/f for f in ('weights_engine.bin','cube_win_i16.bin','meta.txt')]
    for entry in ('a','b','batch_hanchuan'):
        inputs += list((ROOT/'sim/golden/n6_engine_i8'/entry).glob('*.bin'))
    inputs += [ROOT/f for f in ('sim/golden/n6_engine/weights_engine.bin','sim/golden/n6_engine/a/x_embed_i32.bin',
        'data/scenes/honghu/weights/v1_int8/weights_engine.bin','model/data/golden/patch_f32.bin',
        'model/engine_ref.py','model/export_scene.py','model/quant.py','model/fixed_point_sim.py','model/tt_model.py',
        'docs/engine_arch.md','report/accuracy_int8_pc.md','report/m3_s0/inputs.json',
        'build/hls/optimization_build/tt_engine_m3_k7/sol/sim/report/verilog/lat.rpt',
        'build/hls/optimization_build/tt_engine_m3_k7/sol/sim/verilog/tt_engine.performance.result.transaction.xml')]
    inputs += list((ROOT/'data/ckpt').glob('*_qat8_s0.pth'))
    inputs += [baseline]
    manifest=dict(schema=1,parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        scope='S1 host + microkernel HLS/RTL + micro-only Vivado OOC synthesis; NOT system implementation or board',
        tag=args.tag,source_sha256={f:sha(ROOT/f) for f in sources},
        input_sha256={str(f.relative_to(ROOT)).replace('\\','/'):sha(f) for f in inputs},
        generated_rtl_mapping_inputs=rtl_inputs,
        artifacts={str(f.relative_to(out)).replace('\\','/'):sha(f) for f in out.rglob('*') if f.is_file()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('S1_EVIDENCE_PASS',len(manifest['input_sha256']),'inputs',len(manifest['artifacts']),'artifacts')

if __name__=='__main__': main()
