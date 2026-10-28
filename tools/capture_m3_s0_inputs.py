"""Read existing S0 sources/reports only; archive scalar inputs and provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'report/m3_s0/inputs.json'
SYN = ROOT/'build/hls/optimization_build/tt_engine_m3_k7/sol/syn/report'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def capture():
    inputs, sources = {}, []
    def record(path):
        sources.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path)))
    names = ['token_pipeline','copy_ob','norm_full','ta_scores','ta_ctx','res2',
             'load_x','ta_head','dump_x','store_block','mode18018','mode2','mode36']
    for name in names:
        p = SYN/(name+'_csynth.xml')
        r = ET.parse(p).getroot()
        inputs[name] = dict(latency_min=int(r.findtext('.//Best-caseLatency')),
                            latency_max=int(r.findtext('.//Worst-caseLatency')),
                            resources={e.tag:int(e.text) for e in r.find('.//AreaEstimates/Resources')})
        record(p)
    top = SYN/'tt_engine_csynth.rpt'
    record(top)
    for rel in ['src/hls/tt_engine.cpp','src/hls/tt_engine.h','src/hls/tt_attn.cpp','src/hls/tt_attn.h',
                'model/engine_ref.py','sim/hls_tb/tb_tt_engine_full.cpp',
                'board/m3/20261007_full_cosim/cycles.json',
                'board/m3/20261007_system_impl/utilization.rpt',
                'board/m3/20261007_system_impl/timing.rpt','report/perf_m3.md']:
        record(ROOT/rel)
    rtl = json.loads((ROOT/'board/m3/20261007_full_cosim/cycles.json').read_text())
    # HLS-inlined stats/softmax loop estimates from top report, not measured calls.
    cost = dict(projection=inputs['token_pipeline']['latency_min'],copy=inputs['copy_ob']['latency_min'],
                norm=inputs['norm_full']['latency_min'],scores=inputs['ta_scores']['latency_min'],
                ctx=inputs['ta_ctx']['latency_min'],res2=inputs['res2']['latency_min'],
                load=inputs['load_x']['latency_min'],head=2688,stats=480,softmax=348,store=1)
    known_layer = 4*cost['projection']+3*cost['copy']+2*(cost['norm']+cost['stats'])+cost['scores']+cost['softmax']+cost['ctx']+cost['res2']
    # An affine layer+fixed model fitted to CLASS n3 full vs n1 layers5..11.
    # No independent attribution of the residual; rounding/command pad explicit.
    layer = round((rtl['class_3patch_cycles']/3-rtl['class_layer5_11_cycles'])/5)
    per_patch = (rtl['class_3patch_cycles']-4)//3
    cost['opaque_layer'] = layer-known_layer
    cost['opaque_io'] = per_patch-12*layer-cost['load']-cost['head']-cost['store']
    result = dict(schema=1,base_commit='2cf34b2',scope='existing HLS estimates + RTL aggregate calibration; NOT new simulation',
                  hls=inputs,rtl=rtl,model_cycles=cost,
                  calibration=dict(known_layer_cycles=known_layer,affine_layer_cycles=layer,
                                   transaction_pad_cycles=4,per_patch_cycles=per_patch,
                                   fitted=['CLASS full n3','CLASS layer5..11 n1'],
                                   caution='Residual service unit/location unknown; fit is not stage validation'),
                  board=dict(preembed_n16_class_ms=3.394514,with_embed_n16_class_ms=3.626181,
                             single_logits_with_embed_ms=3.628719),sources=sources)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(OUT)

def verify():
    data = json.loads(OUT.read_text())
    bad = [s['path'] for s in data['sources'] if not (ROOT/s['path']).exists() or sha(ROOT/s['path'])!=s['sha256']]
    if bad:
        raise SystemExit('Source mismatch/missing: '+str(bad))
    print(f"PASS {len(data['sources'])} input source hashes; no build invoked")

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify',action='store_true')
    a=p.parse_args()
    verify() if a.verify else capture()
