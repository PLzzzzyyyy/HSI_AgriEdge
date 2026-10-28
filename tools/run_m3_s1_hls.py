"""Sequential isolated HLS 2020.2 microkernels; never export or build a system."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [('dot_pack', 's1_dot', 8, 2, 1), ('dot_plain', 's1_dot', 8, 2, 0),
           ('copy8_p1', 's1_copy', 8, 1, 1), ('copy8_p2', 's1_copy', 8, 2, 1),
           ('copy18_p2', 's1_copy', 18, 2, 1)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default=datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    ap.add_argument('--only', choices=[c[0] for c in CONFIGS], nargs='+')
    ap.add_argument('--hls', default='D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat')
    args = ap.parse_args()
    out = ROOT / 'build/host' / ('m3_s1_hls_' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for label, top, bits, p, pack in CONFIGS:
        if args.only and label not in args.only:
            continue
        # Inspect before launch; do not kill or resume another task.
        check = subprocess.run(['powershell', '-NoProfile', '-Command',
            "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],
            capture_output=True, text=True, check=True)
        (out / (label + '_occupancy.txt')).write_text(check.stdout, encoding='utf-8')
        if check.stdout.strip():
            raise RuntimeError('Hardware task occupied: ' + check.stdout)
        name = 'm3_s1_' + label + '_' + args.tag
        env = dict(os.environ, S1_NAME=name, S1_TOP=top, S1_BITS=str(bits), S1_P=str(p), S1_PACK=str(pack))
        cmd = [args.hls, '-f', str(ROOT / 'build/hls/run_m3_s1.tcl')]
        log = out / (label + '.log')
        print('START', name, flush=True)
        # HLS is a .bat launcher; use Windows command processor, no FS operations.
        with log.open('w', encoding='utf-8') as f:
            proc = subprocess.Popen(subprocess.list2cmdline(cmd), shell=True, env=env,
                cwd=out, stdout=f, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            (out / 'running.json').write_text(json.dumps(dict(pid=proc.pid, name=name, command=cmd, log=str(log))), encoding='utf-8')
            rc = proc.wait()
        build = ROOT / 'build/hls/optimization_build' / name
        text = log.read_text(encoding='utf-8', errors='replace')
        passed = rc == 0 and all((build / (s + '.done')).exists() for s in ('csim', 'csynth', 'cosim')) and 'ERROR:' not in text
        row = dict(name=name, top=top, bits=bits, p=p, pack=pack, exit_code=rc, passed=passed,
                   log=str(log.relative_to(ROOT)), build=str(build.relative_to(ROOT)))
        xml = build / 'sol/syn/report' / (top + '_csynth.xml')
        if xml.exists():
            tree = ET.parse(xml)
            row['hls_resources'] = {e.tag: e.text for e in tree.findall('.//AreaEstimates/Resources/*')}
            row['hls_latency'] = {e.tag: e.text for e in tree.findall('.//SummaryOfOverallLatency/*')}
            row['estimated_clock_ns'] = tree.findtext('.//EstimatedClockPeriod')
        row['snapshot_sha256'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in (build/'snapshot').glob('*') if f.is_file()}
        results.append(row)
        (out / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        (out / 'running.json').write_text(json.dumps(dict(name=name, finished=True, passed=passed)), encoding='utf-8')
        print('DONE', json.dumps(row), flush=True)
        if not passed:
            return 1
    (out/'all.done').write_text('S1_MICRO_HLS_PASS\n', encoding='utf-8')
    return 0

if __name__ == '__main__':
    sys.exit(main())
