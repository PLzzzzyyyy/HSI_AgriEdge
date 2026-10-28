"""Archive G2 synthesis attempts, including failures (never label them PASS)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runs',nargs='+',required=True)
    ap.add_argument('--csim-tag',required=True)
    ap.add_argument('--host-dir',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=ROOT/'report/m3_s2_synth');args=ap.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'.gitattributes').write_bytes(b'* -text\n')
    def copy(src,dst):
        dest=out/dst;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    sources=list((ROOT/'src/hls/m3_s2').glob('*'))+list((ROOT/'src/hls/m3_math').glob('*'))+[ROOT/'build/hls/run_m3_s2_synth.tcl',
             ROOT/'tools/run_m3_s2_synth.py',ROOT/'tools/audit_m3_s2_synth.py',
             ROOT/'tools/test_m3_s2_synth_gate.py',Path(__file__).resolve()]
    for p in sources:copy(p,'source/'+p.relative_to(ROOT).as_posix())
    attempts=[];large_diagnostics=[]
    for tag in args.runs:
        run=ROOT/'build/host'/('m3_s2_synth_'+tag)
        state=json.loads((run/'running.json').read_text())
        assert state.get('finished'),'Attempt still running'
        rows=json.loads((run/'results.json').read_text());attempts.extend(rows)
        copy(run/'results.json',tag+'/results.json');copy(run/'running.json',tag+'/completion.json')
        for n in ('runner_used.py','manual_stop.json','expression_audit.json','gate_tests.txt','resource_summary.md','p2_not_started.json'):
            if (run/n).exists():copy(run/n,tag+'/'+n)
        for row in rows:
            build=ROOT/'build/hls/optimization_build'/row['name']
            log=ROOT/row['log'];label=log.stem
            assert sha(log)==row['log_sha256']
            base=tag+'/'+label
            copy(log,base+'/synthesis.log');copy(run/(label+'_occupancy.txt'),base+'/occupancy.txt')
            for f,h in row['snapshot'].items():
                p=build/'snapshot'/f;assert sha(p)==h;copy(p,base+'/snapshot/'+f)
            for p in (build/'sol/syn/report').glob('*'):
                if p.is_file() and p.suffix in ('.rpt','.xml'):copy(p,base+'/reports/'+p.name)
            if (build/'synth.done').exists():copy(build/'synth.done',base+'/synth.done')
            # Preserve generated diagnostics, not enormous intermediate bitcode.
            for n in ('csynth.rpt','csynth.xml','s2_engine.verbose.rpt','s2_engine.verbose.sched.rpt'):
                p=build/'sol/.autopilot/db'/n
                if p.exists():
                    if p.stat().st_size<=4*1024*1024:copy(p,base+'/diagnostics/'+n)
                    else:large_diagnostics.append(dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p),note='Large intermediate retained in build, not copied'))
        if (run/'all.done').exists():copy(run/'all.done',tag+'/all.done')
    csim=ROOT/'build/host'/('m3_s2_csim_'+args.csim_tag)
    rows=json.loads((csim/'results.json').read_text());assert all(r['passed'] for r in rows)
    copy(csim/'results.json','csim/results.json');copy(csim/'all.done','csim/all.done')
    inputs={}
    host=args.host_dir.resolve();hm=json.loads((host/'manifest.json').read_text());assert hm['passed']
    for p,h in hm['sources'].items():assert sha(ROOT/p)==h
    copy(host/'manifest.json','host/manifest.json');copy(host/'all.done','host/all.done')
    for r in hm['runs']:
        assert r['passed'] and sha(host/r['log'])==r['sha256'];copy(host/r['log'],'host/'+r['log'])
    for row in rows:
        build=ROOT/'build/hls/optimization_build'/row['name']
        label=Path(row['log']).stem
        copy(ROOT/row['log'],'csim/'+label+'/csim.log');copy(build/'csim.done','csim/'+label+'/csim.done')
        for f,h in row['snapshot'].items():
            p=build/'snapshot'/f;assert sha(p)==h
            if f.startswith('sim/golden/'):
                assert sha(ROOT/f)==h;inputs[f]=h
            elif f.endswith(('.cpp','.h')) and f.startswith('src/'):
                assert sha(ROOT/f)==h,'Final source differs from CSim'
    # Numeric prerequisite actually used by the completed (older) synthesis.
    for tag in sorted({r['source_csim'].split('_pack_',1)[-1] for r in attempts if '_pack_' in r['source_csim']}):
        previous=ROOT/'build/host'/('m3_s2_csim_'+tag)
        if (previous/'results.json').exists():
            copy(previous/'results.json','csim_history/'+tag+'/results.json')
            for r in json.loads((previous/'results.json').read_text()):
                if r['passed']:
                    copy(ROOT/r['log'],'csim_history/'+tag+'/'+Path(r['log']).name)
    baseline=ROOT/'build/vivado/tt_m3a_zu5ev.xsa'
    assert sha(baseline)=='9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652'
    inputs[baseline.relative_to(ROOT).as_posix()]=sha(baseline)
    m=dict(schema=1,parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip(),
           scope='HLS synthesis screening + prerequisite CSim; NOT RTL/OOC/system implementation/board',
           runs=args.runs,csim_tag=args.csim_tag,attempts=attempts,
           large_diagnostics=large_diagnostics,
           sources={p.relative_to(ROOT).as_posix():sha(p) for p in sources},inputs=inputs,
           artifacts={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()})
    (out/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8')
    print('G2_SYNTH_EVIDENCE',len(attempts),'attempts',len(inputs),'inputs',len(m['artifacts']),'artifacts')
if __name__=='__main__':main()
