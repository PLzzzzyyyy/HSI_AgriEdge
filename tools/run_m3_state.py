"""Frozen state-field native/ap_int and optional HLS/RTL A/B probe.

Not full-network G2, system timing, or board performance evidence.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
HLS = Path('D:/xilinx/Vitis_HLS/2020.2')
PART = 'xazu5ev-sfvc784-1-i'
SOURCES = [p.relative_to(ROOT).as_posix() for p in (ROOT/'src/hls/m3_s2').glob('*.h')] + [
    'sim/hls_tb/m3_state_micro.h', 'sim/hls_tb/m3_state_micro.cpp',
    'sim/hls_tb/tb_m3_state_micro.cpp', 'tools/run_m3_state.py']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default=datetime.now().strftime('%Y%m%d_%H%M%S'))
    ap.add_argument('--hardware', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch('[a-z0-9_]+', args.tag):
        ap.error('invalid tag')
    out = ROOT/'build/host'/('m3_state_'+args.tag)
    out.mkdir(parents=True, exist_ok=False)
    snap = out/'snapshot'
    for rel in SOURCES:
        dst = snap/rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/rel, dst)
    manifest = dict(scope='state-field only, NOT full network/system/board',
                    part=PART, clock_ns=5, sources={r: sha(snap/r) for r in SOURCES}, runs=[])

    def save():
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def run(label, command, marker=None, timeout=120):
        command = list(map(str, command))
        start = time.monotonic()
        log = out/(label+'.log')
        timed_out = False
        with log.open('wb') as stream:
            proc = subprocess.Popen(command, cwd=out, stdout=stream, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            state = dict(label=label, pid=proc.pid, command=command, log=str(log), finished=False)
            (out/'running.json').write_text(json.dumps(state), encoding='utf-8')
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], check=True,
                               stdout=stream, stderr=subprocess.STDOUT)
                code = proc.wait(timeout=30)
        text = log.read_text(encoding='utf-8', errors='replace')
        ok = not timed_out and code == 0 and 'ERROR:' not in text and (marker is None or marker in text)
        manifest['runs'].append(dict(name=label, command=command, exit=code, passed=ok,
                                    timed_out=timed_out, seconds=round(time.monotonic()-start, 3),
                                    log=log.name, sha256=sha(log)))
        state.update(finished=True, passed=ok, timed_out=timed_out)
        (out/'running.json').write_text(json.dumps(state), encoding='utf-8')
        save()
        print(label, 'PASS' if ok else 'FAIL', flush=True)
        if not ok:
            raise RuntimeError(text[-5000:])

    save()
    for native in (1, 0):
        label = 'native' if native else 'apint'
        flags = ['D:/mingw64/bin/g++.exe', '-O2', '-std=c++14', '-DS2_NATIVE='+str(native),
                 '-I', snap/'src/hls/m3_s2', '-I', HLS/'include']
        for old in (1, 0):
            variant = label+('_old32' if old else '_narrow')
            exe = out/(variant+'.exe')
            run(variant+'_compile', flags+['-DM3_STATE_OLD='+str(old),
                snap/'sim/hls_tb/m3_state_micro.cpp', snap/'sim/hls_tb/tb_m3_state_micro.cpp', '-o', exe])
            run(variant, [exe], 'M3_STATE_MICRO_PASS')
    if args.hardware:
        for old in (1, 0):
            label = 'old32' if old else 'narrow'
            occupancy = subprocess.run(['powershell', '-NoProfile', '-Command',
                "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],
                capture_output=True, text=True, check=True)
            (out/(label+'_occupancy.txt')).write_text(occupancy.stdout, encoding='utf-8')
            if occupancy.stdout.strip():
                raise RuntimeError('hardware occupied')
            name = 'm3_state_'+label+'_'+args.tag
            build = ROOT/'build/hls/optimization_build'/name
            if build.exists():
                raise RuntimeError('refuse existing project')
            flags = f'-std=c++14 -DS2_NATIVE=0 -DM3_STATE_OLD={old} -I{(snap/"src/hls/m3_s2").as_posix()}'
            tcl = out/(label+'.tcl')
            tcl.write_text(f'''cd {{{build.parent.as_posix()}}}
open_project {name}
set_top m3_state_micro
add_files {{{(snap/'sim/hls_tb/m3_state_micro.cpp').as_posix()}}} -cflags {{{flags}}}
add_files -tb {{{(snap/'sim/hls_tb/tb_m3_state_micro.cpp').as_posix()}}} -cflags {{{flags}}}
open_solution sol -flow_target vivado
set_part {{{PART}}}
create_clock -period 5 -name default
csim_design
csynth_design
cosim_design -rtl verilog
set f [open {{{(out/(label+'.done')).as_posix()}}} w]
puts $f "M3_STATE_HARDWARE_DONE"
close $f
exit
''', encoding='utf-8')
            run(label, ['cmd.exe', '/c', HLS/'bin/vitis_hls.bat', '-f', tcl],
                'M3_STATE_MICRO_PASS', timeout=1200)
            report = build/'sol/syn/report/m3_state_micro_csynth.xml'
            if not (out/(label+'.done')).exists() or not report.exists():
                raise RuntimeError('missing completion receipt or synthesis report')
            manifest.setdefault('hardware', []).append(dict(name=name, old=old,
                xml=str(report.relative_to(ROOT)), sha256=sha(report)))
            save()
    manifest['passed'] = True
    save()
    (out/'all.done').write_text('M3_STATE_ALL_PASS\n', encoding='utf-8')


if __name__ == '__main__':
    main()
