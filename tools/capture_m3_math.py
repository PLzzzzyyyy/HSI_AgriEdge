"""Archive math handshake iterations and the explicitly aborted G2 snapshot."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--runs',nargs='+',required=True);ap.add_argument('--g2-tag',required=True)
    args=ap.parse_args()
    assert all(re.fullmatch('[a-z0-9_]+',s) for s in args.runs+[args.g2_tag])
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'.gitattributes').write_bytes(b'* -text\n')
    def copy(p,rel):
        d=out/rel;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,d)
    summary=[]
    for tag in args.runs:
        run=ROOT/'build/host'/('m3_math_'+tag);m=json.loads((run/'manifest.json').read_text())
        assert json.loads((run/'running.json').read_text()).get('finished')
        for rel,h in m['sources'].items():assert sha(run/'snapshot'/rel)==h,rel
        for r in m['runs']:assert sha(run/r['log'])==r['sha256'],r['log']
        shutil.copytree(run/'snapshot',out/tag/'snapshot')
        for p in run.iterdir():
            if p.is_file() and p.suffix in ('.log','.json','.tcl','.done','.txt'):copy(p,tag+'/'+p.name)
        build=ROOT/'build/hls/optimization_build'/('m3_math_'+tag)
        profiles={}
        for p in (build/'sol/syn/report').glob('*'):
            if p.is_file():copy(p,tag+'/reports/'+p.name)
            if p.name.endswith('_csynth.xml'):
                t=ET.parse(p);assert t.findtext('.//Part')=='xazu5ev-sfvc784-1-i'
                profiles[p.stem]=dict(resources={e.tag:int(e.text) for e in t.findall('.//AreaEstimates/Resources/*')},
                    clock_ns=float(t.findtext('.//EstimatedClockPeriod')),
                    target_ns=float(t.findtext('.//TargetClockPeriod')),
                    uncertainty_ns=float(t.findtext('.//ClockUncertainty')),
                    loops=ET.tostring(t.find('.//SummaryOfLoopLatency'),encoding='unicode') if t.find('.//SummaryOfLoopLatency') is not None else None)
        for p in (build/'sol/sim/report').glob('*'):
            if p.is_file() and p.suffix in ('.rpt','.xml','.log'):copy(p,tag+'/cosim/'+p.name)
        for p in (build/'sol/sim/verilog').glob('*.result.lat.rb'):copy(p,tag+'/cosim/'+p.name)
        for name in ['m3_math_probe.v','m3_math_probe_client.v','m3_math_probe_service.v']:
            p=build/'sol/syn/verilog'/name
            if p.exists():copy(p,tag+'/rtl_diagnostic/'+name)
        rtl_hashes={p.relative_to(build).as_posix():sha(p) for p in (build/'sol/syn/verilog').glob('*') if p.is_file()}
        (out/tag/'rtl_hashes.json').write_text(json.dumps(rtl_hashes,indent=2),encoding='utf-8')
        passed=m.get('passed',False);post=[]
        if passed:
            assert (run/'hardware.done').exists()
            rpt=build/'sol/sim/report/m3_math_probe_cosim.rpt'
            assert re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',rpt.read_text())
            text=(run/'hardware.log').read_text(errors='replace')
            post=re.findall(r'M3_MATH_CALL run=(\d+) count=(\d+) retired=(\d+) request_stalls=(\d+) receive_holds=(\d+)',text)[-6:]
            assert len(post)==6 and sum(int(r[2]) for r in post)==48
            assert int(post[3][3])>0 and int(post[3][4])==2000
        else:assert (run/'manual_stop.json').exists()
        summary.append(dict(tag=tag,functional_rtl_pass=passed,manually_aborted=not passed,
                            profiles=profiles,rtl_postcheck_calls=post,
                            scope='48 math responses only; NOT S2 complete network/system/board'))
    # This prior candidate was stopped against II1, not naturally completed.
    run=ROOT/'build/host'/('m3_s2_synth_'+args.g2_tag)
    rows=json.loads((run/'results.json').read_text());assert len(rows)==1
    assert rows[0]['synthesis_completed'] is False and rows[0]['timed_out'] is False
    for name in ['results.json','running.json','manual_stop.json','runner_used.py','8p1_pack.log']:
        copy(run/name,'g2_aborted/'+name)
    build=ROOT/'build/hls/optimization_build'/rows[0]['name']
    for rel,h in rows[0]['snapshot'].items():
        p=build/'snapshot'/rel;assert sha(p)==h;copy(p,'g2_aborted/snapshot/'+rel)
    assert not (build/'sol/syn/report/s2_engine_csynth.xml').exists()
    diag=ROOT/'build/host/m3_math_diag_20261007_r1'
    for name in ['console.log','running.json','exit.json','sim/verilog/diag.tcl']:
        copy(diag/name,'bounded_diagnostic/'+name)
    copy(Path(__file__).resolve(),'capture_used.py')
    (out/'summary.json').write_text(json.dumps(dict(scope='local handshake iterations, not Goal completion',runs=summary),indent=2),encoding='utf-8')
    files={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    (out/'manifest.json').write_text(json.dumps(dict(files=files),indent=2),encoding='utf-8')
    print('M3_MATH_ARCHIVE_VERIFIED',len(files),'files; R1 aborted, R2/R3 functional RTL, G2 aborted without resource report')
if __name__=='__main__':main()
