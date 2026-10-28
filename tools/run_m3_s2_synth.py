"""G2 HLS synthesis screening only; require matching completed CSim first."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def scheduler_summary(tree):
    # S2 has one top-level count-dependent scheduler; init loops have fixed
    # trip counts. Use structure, not source line numbers or transient warnings.
    container=tree.find('.//SummaryOfLoopLatency')
    loops=[] if container is None else [e for e in container.iter()
        if e.tag=='schedule_loop' or e.tag.endswith('_schedule_loop')]
    if not loops:loops=[] if container is None else [e for e in container if e.findtext('TripCount')=='undef']
    if len(loops)!=1:return dict(error='scheduler loop not uniquely identified')
    loop=loops[0]
    return dict(name=loop.tag,pipeline_ii=loop.findtext('PipelineII'),
                pipeline_depth=loop.findtext('PipelineDepth'),
                iteration_latency=loop.findtext('IterationLatency'),
                iteration_min=loop.findtext('IterationLatency/range/min'),
                iteration_max=loop.findtext('IterationLatency/range/max'))

def scheduler_report(top_xml):
    # DATAFLOW can outline the scheduler into Block_split*_proc rather than
    # retaining engine_task as its report name. Require one named loop owner.
    owners=[]
    for p in top_xml.parent.glob('*_csynth.xml'):
        t=ET.parse(p);c=t.find('.//SummaryOfLoopLatency')
        if c is not None and any(e.tag=='schedule_loop' or e.tag.endswith('_schedule_loop') for e in c.iter()):
            owners.append((p,t))
    if len(owners)==1:return owners[0]
    # Legacy S2 has no explicit loop label. Ambiguous outlined owners fail
    # closed through a missing scheduler tree, never choose an init loop.
    return (top_xml,ET.parse(top_xml)) if not owners else (None,ET.ElementTree(ET.Element('AmbiguousScheduler')))

def continuation_blockers(tree,text,schedule_tree=None):
    """Stop automatic next builds for review, NOT a Vivado feasibility verdict."""
    blockers=[]
    for field in ('LUT','FF','DSP','BRAM_18K','URAM'):
        used=tree.findtext('.//AreaEstimates/Resources/'+field)
        cap=tree.findtext('.//AreaEstimates/AvailableResources/'+field)
        if used is None or cap is None:
            blockers.append('resource capacity missing: '+field)
        elif int(used)>int(cap):
            blockers.append('HLS estimate requires review: %s %s > %s'%(field,used,cap))
    if re.search(r'Unable to satisfy pipeline directive for loop',text):
        blockers.append('requested loop pipeline not achieved')
    schedule=scheduler_summary(tree if schedule_tree is None else schedule_tree)
    if 'error' in schedule:blockers.append(schedule['error'])
    else:
        ii=schedule['pipeline_ii']
        if ii is None or not ii.isdigit() or int(ii)<1:
            blockers.append('scheduler PipelineII missing or invalid')
        elif int(ii)!=1:
            blockers.append('scheduler II=%s exceeds fixed II=1 screen'%ii)
    return blockers

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',default=datetime.now().strftime('%Y%m%d_%H%M%S'))
    ap.add_argument('--csim-tag',default='20261007_r2')
    ap.add_argument('--only',nargs='+',choices=['8p1_pack','8p2_pack','8p2_plain'],default=['8p1_pack','8p2_pack'])
    ap.add_argument('--timeout',type=int,default=2700)
    args=ap.parse_args()
    if not re.fullmatch('[a-z0-9_]+',args.tag) or not re.fullmatch('[a-z0-9_]+',args.csim_tag): ap.error('Invalid tag')
    source_run=ROOT/'build/host'/('m3_s2_csim_'+args.csim_tag)
    records=json.loads((source_run/'results.json').read_text())
    out=ROOT/'build/host'/('m3_s2_synth_'+args.tag);out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(Path(__file__).resolve(),out/'runner_used.py')
    results=[]
    for label in args.only:
        srcname='m3_s2_'+label+'_'+args.csim_tag
        row=next(r for r in records if r['name']==srcname)
        if not row['passed']: raise RuntimeError('CSim failed')
        previous=ROOT/'build/hls/optimization_build'/srcname
        if not (previous/'csim.done').exists(): raise RuntimeError('CSim receipt missing')
        for path,h in row['snapshot'].items():
            if path.startswith('src/') and path.endswith(('.cpp','.h')):
                if sha(ROOT/path)!=h or sha(previous/'snapshot'/path)!=h: raise RuntimeError('CSim/source mismatch: '+path)
        check=subprocess.run(['powershell','-NoProfile','-Command',"Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],capture_output=True,text=True,check=True)
        (out/(label+'_occupancy.txt')).write_text(check.stdout,encoding='utf-8')
        if check.stdout.strip(): raise RuntimeError('Hardware task occupied')
        name='m3_s2_syn_'+label+'_'+args.tag
        env=dict(os.environ,S2_SYN_NAME=name,S2_CSIM_BUILD=str(previous),S2_NUM=str(row['num']),S2_P=str(row['p']),S2_PACK=str(row['pack']))
        cmd=['D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat','-f',str(ROOT/'build/hls/run_m3_s2_synth.tcl')]
        log=out/(label+'.log');start=time.monotonic();print('START',name,flush=True)
        with log.open('w',encoding='utf-8') as f:
            proc=subprocess.Popen(subprocess.list2cmdline(cmd),shell=True,env=env,cwd=out,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/'running.json').write_text(json.dumps(dict(pid=proc.pid,name=name,command=cmd,log=str(log),started=datetime.now().isoformat())),encoding='utf-8')
            timed_out=False
            try: code=proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                # Terminate only the process tree created immediately above.
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=f,stderr=subprocess.STDOUT,check=False)
                proc.wait();code=-1;timed_out=True
        build=ROOT/'build/hls/optimization_build'/name
        text=log.read_text(encoding='utf-8',errors='replace')
        xml=build/'sol/syn/report/s2_engine_csynth.xml'
        passed=code==0 and (build/'synth.done').exists() and xml.exists() and 'ERROR:' not in text
        result=dict(name=name,num=row['num'],p=row['p'],pack=row['pack'],source_csim=srcname,
                    exit=code,passed=passed,timed_out=timed_out,seconds=round(time.monotonic()-start,3),
                    log=str(log.relative_to(ROOT)),log_sha256=sha(log),errors=[l for l in text.splitlines() if 'ERROR:' in l],
                    snapshot={str(p.relative_to(build/'snapshot')).replace('\\','/'):sha(p) for p in (build/'snapshot').rglob('*') if p.is_file()})
        if xml.exists():
            tree=ET.parse(xml)
            result['hls_resources']={e.tag:e.text for e in tree.findall('.//AreaEstimates/Resources/*')}
            result['hls_latency']={e.tag:e.text for e in tree.findall('.//SummaryOfOverallLatency/*')}
            result['hls_clock_ns']=tree.findtext('.//EstimatedClockPeriod')
            schedule_xml,schedule_tree=scheduler_report(xml)
            result['scheduler_report']=str(schedule_xml.relative_to(ROOT)) if schedule_xml else None
            result['scheduler']=scheduler_summary(schedule_tree)
            result['continuation_blockers']=continuation_blockers(tree,text,schedule_tree)
        result['synthesis_completed']=passed
        result['gate_scope']='Automatic continuation review only; not G2/Vivado/board PASS'
        results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        (out/'running.json').write_text(json.dumps(dict(name=name,finished=True,passed=passed)),encoding='utf-8')
        print('DONE',json.dumps({k:v for k,v in result.items() if k not in ('snapshot',)}),flush=True)
        if not passed or result.get('continuation_blockers'): return 1
    (out/'all.done').write_text('S2_SYNTH_ALL_PASS\n',encoding='utf-8');return 0
if __name__=='__main__':sys.exit(main())
