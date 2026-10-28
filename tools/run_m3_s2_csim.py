"""Only frozen full-network CSim. Never synthesize/export/implement hardware."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
CONFIGS=[('8p1_pack',8,1,1),('8p2_pack',8,2,1),('8p2_plain',8,2,0),('16p2_plain',16,2,0)]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',default=datetime.now().strftime('%Y%m%d_%H%M%S'))
    ap.add_argument('--only',nargs='+',choices=[r[0] for r in CONFIGS]);args=ap.parse_args()
    if not re.fullmatch('[a-z0-9_]+',args.tag): ap.error('invalid tag')
    out=ROOT/'build/host'/('m3_s2_csim_'+args.tag);out.mkdir(parents=True,exist_ok=False)
    records=[]
    for label,num,p,pack in CONFIGS:
        if args.only and label not in args.only: continue
        check=subprocess.run(['powershell','-NoProfile','-Command',"Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],capture_output=True,text=True,check=True)
        (out/(label+'_occupancy.txt')).write_text(check.stdout,encoding='utf-8')
        if check.stdout.strip(): raise RuntimeError('hardware task occupied')
        name='m3_s2_'+label+'_'+args.tag
        env=dict(os.environ,S2_NAME=name,S2_NUM=str(num),S2_P=str(p),S2_PACK=str(pack))
        cmd=['D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat','-f',str(ROOT/'build/hls/run_m3_s2_csim.tcl')]
        log=out/(label+'.log');print('START',name,flush=True)
        with log.open('w',encoding='utf-8') as f:
            proc=subprocess.Popen(subprocess.list2cmdline(cmd),shell=True,env=env,cwd=out,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/'running.json').write_text(json.dumps(dict(pid=proc.pid,name=name,log=str(log),command=cmd)),encoding='utf-8')
            code=proc.wait()
        build=ROOT/'build/hls/optimization_build'/name;text=log.read_text(encoding='utf-8',errors='replace')
        passed=(code==0 and (build/'csim.done').exists() and 'ERROR:' not in text
                and 'S2_TEST_PASS mode=full' in text and 'S2_TEST_PASS mode=budget' in text)
        row=dict(name=name,num=num,p=p,pack=pack,exit=code,passed=passed,log=str(log.relative_to(ROOT)),
                 snapshot={str(f.relative_to(build/'snapshot')).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in (build/'snapshot').rglob('*') if f.is_file()})
        records.append(row);(out/'results.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        (out/'running.json').write_text(json.dumps(dict(name=name,finished=True,passed=passed)),encoding='utf-8')
        print('DONE',name,'PASS' if passed else 'FAIL',flush=True)
        if not passed: return 1
    (out/'all.done').write_text('S2_FULL_CSIM_ALL_PASS\n',encoding='utf-8');return 0
if __name__=='__main__':sys.exit(main())
