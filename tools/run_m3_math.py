# Independent long-latency math FIFO probe; never starts a full network build.
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
ROOT=Path(__file__).resolve().parents[1]
HLS=Path('D:/xilinx/Vitis_HLS/2020.2')
PART='xazu5ev-sfvc784-1-i'
FILES=['src/hls/m3_math/s2_math.h','src/hls/m3_math/s2_math.cpp',
       'sim/hls_tb/m3_math_probe.cpp','sim/hls_tb/m3_math_probe.h','sim/hls_tb/tb_m3_math.cpp','tools/run_m3_math.py']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True)
    ap.add_argument('--hardware',action='store_true')
    ap.add_argument('--coexist-pid',type=int,help='Only this verified S2 synthesis may coexist with the small probe')
    args=ap.parse_args()
    if not re.fullmatch('[a-z0-9_]+',args.tag):ap.error('invalid tag')
    out=ROOT/'build/host'/('m3_math_'+args.tag);out.mkdir(parents=True,exist_ok=False)
    snap=out/'snapshot'
    for name in FILES:
        p=snap/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
    m=dict(scope='standalone tagged math FIFO probe, not integrated S2 or board',part=PART,clock_ns=5,
           sources={n:sha(snap/n) for n in FILES},runs=[])
    def save():(out/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8')
    def run(label,cmd,marker=None):
        t=time.monotonic();log=out/(label+'.log');print('START',label,flush=True)
        with log.open('wb') as f:
            p=subprocess.Popen(list(map(str,cmd)),cwd=out,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/'running.json').write_text(json.dumps(dict(label=label,pid=p.pid,command=list(map(str,cmd)),log=str(log))),encoding='utf-8')
            code=p.wait()
        text=log.read_text(encoding='utf-8',errors='replace')
        ok=code==0 and 'ERROR:' not in text and (marker is None or marker in text)
        m['runs'].append(dict(label=label,passed=ok,exit=code,seconds=round(time.monotonic()-t,3),log=log.name,sha256=sha(log)))
        save();(out/'running.json').write_text(json.dumps(dict(label=label,finished=True,passed=ok)),encoding='utf-8')
        print(label,'PASS' if ok else 'FAIL',flush=True)
        if not ok:raise RuntimeError(text[-4000:])
    save()
    src=[snap/n for n in FILES if n.endswith('.cpp')]
    for num in (8,16):
        for native in (1,0):
            label=f'n{num}_native{native}';exe=out/(label+'.exe')
            run(label+'_compile',['D:/mingw64/bin/g++.exe','-O2','-std=c++14','-ffp-contract=off',
                f'-DS2_NUM={num}',f'-DS2_NATIVE={native}','-I',snap/'src/hls/m3_math','-I',HLS/'include',*src,'-o',exe])
            run(label,[exe],marker=f'M3_MATH_PASS num={num}')
    if args.hardware:
        occ=subprocess.run(['powershell','-NoProfile','-Command',
            "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],capture_output=True,text=True,check=True)
        (out/'occupancy.txt').write_text(occ.stdout,encoding='utf-8')
        if occ.stdout.strip():
            live=json.loads(occ.stdout);live=live if isinstance(live,list) else [live]
            if (len(live)!=1 or live[0]['ProcessId']!=args.coexist_pid
                or live[0]['Name']!='vitis_hls.exe'
                or 'run_m3_s2_synth.tcl' not in live[0]['CommandLine']):
                raise RuntimeError('unexpected hardware occupied; do not start duplicate')
            mem=subprocess.check_output(['powershell','-NoProfile','-Command',
                '(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory'],text=True)
            if int(mem.strip())<4*1024*1024:raise RuntimeError('less than4GiB free for isolated small probe')
            m['coexist']=dict(process=live[0],free_kib=int(mem.strip()),
                              reason='independent small math probe; distinct frozen project, not restart of live S2')
            save()
        name='m3_math_'+args.tag;build=ROOT/'build/hls/optimization_build'/name
        if build.exists():raise RuntimeError('refuse old project')
        inc=(snap/'src/hls/m3_math').as_posix();flags=f'-std=c++14 -ffp-contract=off -DS2_NUM=8 -DS2_NATIVE=0 -I{inc}'
        tcl=out/'run.tcl'
        lines=[f'cd {{{build.parent.as_posix()}}}',f'open_project {name}','set_top m3_math_probe']
        for p in src:
            tb=' -tb' if p.name.startswith('tb_') else ''
            lines.append(f'add_files{tb} {{{p.as_posix()}}} -cflags {{{flags}}}')
        lines+=['open_solution sol -flow_target vivado',f'set_part {PART}','create_clock -period 5 -name default',
                'csim_design','csynth_design','cosim_design -rtl verilog -trace_level all',
                f'set f [open {{{(out/"hardware.done").as_posix()}}} w]',
                'puts $f "M3_MATH_HARDWARE_DONE"','close $f','exit']
        tcl.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        run('hardware',['cmd.exe','/c',HLS/'bin/vitis_hls.bat','-f',tcl],marker='M3_MATH_PASS num=8')
        if not (out/'hardware.done').exists():raise RuntimeError('missing hardware receipt')
        rpt=build/'sol/sim/report/m3_math_probe_cosim.rpt'
        if not rpt.exists() or not re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',rpt.read_text()):raise RuntimeError('cosim not PASS')
        m['hardware']=dict(build=str(build.relative_to(ROOT)),cosim_sha256=sha(rpt));save()
    m['passed']=True;save();(out/'all.done').write_text('M3_MATH_ALL_PASS\n')
if __name__=='__main__':main()
