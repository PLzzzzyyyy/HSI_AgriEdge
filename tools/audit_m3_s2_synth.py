"""Summarize completed HLS estimates; never convert them to board timings."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

def expressions(text):
    section=text.split('* Expression:',1)[1].split('* Multiplexer:',1)[0]
    rows=[]
    for line in section.splitlines():
        c=[v.strip() for v in line.strip().strip('|').split('|')]
        if len(c)==7 and c[0]!='Total' and all(v.isdigit() for v in c[2:5]):
            rows.append(dict(name=c[0],op=c[1],dsp=int(c[2]),ff=int(c[3]),lut=int(c[4]),
                             width0=int(c[5]) if c[5].isdigit() else None,
                             width1=int(c[6]) if c[6].isdigit() else None))
    return rows

def audit(report):
    text=Path(report).read_text(encoding='utf-8',errors='replace')
    rows=expressions(text)
    total=sum(r['lut'] for r in rows)
    expected=re.search(r'\|Expression\s*\|\s*-\s*\|\s*-\s*\|\s*0\s*\|\s*(\d+)\s*\|',text)
    assert expected and total==int(expected[1]),'Expression table did not reconcile'
    count=Counter();luts=Counter();width_luts=Counter()
    for r in rows:
        count[r['op']]+=1;luts[r['op']]+=r['lut']
        if r['op'] in ('ashr','lshr','shl'):width_luts[str(r['width0'])]+=r['lut']
    shifts=[r for r in rows if r['op'] in ('ashr','lshr','shl')]
    return dict(scope='HLS estimates only, no RTL/board timing or fitted stage costs',
        report=str(report),expression_lut_total=total,
        expression_by_op=[dict(op=k,count=count[k],lut=v) for k,v in luts.most_common()],
        shifts=dict(count=len(shifts),lut=sum(r['lut'] for r in shifts),lut_by_input_width=dict(width_luts)),
        largest_expressions=sorted(rows,key=lambda r:r['lut'],reverse=True)[:20])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('report',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    result=audit(a.report);a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='largest_expressions'},indent=2))
if __name__=='__main__':main()
