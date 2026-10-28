# Frozen old/new quantizer proof. No full-network or system build.
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
PART='xazu5ev-sfvc784-1-i'  # Match the frozen M3/S2 system, not a faster grade.
SOURCES=['src/hls/m3_s2/s2_quant.h','src/hls/m3_s2/s2_internal.h',
         'src/hls/m3_s2/s2_engine.h','sim/hls_tb/tb_m3_quant.cpp',
         'sim/hls_tb/m3_quant_micro.cpp','sim/hls_tb/tb_m3_quant_micro.cpp',
         'tools/run_m3_quant.py']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',default=datetime.now().strftime('%Y%m%d_%H%M%S'))
    ap.add_argument('--hardware',action='store_true');args=ap.parse_args()
    if not re.fullmatch('[a-z0-9_]+',args.tag):ap.error('invalid tag')
    out=ROOT/'build/host'/('m3_quant_'+args.tag);out.mkdir(parents=True,exist_ok=False)
    snap=out/'snapshot'
    for rel in SOURCES:
        dst=snap/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dst)
    manifest=dict(scope='quantizer host/HLS microkernel only, NOT full network or board',part=PART,clock_ns=5,
                  sources={r:sha(snap/r) for r in SOURCES},runs=[])
    def save(): (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    save()
    def run(label,cmd,marker=None):
        start=time.monotonic();log=out/(label+'.log')
        with log.open('wb') as f:
            p=subprocess.Popen([str(x) for x in cmd],cwd=out,stdout=f,stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            (out/'running.json').write_text(json.dumps(dict(label=label,pid=p.pid,command=list(map(str,cmd)),log=str(log))),encoding='utf-8')
            code=p.wait()
        text=log.read_text(encoding='utf-8',errors='replace')
        ok=code==0 and (marker is None or marker in text) and 'ERROR:' not in text
        manifest['runs'].append(dict(name=label,exit=code,passed=ok,seconds=round(time.monotonic()-start,3),
                                    command=list(map(str,cmd)),log=log.name,sha256=sha(log)))
        save();(out/'running.json').write_text(json.dumps(dict(label=label,finished=True,passed=ok)),encoding='utf-8')
        print(label,'PASS' if ok else 'FAIL',flush=True)
        if not ok:raise RuntimeError(text[-6000:])
    for native in (1,0):
        label='native' if native else 'apint';exe=out/(label+'.exe')
        run(label+'_compile',['D:/mingw64/bin/g++.exe','-O2','-std=c++14','-DS2_NATIVE='+str(native),
                             '-I',snap/'src/hls/m3_s2','-I',HLS/'include',snap/'sim/hls_tb/tb_m3_quant.cpp','-o',exe])
        run(label,[exe],marker='M3_QUANT_PASS')
    if args.hardware:
        for old in (1,0):
            label='old64' if old else 'bounded';name='m3_quant_'+label+'_'+args.tag
            occupancy=subprocess.run(['powershell','-NoProfile','-Command',
                "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],capture_output=True,text=True,check=True)
            (out/(label+'_occupancy.txt')).write_text(occupancy.stdout,encoding='utf-8')
            if occupancy.stdout.strip():raise RuntimeError('hardware occupied')
            build=ROOT/'build/hls/optimization_build'/name
            if build.exists():raise RuntimeError('refuse old project')
            inc=(snap/'src/hls/m3_s2').as_posix()
            flags=f'-std=c++14 -DS2_NATIVE=0 -DM3_QUANT_OLD={old} -I{inc}'
            tcl=out/(label+'.tcl')
            tcl.write_text(f'''cd {{{build.parent.as_posix()}}}
open_project {name}
set_top m3_quant_micro
add_files {{{(snap/'sim/hls_tb/m3_quant_micro.cpp').as_posix()}}} -cflags {{{flags}}}
add_files -tb {{{(snap/'sim/hls_tb/tb_m3_quant_micro.cpp').as_posix()}}} -cflags {{{flags}}}
open_solution sol -flow_target vivado
set_part {{{PART}}}
create_clock -period 5 -name default
csim_design
csynth_design
cosim_design -rtl verilog
set f [open {{{(out/(label+'.done')).as_posix()}}} w]
puts $f "M3_QUANT_HARDWARE_DONE"
close $f
exit
''',encoding='utf-8')
            run(label,['cmd.exe','/c',str(HLS/'bin/vitis_hls.bat'),'-f',tcl],marker='M3_QUANT_MICRO_PASS')
            if not (out/(label+'.done')).exists():raise RuntimeError('missing completion receipt')
            report=build/'sol/syn/report/m3_quant_micro_csynth.xml'
            if not report.exists():raise RuntimeError('missing synthesis report')
            manifest.setdefault('hardware',[]).append(dict(name=name,old=old,xml=str(report.relative_to(ROOT)),sha256=sha(report)))
            save()
    manifest['passed']=True;save();(out/'all.done').write_text('M3_QUANT_ALL_PASS\n')
if __name__=='__main__':main()
