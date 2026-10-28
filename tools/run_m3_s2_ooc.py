"""Map completed HLS RTL in isolated Vivado OOC; never a system/G2 PASS gate."""
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
ROOT = Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--synth-tag', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--timeout', type=int, default=10800)
    args = ap.parse_args()
    if not all(re.fullmatch('[a-z0-9_]+', t) for t in (args.tag, args.synth_tag)):
        ap.error('Invalid tag')
    run = ROOT / 'build/host' / ('m3_s2_synth_' + args.synth_tag)
    state = json.loads((run / 'running.json').read_text())
    records = json.loads((run / 'results.json').read_text())
    assert state.get('finished') and len(records) == 1
    row = records[0]
    assert row['synthesis_completed'], 'No completed HLS RTL'
    assert sha(ROOT / row['log']) == row['log_sha256']
    build = ROOT / 'build/hls/optimization_build' / row['name']
    assert (build / 'synth.done').exists()
    for name, digest in row['snapshot'].items():
        assert sha(build / 'snapshot' / name) == digest
        if name.startswith('src/') and name.endswith(('.h', '.cpp')):
            assert sha(ROOT / name) == digest, 'Current source differs from completed HLS'
    check = subprocess.run(['powershell', '-NoProfile', '-Command',
        "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"], capture_output=True, text=True, check=True)
    assert not check.stdout.strip(), 'Hardware task occupied: ' + check.stdout
    out = ROOT / 'build/host' / ('m3_s2_ooc_' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'occupancy.txt').write_text(check.stdout)
    (out / 'rtl').mkdir()
    for p in (build / 'sol/syn/verilog').iterdir():
        if p.is_file(): shutil.copy2(p, out / 'rtl' / p.name)
    for p in (Path(__file__).resolve(), ROOT / 'build/hls/map_m3_s2.tcl'):
        shutil.copy2(p, out / p.name)
    (out / 'clock.xdc').write_text('create_clock -name ap_clk -period 5.000 [get_ports ap_clk]\n')
    inputs = {p.relative_to(out).as_posix(): sha(p) for p in out.rglob('*') if p.is_file()}
    cmd = ['D:/xilinx/Vivado/2020.2/bin/vivado.bat', '-mode', 'batch', '-source', str(out / 'map_m3_s2.tcl'),
           '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    start = time.monotonic()
    print('START_OOC', out.name, flush=True)
    with (out / 'console.log').open('wb') as f:
        proc = subprocess.Popen(subprocess.list2cmdline(cmd), shell=True, cwd=out,
            env=dict(os.environ, S2_OOC_OUT=str(out)), stdout=f, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        (out / 'running.json').write_text(json.dumps(dict(pid=proc.pid, started=datetime.now().isoformat(), command=cmd)))
        timed_out = False
        try: code = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=f, stderr=subprocess.STDOUT)
            proc.wait(); code = -1; timed_out = True
    text = (out / 'console.log').read_text(errors='replace')
    completed = code == 0 and (out / 'mapping.done').exists() and 'S2_VIVADO_OOC_SYNTH_COMPLETE' in text and 'ERROR:' not in text
    result = dict(scope='Full S2 Vivado OOC synthesis mapping only, NOT implementation/timing/G2/RTL/board PASS',
        synth_tag=args.synth_tag, part='xazu5ev-sfvc784-1-i', clock_ns=5.0,
        finished=True, mapping_completed=completed, exit=code, timed_out=timed_out,
        seconds=round(time.monotonic()-start, 3), inputs=inputs,
        artifacts={p.relative_to(out).as_posix(): sha(p) for p in out.iterdir() if p.is_file() and p.name not in inputs and p.name != 'running.json'})
    (out / 'results.json').write_text(json.dumps(result, indent=2))
    (out / 'running.json').write_text(json.dumps(dict(finished=True, mapping_completed=completed)))
    print('DONE_OOC', json.dumps({k:v for k,v in result.items() if k not in ('inputs','artifacts')}), flush=True)
    return 0 if completed else 1
if __name__ == '__main__': sys.exit(main())
