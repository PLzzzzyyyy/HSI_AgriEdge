"""Check serial M3a board UART coverage and recompute every PERF from SAMPLE ticks.

Read-only by default; --out must be a new path. Never connects to a board.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("PREEMBED_FULL", "PS_EMBED_PLUS_FULL")

def need(ok, message):
    if not ok: raise ValueError(message)

def check(text):
    need(not re.search(r"(?m)^(FAIL|ABORT|M3A_APP_END FAIL)", text), "UART contains failure")
    need(text.count("M3A_SERIAL_BASELINE v1") == 1, "Expected one run")
    for marker in ("M3A_CORRECTNESS PASS mismatches=0", "M3A_BASELINE PASS mismatches=0",
                   "M3A_APP_END PASS", "HALTED: save UART log.", "PASS PS embed vs golden A",
                   "PASS resume actual DUMP L4 -> L5..11 FEAT/CLASS"):
        need(marker in text, "Missing " + marker)
    need("package=d081e19d48e22c0e" in text, "Unknown baseline package")
    timer = re.search(r"timer_hz=(\d+) runs=(\d+) batch=(\d+) max_polls=(\d+) PS_backend=(\w+)",text)
    need(timer is not None, "Missing timer configuration")
    hz,runs,batch,polls = map(int,timer.groups()[:4])
    need(hz>0 and runs==10 and batch==16 and timer[5]=="NEON", "Unexpected timer/app configuration")
    layers = re.findall(r"^PASS DUMP layer=(\d+) elements=(\d+)$",text,re.M)
    need(layers==[(str(l),"15876") for l in range(12)],"Incomplete/duplicate DUMP")
    logits = re.search(r"PASS A/B/A LOGITS32; A_q16=([\d,\-]+)",text)
    gold = struct.unpack("<32i",(ROOT/"sim/golden/n6_engine/a/logits_q16_i32.bin").read_bytes())
    need(logits and tuple(map(int,logits[1].split(',')))==gold[:9],"Printed logits disagree with golden")
    cls=re.search(r"PASS A/B/A CLASS\+confidence\+odd_tail; A=(0x[0-9a-f]+) B=(0x[0-9a-f]+)",text)
    need(cls is not None,"Missing CLASS")
    for i,ent in enumerate(('a','b'),1):
        expected=struct.unpack('<I',(ROOT/f'sim/golden/n6_engine/{ent}/class_u32.bin').read_bytes())[0]
        need(int(cls[i],16)==expected,"CLASS differs from golden")
    expected={(s,k,n) for s in SCOPES for k in ('LOGITS','CLASS') for n in (1,3,16)}
    samples=defaultdict(dict)
    lines=re.findall(r"^SAMPLE scope=(\w+) out=(\w+) n=(\d+) run=(\d+) ticks=(\d+)$",text,re.M)
    need(len(lines)==120,"Expected 120 samples")
    for s,k,n,r,t in lines:
        key=(s,k,int(n)); run=int(r)
        need(key in expected and run not in samples[key] and int(t)>0,"Duplicate/invalid sample")
        samples[key][run]=int(t)
    perfs=[]; seen=set()
    for line in text.splitlines():
        if not line.startswith('PERF '): continue
        fields=dict(v.split('=',1) for v in line.split()[1:])
        key=(fields['scope'],fields['out'],int(fields['n']))
        need(key in expected and key not in seen,"Duplicate/unknown PERF")
        need(int(fields['runs'])==runs and set(samples[key])==set(range(runs)),"Missing repeat")
        seen.add(key); ticks=list(samples[key].values()); total=sum(ticks); n=key[2]
        need(int(fields['total_ticks'])==total,"Total ticks mismatch")
        metrics=dict(mean_batch_ms=total*1000/hz/runs,min_batch_ms=min(ticks)*1000/hz,
                     max_batch_ms=max(ticks)*1000/hz,ms_per_patch=total*1000/hz/runs/n,
                     patches_per_s=hz*runs*n/total)
        for name,value in metrics.items():
            tol=.000501 if name=='patches_per_s' else .000000501
            need(abs(float(fields[name])-value)<=tol,f"{key}: {name} does not round from samples")
        perfs.append(dict(scope=key[0],out=key[1],n=n,runs=runs,total_ticks=total,**metrics))
    need(seen==expected,"Missing PERF group")
    load=re.search(r"LOAD_W PASS bytes=(\d+) ticks=(\d+) ms=([\d.]+) return=(0x[0-9a-f]+)",text)
    need(load and int(load[1])==480576 and int(load[4],16)==0x120c0300,"Weight/contract check")
    load_ms=int(load[2])*1000/hz
    need(abs(float(load[3])-load_ms)<=.000000501,"LOAD_W timer mismatch")
    return dict(status="SERIAL_M3A_BOARD_UART_PASS",timer_hz=hz,samples=120,groups=12,
                dump_layers=12,load_ms=load_ms,metrics=perfs,
                limits="User-provided UART; repeated A benchmark, not scene throughput, not M3b or long-run validation")

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('uart',type=Path)
    ap.add_argument('--out',type=Path)
    a=ap.parse_args()
    result=check(a.uart.read_text(encoding='utf-8'))
    content=json.dumps(result,indent=2)+'\n'
    if a.out:
        with a.out.open('x',encoding='utf-8',newline='\n') as f: f.write(content)
    print(content)
