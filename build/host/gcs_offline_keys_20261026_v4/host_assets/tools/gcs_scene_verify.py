"""Read-only full-scene data acceptance. Never opens devices or runs inference.

UART row/whole CRC + downloaded GCS JSON replace manually checking 220,000 words.
This is data acceptance, NOT acceptance of all GCS/DP/S3/model-update features.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'gcs'))
import board_roi as b


def exact(pattern, text, description):
    matches = re.findall(pattern, text, re.M | re.I)
    if len(matches) != 1:
        raise ValueError(f'{description}: expected exactly one record, found {len(matches)}')
    return matches[0]


def verify_uart(text, audit):
    boot = exact(r'^S2C READY boot_id=([0-9a-f]{8})[^\r\n]*\r?$', text, 'READY')
    session, task = exact(r'^S2C FULL_EXEC session=([0-9a-f]{8}) task=(\d+) size=400x550 bound_s=1800\r?$', text, 'FULL_EXEC')
    if (int(boot, 16), int(session, 16), int(task)) != (audit.boot, audit.session, audit.task):
        raise ValueError('UART identity mismatch')
    records = re.findall(r'^S2C FULL_ROW y=(\d+) n=(\d+) crc32=([0-9a-f]{8})\r?$', text, re.M | re.I)
    if len(records) != 550 or {int(r[0]) for r in records} != set(range(550)):
        raise ValueError('UART requires 550 unique row CRC records')
    crcs = {int(y): (int(n), int(crc, 16)) for y, n, crc in records}
    whole = 0
    for y in range(550):
        words = audit.rows.get(y)
        if words is None or len(words) != 400 or any(w is None for w in words):
            raise ValueError(f'UDP row {y} incomplete')
        raw = struct.pack('<400I', *words)
        if crcs[y] != (400, zlib.crc32(raw)):
            raise ValueError(f'UART/UDP row CRC mismatch: {y}')
        whole = zlib.crc32(raw, whole)
    rc, driver, completed, halted, crc = exact(
        r'^S2C FULL_RESULT rc=(-?\d+) driver=(-?\d+) completed=(\d+) halted=(\d+) crc32=([0-9a-f]{8})\r?$',
        text, 'FULL_RESULT')
    if (int(rc), int(driver), int(completed), int(halted), int(crc, 16)) != (0, 0, 220000, 0, whole):
        raise ValueError('UART full result/error/whole CRC mismatch')
    return f'{whole:08x}'


def verify_export(saved, actual):
    for key in ('boot_id', 'session', 'task', 'start_seq', 'scene', 'model', 'wcrc', 'roi',
                'status', 'error', 'full_scene', 'ack', 'received_pixels', 'total', 'class_counts'):
        if saved.get(key) != actual[key]:
            raise ValueError('Export/UDP metadata mismatch: ' + key)
    if len(saved.get('cells', [])) != 220000:
        raise ValueError('Export requires 220000 cells')
    # Compare coordinates and all raw/derived values, not just a histogram/CRC.
    cells = saved['cells']
    if cells != actual['cells']:
        raise ValueError('Export cells differ from complete row-major UDP words')


def verify_s3(text,audit):
    """S3 wait evidence separate from pixel correctness. 1s is the existing
    protocol online lease, NOT an invented PL inference performance target."""
    records=re.findall(r'^S2C S3 scope=scene session=([0-9a-f]{8}) task=(\d+) wait_calls=(\d+) wait_rx=(\d+) max_gap_us=(\d+) max_service_us=(\d+)\r?$',text,re.M|re.I)
    if len(records)!=1:
        return dict(passed=False,reason='Exactly one full-scene S3 receipt required',scope='S3_NOT_VERIFIED')
    session,task,calls,rx,gap,spent=records[0]
    checks=dict(identity=(int(session,16),int(task))==(audit.session,audit.task),
                serviced_during_pl_wait=int(calls)>0,received_during_pl_wait=0<int(rx)<=int(calls),
                within_existing_one_second_lease=int(gap)<1000000 and int(spent)<1000000)
    return dict(passed=all(checks.values()),checks=checks,wait_calls=int(calls),wait_rx=int(rx),
                max_gap_us=int(gap),max_service_us=int(spent),scope='SCENE_PL_WAIT_NETWORK_SERVICE_ONLY')


def verify(run_dir, uart=None, export=None):
    info = json.loads((run_dir / 'session.json').read_text(encoding='utf-8-sig'))
    if info.get('full_scene') is not True or tuple(info['target']) != b.wire.TARGET:
        raise ValueError('Not a full-scene session at the fixed board endpoint')
    job = b.Job(info['boot_id'], info['session'], info['task'], full=True)
    task_finished = False
    with (run_dir / 'packets.jsonl').open(encoding='utf-8-sig') as stream:
        for line in stream:
            packet = json.loads(line)
            data = bytes.fromhex(packet['hex'])
            if tuple(packet['peer']) != b.wire.TARGET:
                if packet['direction'] == 'tx':
                    raise ValueError('TX outside fixed endpoint')
                continue
            if packet.get('phase', 'task') == 'interaction':
                if not task_finished:
                    if not job.finish():raise ValueError(job.error)
                    task_finished = True
                continue  # PROBE is a separate acceptance; cannot alter scene data
            if task_finished:raise ValueError('Task data after interaction phase')
            if packet['direction'] == 'tx':job.sent(data)
            elif packet['direction'] == 'rx':job.receive(data)
            else:raise ValueError('Unknown packet direction')
    if not task_finished and not job.finish():raise ValueError(job.error)
    actual = job.snapshot()
    saved = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8-sig'))
    verify_export(saved, actual)
    checks = dict(udp_220000_unique_ack_done=True, saved_words_exact=True,
                  uart_550_rows_and_whole_crc=False, downloaded_gcs_json_exact=False)
    whole = None
    s3=dict(passed=False,reason='UART missing',scope='S3_NOT_VERIFIED')
    if uart:
        uart_text=uart.read_text(encoding='utf-8-sig')
        whole = verify_uart(uart_text, job.audit)
        s3=verify_s3(uart_text,job.audit)
        checks['uart_550_rows_and_whole_crc'] = True
    if export:
        verify_export(json.loads(export.read_text(encoding='utf-8-sig')), actual)
        checks['downloaded_gcs_json_exact'] = True
    return dict(scope='FULL_SCENE_DATA_ONLY_NOT_ALL_FEATURES', checks=checks,
                data_acceptance=all(checks.values()), boot_id=actual['boot_id'],
                session=actual['session'], task=actual['task'], crc32=whole,
                s3=s3,
                browser_words_sha256=hashlib.sha256(b''.join(struct.pack('<400I',*job.audit.rows[y])
                    for y in range(550))+bytes([1])*220000).hexdigest(),
                missing=[k for k, passed in checks.items() if not passed])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--uart', type=Path)
    parser.add_argument('--export', type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.run_dir, args.uart, args.export)
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps(dict(data_acceptance=False, error=str(exc)), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['data_acceptance'] else 2


if __name__ == '__main__':sys.exit(main())
