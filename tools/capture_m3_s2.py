"""Archive final S2 host/CSim proof. No synthesis, no changes to old evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True)
    ap.add_argument('--host-dir',type=Path)
    ap.add_argument('--out',type=Path,default=ROOT/'report/m3_s2')
    ap.add_argument('--configs',nargs='+',default=['8p1_pack','8p2_pack','8p2_plain','16p2_plain'])
    args=ap.parse_args()
    host=args.host_dir.resolve() if args.host_dir else ROOT/'build/host'/('m3_s2_host_'+args.tag)
    csim=ROOT/'build/host'/('m3_s2_csim_'+args.tag)
    hm=json.loads((host/'manifest.json').read_text())
    cm=json.loads((csim/'results.json').read_text())
    assert hm['passed'] and len(hm['runs'])==25 and all(r['passed'] for r in hm['runs'])
    assert any(r['name']=='negative_3' and r['exit']==90 for r in hm['runs'])
    assert {r['name'] for r in hm['runs'] if r['name'].endswith('_budget')}=={
        'native8p1_pack_budget','native8p2_pack_budget','apint8p2_pack_budget'}
    assert (host/'all.done').exists() and (csim/'all.done').exists()
    assert {r['name'] for r in cm}=={'m3_s2_'+c+'_'+args.tag for c in args.configs}
    assert all(r['passed'] for r in cm)
    for name,h in hm['sources'].items():assert sha(ROOT/name)==h,name
    baseline=ROOT/'build/vivado/tt_m3a_zu5ev.xsa'
    assert sha(baseline)=='9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652'
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'.gitattributes').write_bytes(b'* -text\n')
    def copy(src,dst):
        target=out/dst;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    sources=list((ROOT/'src/hls/m3_s2').glob('*'))+list((ROOT/'src/hls/m3_math').glob('*'))+[ROOT/'sim/hls_tb/tb_m3_s2.cpp',
        ROOT/'build/hls/run_m3_s2_csim.tcl',ROOT/'tools/run_m3_s2_csim.py',ROOT/'tools/test_m3_s2.py',Path(__file__).resolve()]
    for p in sources:copy(p,'source/'+p.relative_to(ROOT).as_posix())
    copy(host/'manifest.json','host_manifest.json');copy(host/'all.done','host_all.done')
    for row in hm['runs']:
        assert sha(host/row['log'])==row['sha256'];copy(host/row['log'],'host/'+row['log'])
    copy(csim/'results.json','csim_results.json');copy(csim/'all.done','csim_all.done')
    copy(ROOT/'build/host/m3_s2_vectors/manifest.json','vectors_manifest.json')
    inputs={}
    for row in cm:
        label=row['name'].removeprefix('m3_s2_').removesuffix('_'+args.tag)
        build=ROOT/'build/hls/optimization_build'/row['name'];snap=build/'snapshot'
        assert not (build/'sol/syn/report').exists(),'Unexpected synthesis output'
        for f,h in row['snapshot'].items():
            p=snap/f;assert sha(p)==h,(row['name'],f)
            if f.startswith('sim/golden/'):
                assert sha(ROOT/f)==h;inputs[f]=h
            else:
                copy(p,'csim/'+label+'/snapshot/'+f)
                if f.startswith('src/') or f.startswith('sim/hls_tb/'):
                    assert sha(ROOT/f)==h,'CSim must match final source'
        copy(build/'csim.done','csim/'+label+'/csim.done')
        copy(ROOT/row['log'],'csim/'+label+'/csim.log')
        copy(csim/(label+'_occupancy.txt'),'csim/'+label+'/occupancy.txt')
    for vec in hm['vectors']:
        p=ROOT/vec['output'];assert sha(p)==vec['sha256'];inputs[vec['output']]=vec['sha256']
        inputs.update(vec['inputs'])
    for num in (8,16):
        g=ROOT/'sim/golden'/('n6_engine_i8' if num==8 else 'n6_engine')/'batch_hanchuan'
        for n in ('weights_engine.bin','wins_i16.bin','expect_logits_i32.bin','expect_class_u32.bin'):
            p=g/n;inputs[p.relative_to(ROOT).as_posix()]=sha(p)
    inputs['build/vivado/tt_m3a_zu5ev.xsa']=sha(baseline)
    manifest=dict(schema=1,parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        scope='S2 C++ implementation + host + full CSim ONLY; G2 hardware screening pending, no RTL/implementation/board',tag=args.tag,
        sources={p.relative_to(ROOT).as_posix():sha(p) for p in sources},inputs=inputs,
        artifacts={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('S2_EVIDENCE_PASS',len(inputs),'inputs',len(manifest['artifacts']),'artifacts')
if __name__=='__main__':main()
