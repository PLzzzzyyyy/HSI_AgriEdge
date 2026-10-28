"""Verify and archive T2 state microkernel + worker/full integration evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from run_m3_state import ROOT, PART

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def copy_files(src,dst):
    for p in src.rglob('*'):
        if p.is_file() and p.suffix in ('.h','.cpp','.py','.json','.log','.txt','.tcl','.done','.rpt','.xml','.v','.rb'):
            q=dst/p.relative_to(src);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True);ap.add_argument('--micro-tag');ap.add_argument('--edges-tag');args=ap.parse_args()
    if any(not re.fullmatch('[a-z0-9_]+',v) for v in [args.tag,args.micro_tag or args.tag,args.edges_tag or args.tag]):ap.error('invalid tag')
    source=ROOT/'build/host'/('m3_state_'+(args.micro_tag or args.tag))
    m=json.loads((source/'manifest.json').read_text());assert m['passed'] and (source/'all.done').exists()
    for r in m['runs']:assert r['passed'] and sha(source/r['log'])==r['sha256']
    for name,digest in m['sources'].items():assert sha(source/'snapshot'/name)==digest
    # Reuse r1 hardware only if declarations really match the final source.
    before=(source/'snapshot/src/hls/m3_s2/s2_internal.h').read_text()
    after=(ROOT/'src/hls/m3_s2/s2_internal.h').read_text()
    after=re.sub(r'    void check_bounds\(\) const \{.*?\n    \}\n', '', after, flags=re.S)
    before=re.sub(r'    void check_bounds\(\) const \{.*?\n    \}\n', '', before, flags=re.S)
    assert before==after, 'micro declarations changed: rerun hardware'
    for name in ['s2_engine.h','s2_state.h','s2_index.h','s2_quant.h']:
        assert sha(source/'snapshot/src/hls/m3_s2'/name)==sha(ROOT/'src/hls/m3_s2'/name)
    out=ROOT/'report/m3_state'/args.tag;out.mkdir(parents=True,exist_ok=False)
    (out/'.gitattributes').write_text('* -text\n');copy_files(source,out/'micro')
    rows=[]
    for h in m['hardware']:
        xml=ROOT/h['xml'];assert sha(xml)==h['sha256'];t=ET.parse(xml)
        assert t.findtext('.//Part')==PART and float(t.findtext('.//TargetClockPeriod'))==5
        build=ROOT/'build/hls/optimization_build'/h['name']/'sol'
        cosim=build/'sim/report/m3_state_micro_cosim.rpt'
        assert re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',cosim.read_text())
        label='old32' if h['old'] else 'narrow'
        for sub in ['syn/report','syn/verilog','sim/report']:copy_files(build/sub,out/label/sub)
        for p in (build/'sim/verilog').glob('*.result.lat.rb'):
            q=out/label/p.name;shutil.copyfile(p,q)
        rows.append(dict(name=label,resources={e.tag:int(e.text) for e in t.findall('.//AreaEstimates/Resources/*')},
             latency={e.tag:e.text for e in t.findall('.//SummaryOfOverallLatency/*')},
             estimated_clock_ns=float(t.findtext('.//EstimatedClockPeriod'))))
    for name,prefix in [('edges','m3_state_edges_'),('host','m3_s2_host_')]:
        src=ROOT/'build/host'/(prefix+((args.edges_tag or args.tag) if name=='edges' else args.tag));data=json.loads((src/'manifest.json').read_text())
        assert data['passed'] and (src/'all.done').exists()
        for r in data['runs']:assert r['passed'] and sha(src/r['log'])==r['sha256']
        if name=='edges':
            for path,digest in data['sources'].items():
                assert sha(src/'snapshot'/path)==digest
                if path.startswith('src/'):
                    previous=(src/'snapshot'/path).read_text()
                    current=(ROOT/path).read_text()
                    if path.endswith('s2_engine.cpp'):
                        previous=previous.replace('s.done|=bit(j.stage);','s.done|=State<15>(bit(j.stage));')
                    assert previous==current, 'edge source changed beyond audited stage-mask cast'
        else:
            for path,digest in data['sources'].items():assert sha(ROOT/path)==digest
        copy_files(src,out/'integration'/name)
    csim=ROOT/'build/host'/('m3_s2_csim_'+args.tag)
    results=json.loads((csim/'results.json').read_text());assert len(results)==3 and (csim/'all.done').exists()
    assert {(r['num'],r['p'],r['pack']) for r in results}=={(8,1,1),(8,2,1),(16,2,0)}
    for r in results:
        assert r['passed']
        snap=ROOT/'build/hls/optimization_build'/r['name']/'snapshot'
        for path,digest in r['snapshot'].items():
            assert sha(snap/path)==digest
            if path.startswith('src/'):assert sha(ROOT/path)==digest
        assert 'Bitsize mismatch' not in (ROOT/r['log']).read_text(errors='replace')
        # Archive source/testbench/parameters, not duplicate large golden binaries.
        copy_files(snap,out/'integration/csim_snapshots'/r['name'])
    copy_files(csim,out/'integration/csim')
    summary=dict(scope='state microkernel + C integration ONLY, NOT G2/G3/G4 or board',part=PART,clock_ns=5,rows=rows)
    (out/'comparison.json').write_text(json.dumps(summary,indent=2))
    shutil.copyfile(Path(__file__),out/'capture_used.py')
    xsa=ROOT/'build/vivado/tt_m3a_zu5ev.xsa'
    assert sha(xsa)=='9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652'
    (out/'baseline_xsa.json').write_text(json.dumps(dict(path=xsa.relative_to(ROOT).as_posix(),sha256=sha(xsa),unchanged=True),indent=2))
    files={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    (out/'archive_manifest.json').write_text(json.dumps(dict(files=files),indent=2))
    print(json.dumps(summary,indent=2));print('ARCHIVED',len(files),'files')
if __name__=='__main__':main()
