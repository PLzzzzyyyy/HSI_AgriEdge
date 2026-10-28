"""Implement a verified S2 OOC checkpoint in a new directory, never a system/P2 gate."""
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VIVADO = Path('D:/xilinx/Vivado/2020.2/bin/vivado.bat')
MARKER = 'S2_OOC_IMPLEMENTATION_COMPLETE_NOT_SYSTEM_OR_TIMING_PASS'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def validate_ooc(ooc):
    state = json.loads((ooc / 'running.json').read_text())
    receipt = json.loads((ooc / 'results.json').read_text())
    require(state.get('finished') and receipt.get('finished') and
            receipt.get('mapping_completed') and receipt.get('exit') == 0 and
            not receipt.get('timed_out'), 'OOC synthesis not completed')
    require((ooc / 'mapping.done').is_file(), 'Missing synthesis marker')
    require(receipt['part'] == 'xazu5ev-sfvc784-1-i' and receipt['clock_ns'] == 5.0,
            'Unexpected part or clock')
    for name, digest in {**receipt['inputs'], **receipt['artifacts']}.items():
        require(sha(ooc / name) == digest, 'OOC hash mismatch: ' + name)
    with zipfile.ZipFile(ooc / 's2_engine_ooc.dcp') as archive:
        metadata = ET.fromstring(archive.read('dcp.xml'))
    require(metadata.find('Top').get('Name') == 's2_engine' and
            metadata.find('OutOfContext').get('Name') == '1' and
            metadata.find('Part').get('Name') == receipt['part'], 'DCP metadata mismatch')
    synth = ROOT / 'build/host' / ('m3_s2_synth_' + receipt['synth_tag'])
    rows = json.loads((synth / 'results.json').read_text())
    require(json.loads((synth / 'running.json').read_text()).get('finished') and
            len(rows) == 1 and rows[0]['synthesis_completed'], 'HLS not complete')
    row = rows[0]
    require('8p1_pack' in row['name'], 'This diagnostic entry is P1 W8 only')
    build = ROOT / 'build/hls/optimization_build' / row['name']
    require((build / 'synth.done').is_file(), 'Missing HLS marker')
    require(sha(ROOT / row['log']) == row['log_sha256'], 'HLS log hash mismatch')
    for name, digest in row['snapshot'].items():
        require(sha(build / 'snapshot' / name) == digest, 'HLS snapshot mismatch: ' + name)
        if name.startswith('src/'):
            require(sha(ROOT / name) == digest, 'Current source mismatch: ' + name)
    for name, digest in receipt['inputs'].items():
        if name.startswith('rtl/'):
            require(sha(build / 'sol/syn/verilog' / Path(name).name) == digest,
                    'HLS/OOC RTL mismatch: ' + name)
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ooc-tag', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--timeout', type=int, default=10800)
    args = ap.parse_args()
    if not all(re.fullmatch('[a-z0-9_]+', tag) for tag in (args.tag, args.ooc_tag)):
        ap.error('Invalid tag')
    if args.timeout <= 0:
        ap.error('Timeout must be positive')
    ooc = ROOT / 'build/host' / ('m3_s2_ooc_' + args.ooc_tag)
    receipt = validate_ooc(ooc)
    require(VIVADO.is_file(), 'Vivado 2020.2 not found')
    check = subprocess.run(['powershell', '-NoProfile', '-Command',
        "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab|xvlog)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],
        capture_output=True, text=True, check=True)
    require(not check.stdout.strip(), 'Hardware task occupied: ' + check.stdout)
    out = ROOT / 'build/host' / ('m3_s2_impl_' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'occupancy.txt').write_text(check.stdout, encoding='utf-8')
    shutil.copy2(ooc / 's2_engine_ooc.dcp', out / 'input.dcp')
    for path in (Path(__file__).resolve(), ROOT / 'build/vivado/impl_m3_s2_ooc.tcl'):
        shutil.copy2(path, out / path.name)
    for name in ('results.json', 'mapping.done', 'clock.xdc'):
        shutil.copy2(ooc / name, out / ('source_' + name))
    inputs = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    require(inputs['input.dcp'] == receipt['artifacts']['s2_engine_ooc.dcp'],
            'Copied DCP mismatch')
    cmd = [str(VIVADO), '-mode', 'batch', '-source', str(out / 'impl_m3_s2_ooc.tcl'),
           '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    start = time.monotonic()
    print('START_OOC_IMPL', out.name, flush=True)
    code, timed_out, error = -1, False, None
    proc = None
    with (out / 'console.log').open('wb') as log:
        try:
            proc = subprocess.Popen(subprocess.list2cmdline(cmd), shell=True, cwd=out,
                env=dict(os.environ, S2_IMPL_OUT=str(out)), stdout=log,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            dump(out / 'running.json', dict(pid=proc.pid, command=cmd,
                 started=datetime.now().isoformat(), finished=False))
            try:
                code = proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
                code = proc.wait()
        except Exception as exc:
            error = repr(exc)
            # Never publish a finished receipt while our child is still alive.
            if proc is not None and proc.poll() is None:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
                code = proc.wait()
    text = (out / 'console.log').read_text(errors='replace')
    completed = (code == 0 and not timed_out and error is None and
                 (out / 'implementation.done').is_file() and MARKER in text and
                 (out / 's2_engine_routed.dcp').is_file() and 'ERROR:' not in text)
    result = dict(scope='P1 W8 full core OOC place/route only; NOT PS/AXI system, P2, RTL or board PASS',
        ooc_tag=args.ooc_tag, synth_tag=receipt['synth_tag'], part=receipt['part'], clock_ns=5.0,
        finished=True, implementation_completed=completed, exit=code, timed_out=timed_out,
        error=error, seconds=round(time.monotonic() - start, 3), inputs=inputs,
        artifacts={p.name: sha(p) for p in out.iterdir() if p.is_file() and
                   p.name not in inputs and p.name != 'running.json'})
    dump(out / 'results.json', result)
    dump(out / 'running.json', dict(finished=True, implementation_completed=completed))
    print('DONE_OOC_IMPL', json.dumps({k: v for k, v in result.items()
                                     if k not in ('inputs', 'artifacts')}), flush=True)
    return 0 if completed else 1


if __name__ == '__main__':
    sys.exit(main())
