"""Archive and verify the like-part old/new quantizer experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from run_m3_quant import ROOT, PART

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True);args=ap.parse_args()
    if not re.fullmatch('[a-z0-9_]+',args.tag):ap.error('invalid tag')
    source=ROOT/'build/host'/('m3_quant_'+args.tag)
    m=json.loads((source/'manifest.json').read_text())
    assert m.get('passed') and (source/'all.done').exists()
    assert len(m['runs'])==6 and all(r['passed'] for r in m['runs'])
    assert m.get('part')==PART and m.get('clock_ns')==5
    for name,digest in m['sources'].items():assert sha(source/'snapshot'/name)==digest
    for r in m['runs']:assert sha(source/r['log'])==r['sha256']
    rows=[]
    for h in m['hardware']:
        p=ROOT/h['xml'];assert sha(p)==h['sha256']
        t=ET.parse(p);assert t.findtext('.//Part')==PART
        assert float(t.findtext('.//TargetClockPeriod'))==5
        assert t.findtext('.//PipelineInitiationInterval')=='1'
        build=ROOT/'build/hls/optimization_build'/h['name']
        cosim=build/'sol/sim/report/m3_quant_micro_cosim.rpt'
        text=cosim.read_text()
        assert re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',text),text
        rows.append(dict(name='old64' if h['old'] else 'bounded',part=PART,
                         resources={e.tag:int(e.text) for e in t.findall('.//AreaEstimates/Resources/*')},
                         latency={e.tag:e.text for e in t.findall('.//SummaryOfOverallLatency/*')},
                         estimated_clock_ns=float(t.findtext('.//EstimatedClockPeriod')),
                         cosim_report=str(cosim.relative_to(ROOT))))
    assert [r['name'] for r in rows]==['old64','bounded']
    assert rows[1]['resources']['LUT']<rows[0]['resources']['LUT']
    # This local criterion does not certify full-network tick or system timing.
    out=ROOT/'report/m3_quant'/args.tag;out.mkdir(parents=True,exist_ok=False)
    (out/'.gitattributes').write_text('* -text\n')
    shutil.copytree(source/'snapshot',out/'snapshot')
    for p in source.iterdir():
        if p.is_file() and p.suffix in ('.json','.log','.tcl','.done','.txt'):shutil.copyfile(p,out/p.name)
    for h,r in zip(m['hardware'],rows):
        dst=out/r['name'];dst.mkdir()
        build=ROOT/'build/hls/optimization_build'/h['name']
        for p in (build/'sol/syn/report').glob('*'):shutil.copyfile(p,dst/p.name)
        shutil.copyfile(ROOT/r['cosim_report'],dst/'m3_quant_micro_cosim.rpt')
        for p in (build/'sol/sim/report').glob('*.xml'):shutil.copyfile(p,dst/p.name)
        for p in (build/'sol/sim/verilog').glob('*.result.lat.rb'):shutil.copyfile(p,dst/p.name)
    result=dict(scope='local quantizer comparison, not full network/system/board',rows=rows,
                lut_reduction_pct=100*(1-rows[1]['resources']['LUT']/rows[0]['resources']['LUT']))
    (out/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    files={str(p.relative_to(out)).replace('\\','/'):sha(p) for p in out.rglob('*') if p.is_file()}
    (out/'archive_manifest.json').write_text(json.dumps(dict(files=files),indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
