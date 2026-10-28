"""Isolated r9 P1 cosim setup, reusing validated synthesis without rebuilding it."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from run_m3_s2_impl import ROOT, dump, require, sha, validate_ooc

HLS = Path('D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat')
SETUP_MARKER = 'S2_RTL_N1_SETUP_COMPLETE_NOT_SIMULATION_PASS'


def setup_completed(receipt, text):
    return (receipt['exit']==0 and not receipt['timed_out'] and
            SETUP_MARKER in text and 'ERROR:' not in text and
            'Invalid attribute' not in text)


def run_stage(out, stage, command, env, timeout=1800, cwd=None):
    """Wait for our child; emit failure/timeout receipts as well as successes."""
    start=time.monotonic()
    with (out/(stage+'.log')).open('wb') as log:
        proc=subprocess.Popen(subprocess.list2cmdline(command), shell=True,
            cwd=cwd or out, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        dump(out/'running.json',dict(stage=stage,pid=proc.pid,command=command,
            cwd=str(cwd or out),started=datetime.now().isoformat(),finished=False))
        timed_out=False
        try:
            code=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=log,stderr=log,check=True)
            code=proc.wait()
    receipt=dict(stage=stage,exit=code,timed_out=timed_out,finished=True,
        seconds=round(time.monotonic()-start,3),log_sha256=sha(out/(stage+'.log')))
    dump(out/(stage+'.json'),receipt)
    dump(out/'running.json',receipt)
    print(json.dumps(receipt),flush=True)
    return receipt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',required=True)
    args=ap.parse_args()
    require(bool(re.fullmatch('[a-z0-9_]+',args.tag)),'Invalid tag')
    ooc=ROOT/'build/host/m3_s2_ooc_20261008_t3_fix_r9_ip'
    receipt=validate_ooc(ooc)
    require(receipt['synth_tag']=='20261008_t3_fix_r9','r9 only')
    occupied=subprocess.run(['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab|xvlog)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],
        capture_output=True,text=True,check=True)
    require(not occupied.stdout.strip(),'Hardware task occupied: '+occupied.stdout)
    out=ROOT/'build/host'/('m3_s2_rtl_'+args.tag)
    out.mkdir(exist_ok=False,parents=True)
    (out/'occupancy.txt').write_text(occupied.stdout)
    prev=ROOT/'build/hls/optimization_build/m3_s2_syn_8p1_pack_20261008_t3_fix_r9'
    project=out/prev.name
    # Keep project basename/solution identity; relocate only hls.app paths.
    shutil.copytree(prev,project)
    app=project/'hls.app'
    app.write_text(app.read_text().replace(prev.as_posix(),project.as_posix()),encoding='utf-8')
    for name in ('tb_m3_s2_rtl_n1.cpp','tb_m3_s2.cpp'):
        shutil.copy2(ROOT/'sim/hls_tb'/name,out/name)
    for path in (Path(__file__),ROOT/'build/hls/setup_m3_s2_rtl_n1.tcl'):
        shutil.copy2(path,out/path.name)
    golden=ROOT/'sim/golden/n6_engine_i8'
    dest=out/'sim/golden/n6_engine_i8'
    (dest/'a').mkdir(parents=True)
    shutil.copy2(golden/'weights_engine.bin',dest/'weights_engine.bin')
    for path in (golden/'a').glob('*.bin'):
        if path.name in ('x_in_i16.bin','class_u32.bin','logits_q16_i32.bin') or re.fullmatch(r'L\d+_x_out_i4.bin',path.name):
            shutil.copy2(path,dest/'a'/path.name)
    inputs={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    dump(out/'inputs.json',dict(scope='P1 n1 DUMP diagnostic, not CLASS_ONLY/n16/P2/system',
        source_project=str(prev),source_ooc=str(ooc),files=inputs))
    env=dict(os.environ,S2_DIAG_PROJECT=project.as_posix(),S2_ROOT=out.as_posix(),
        S2_DIAG_TB=(out/'tb_m3_s2_rtl_n1.cpp').as_posix(),
        S2_WEIGHT_WORDS=str((dest/'weights_engine.bin').stat().st_size//8))
    result=run_stage(out,'setup',[str(HLS),'-f',str(out/'setup_m3_s2_rtl_n1.tcl')],env)
    result['setup_completed']=setup_completed(result,(out/'setup.log').read_text(errors='replace'))
    dump(out/'setup.json',result)
    validate_ooc(ooc)
    return 0 if result['setup_completed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
