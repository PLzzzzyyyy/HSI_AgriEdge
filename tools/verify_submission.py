"""Read-only, standard-library evidence verification. No product imports or device access."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import math
import re

HERE = Path(__file__).resolve().parents[1] / 'report'

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def close(a, b):
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)

def main():
    import re
    required={'src','sim','build','board','data','skill','report'}
    require(all((HERE.parent/p).is_dir() for p in required), 'Required directories')
    require(all(re.fullmatch('[a-z0-9_.-]+',p.name) for p in HERE.parent.rglob('*') if '.git' not in p.relative_to(HERE.parent).parts), 'Lowercase English filenames')
    manifest = json.loads((HERE.parent/'package_manifest.json').read_text('utf-8'))
    for item in manifest['files']:
        path = HERE.parent/item['path']
        require(path.is_file(), 'Missing: '+item['path'])
        require(path.stat().st_size == item['bytes'], 'Size: '+item['path'])
        require(hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], 'SHA256: '+item['path'])
    evidence = json.loads((HERE/'evidence_manifest.json').read_text('utf-8'))
    for item in evidence['files']:
        path=HERE/item['path'].lower()
        require(hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'], 'Evidence mismatch: '+item['path'])

    class Result(C.LittleEndianStructure):
        _fields_=[(name,C.c_uint32) for name in ('magic','version','status','stage','runs','warmup','ps_hz','pl_hz')]+[
            ('timer_hz',C.c_uint64),('ticks',(C.c_uint64*10)*3),
            ('logits_q16',((C.c_int32*9)*11)*2),('legacy_logits',(C.c_float*9)*11),
            ('labels',(C.c_int32*11)*3),('cycles',C.c_uint32*11),
            ('exact_mismatches',C.c_uint32),('legacy_label_mismatches',C.c_uint32),
            ('legacy_max_error',C.c_float),('driver_status',C.c_int32)]
    folder=HERE/'evidence/s01_single_pixel'
    raw=(folder/'board_result.bin').read_bytes()
    require(len(raw)==C.sizeof(Result)==1664, 'Result structure')
    r=Result.from_buffer_copy(raw)
    require((r.magic,r.version,r.status,r.stage,r.runs,r.warmup)==(0x53425031,1,1,100,10,1), 'Result header/status')
    require(r.driver_status==r.exact_mismatches==r.legacy_label_mismatches==0, 'Board result errors')
    result=json.loads((folder/'results.json').read_text('utf-8'))
    means=[]
    for index,key in enumerate(['ps','matching_integer_ps','pl']):
        ticks=list(r.ticks[index]); require(all(t>0 for t in ticks), 'Invalid ticks')
        require(ticks==result[key]['raw_ticks'], 'JSON ticks mismatch')
        mean=sum(ticks)*1000/r.timer_hz/10
        require(close(mean,result[key]['mean_ms']), 'Mean mismatch '+key)
        means.append(mean)
    require(close(means[0]/means[2],result['speedup_existing_ps']), 'Main speedup')
    require(close(means[1]/means[2],result['speedup_matching_integer_ps']), 'Integer speedup')
    maximum=0
    for run in range(11):
        require(all(r.labels[mode][run]==3 for mode in range(3)), 'Class mismatch')
        for cls in range(9):
            require(r.logits_q16[0][run][cls]==r.logits_q16[1][run][cls], 'Integer logits mismatch')
            maximum=max(maximum,abs(r.legacy_logits[run][cls]-r.logits_q16[1][run][cls]/65536))
    require(maximum<=0.01 and close(maximum,result['correctness']['existing_ps_max_abs_logit_error']), 'Float logits error')
    require(hashlib.sha256((folder/'normalized_patch_f32.bin').read_bytes()).hexdigest()=='aa1ea9a584845785aec950e0b9071f57c407a9659302284bc30b10795b1e00ce','Input hash')

    # Vivado report headers can contain legacy-codepage paths; resource table labels are ASCII.
    util=(HERE/'evidence/s02_current_implementation/utilization.rpt').read_bytes().decode('latin1')
    for label,value in [('CLB LUTs',57818),('CLB Registers',70181),('Block RAM Tile',113),('URAM',20),('DSPs',620)]:
        match=re.search(r'\|\s*'+re.escape(label)+r'\s*\|\s*([\d.]+)',util)
        require(match and float(match[1])==value, 'Resource '+label)
    impl=json.loads((HERE/'evidence/s02_current_implementation/package.json').read_text('utf-8'))
    require(impl['wns']==0.447 and impl['whs']==0.005, 'Timing summary')
    deploy=json.loads((HERE/'evidence/s07_deployment/deployment.json').read_text('utf-8'))
    require(impl['bit_sha256']==deploy['files']['tt_gcs_keys.bit'], 'Bitstream pairing')
    require(impl['xsa_sha256']==deploy['files']['tt_gcs_keys.xsa'], 'XSA pairing')
    accuracy=json.loads((HERE/'evidence/s04_accuracy/fact_sources.json').read_text('utf-8'))['accuracy']
    cm=accuracy['cm']; n=sum(map(sum,cm)); correct=sum(cm[i][i] for i in range(len(cm)))
    require(n==accuracy['n']==203642 and close(correct/n,accuracy['OA']), 'OA recomputation')
    aa=sum(cm[i][i]/sum(cm[i]) for i in range(len(cm)))/len(cm)
    pe=sum(sum(cm[i])*sum(row[i] for row in cm) for i in range(len(cm)))/n**2
    kappa=(correct/n-pe)/(1-pe)
    require(close(aa,accuracy['AA']) and close(kappa,accuracy['Kappa']), 'AA / Kappa')
    require(accuracy['complete_test_coverage'] and accuracy['source']=='board', 'Accuracy scope')
    print(json.dumps({'result':'PASS','scope':'OFFLINE_RECOMPUTATION_OF_SAVED_EVIDENCE_NOT_NEW_BOARD_TEST',
        'manifest_files':len(manifest['files']),'evidence_files':len(evidence['files']),
        'ps_mean_ms':means[0],'pl_mean_ms':means[2],'speedup':means[0]/means[2],
        'maximum_logit_error':maximum,'OA':correct/n,'AA':aa,'Kappa':kappa,
        'resource_and_deployment_pairing':'PASS'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
