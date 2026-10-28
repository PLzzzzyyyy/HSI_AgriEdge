"""Private GCS S2c adapter. No model/fake-board imports or source-selection UDP."""
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import secrets
import socket
import struct
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import s2c_roi_client as wire
import board_scene
import board_probe

OLD_BOOTS = {0xe4196b84, 0xe86a03b1, 0x64ead9e4}
RECT = [0, 0, 3, 5]  # GCS: row, column, height, width


def now():
    return datetime.now(timezone.utc).isoformat()


class Job:
    """Fail-closed attempt. Cells come only from received ROW words."""
    def __init__(self, boot, session, task, full=False):
        self.full = full
        self.audit = (board_scene.Audit if full else wire.Audit)(boot, session, task)
        self.state, self.error = 'running', None
        self.last_status = None
        self.started, self.ended = now(), None
        self.out = None
        self.interaction = None
        self.rx_pkts = self.rx_bytes = self.tx_pkts = self.tx_bytes = 0

    def fail(self, error):
        if self.state != 'error':  # preserve FIRST failure
            self.state, self.error, self.ended = 'error', str(error), now()

    def sent(self, data):
        if self.state != 'running':
            raise ValueError('terminal attempt cannot send')
        self.audit.sent(data)
        self.tx_pkts += 1
        self.tx_bytes += len(data)

    def receive(self, data):
        if self.state != 'running':
            return
        self.rx_pkts += 1
        self.rx_bytes += len(data)
        try:
            d = self.audit.received(data)
            if d['kind'] == 0x82:
                self.last_status = {k:v for k,v in d.items() if k != 'new_cells'}
            return d
        except Exception as exc:
            self.fail(exc)
            raise

    def finish(self):
        if self.state != 'running':
            return False
        if not self.audit.complete():
            self.fail('Missing ACK / all unique pixels / matching DONE; no retry')
            return False
        self.state, self.ended = 'done', now()
        return True

    def snapshot(self, include_cells=True):
        a = self.audit
        cells = [dict(x=x, y=y, class_word=f'{w:08X}', class_id=w & 255,
                      confidence_q16=w >> 16, confidence=(w >> 16) / 65536)
                 for y, words in sorted(a.rows.items()) for x, w in enumerate(words) if w is not None] if include_cells else []
        width,height=(400,550) if self.full else (5,3)
        count=a.count if self.full else len(a.rows)*5
        counts=a.counts[:] if self.full else [sum((w&255)==k for words in a.rows.values() for w in words) for k in range(9)]
        return dict(boot_id=f'{a.boot:08x}', session=f'{a.session:08x}', task=a.task,
                    start_seq=a.start_seq, scene='longkou', model='v2', wcrc=f'{wire.WCRC:08x}',
                    roi=dict(x=0, y=0, width=width, height=height), status=self.state, error=self.error,
                    full_scene=self.full, class_counts=counts, cells_included=include_cells,
                    ack=a.ack, received_pixels=count, total=width*height, rows=len(a.rows),
                    duplicates=a.duplicates, done_status=a.final, last_status=self.last_status,
                    cells=cells, started=self.started, ended=self.ended,
                    evidence=str(self.out) if self.out else None,
                    temperature=None, power=None, performance=None, phy=None,
                    scope=('Full LongKou scene' if self.full else 'Fixed ROI')+'; not full v1/OA/performance/soak',
                    uart_verified=False,
                    interaction=self.interaction.snapshot() if self.interaction else None)


def csv_text(snapshot):
    s = io.StringIO(newline='')
    w = csv.DictWriter(s, fieldnames=['boot_id', 'session', 'task', 'x', 'y',
                                    'class_word', 'class_id', 'confidence_q16', 'confidence'])
    w.writeheader()
    for c in snapshot['cells']:
        w.writerow({**{k: snapshot[k] for k in ('boot_id', 'session', 'task')}, **c})
    return s.getvalue()


class BoardSource:
    name = 'board'
    addr = wire.TARGET

    def __init__(self, root=None):
        self.root = root or ROOT / 'build/host/gcs_roi'
        self.boot = None
        self.job = None
        self.worker = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()

    def authorize(self, text, confirmed):
        if confirmed is not True:
            raise ValueError('Explicit new business-App cold-start confirmation required')
        try:
            boot = wire.boot_value(text)
        except (TypeError, wire.argparse.ArgumentTypeError) as exc:
            raise ValueError(str(exc)) from exc
        if boot in OLD_BOOTS or not boot:
            raise ValueError('Fresh eight-digit boot_id required; old IDs forbidden')
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('Attempt still active')
            if (self.root / 'boots' / f'{boot:08x}.json').exists():
                raise ValueError('Boot already consumed; no second START/retry')
            self.boot = boot
        return self.describe()

    def validate(self, cmd):
        small=cmd.get('kind')=='region' and cmd.get('rect')==RECT
        scan=cmd.get('kind')=='scan' and cmd.get('rect') in (None,[0,0,550,400])
        if cmd.get('scene')!='longkou' or cmd.get('version')!='v2' or not(small or scan):
            raise ValueError('Board scope: LongKou/v2 full scene or fixed 5x3 ROI only')
        if self.boot is None:
            raise ValueError('New App startup/boot_id not confirmed; no UDP sent')
        if (self.root / 'boots' / f'{self.boot:08x}.json').exists():
            raise ValueError('Boot already consumed; no second START')

    def describe(self):
        active = bool(self.worker and self.worker.is_alive())
        used = self.boot is not None and (self.root / 'boots' / f'{self.boot:08x}.json').exists()
        return dict(source='board', label='真实板卡 · LongKou/v2', board_ip=self.addr[0],
                    board_port=self.addr[1], link='unknown', phy='未测', active=active,
                    authorized=self.boot is not None and not used,
                    boot_id=f'{self.boot:08x}' if self.boot is not None else None,
                    protocol='v1已实现子集（无v0模拟板兼容）', used=used)

    def telemetry(self):
        j = self.job
        return dict(device='AXU5EV-E · 温度/功率/性能/PHY未测', temp_c=None, power_w=None,
                    ms_per_px=None, lost=None, rx_pkts=j.rx_pkts if j else 0,
                    rx_bytes=j.rx_bytes if j else 0, tx_pkts=j.tx_pkts if j else 0,
                    tx_bytes=j.tx_bytes if j else 0)

    def start(self, run, on_chunk, on_done, pace_rows=0, on_update=None):
        self.validate(dict(kind=run.kind, scene=run.scene, version=run.version, rect=run.rect))
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('Previous board session still open; close it explicitly first')
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / 'boots').mkdir(exist_ok=True)
            # Durable exclusive claim survives source switches and service restart.
            with (self.root / 'boots' / f'{self.boot:08x}.json').open('x', encoding='utf-8') as f:
                json.dump(dict(boot_id=f'{self.boot:08x}', claimed=now(), run=run.id), f)
            j = self.job = Job(self.boot, secrets.randbits(32), secrets.randbelow(65535) + 1, run.kind=='scan')
            j.out = self.root / datetime.now().strftime('attempt_%Y%m%d_%H%M%S_%f')
            j.out.mkdir(exist_ok=False)
            run.board_job = j
            self.cancel.clear()

        def update(chunk=None, final=False):
            snap = j.snapshot(include_cells=not j.full or final)
            (j.out / 'summary.json').write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
            if not j.full or final:
                (j.out / 'results.csv').write_text(csv_text(snap), encoding='utf-8-sig')
            if on_update:
                event=j.snapshot(include_cells=not j.full)
                if chunk:event['chunk']=chunk
                on_update(event)

        def work():
            notified = False
            try:
                info = dict(boot_id=j.audit.boot, session=j.audit.session, task=j.audit.task, full_scene=j.full,
                            target=list(self.addr), started=j.started, source_sha256=wire.sha(Path(__file__)),
                            client_sha256=wire.sha(Path(wire.__file__)),
                            sources={str(Path(m.__file__).relative_to(ROOT)):wire.sha(Path(m.__file__))
                                     for m in (board_scene,board_probe,wire)})
                (j.out / 'session.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
                update()
                with (j.out / 'packets.jsonl').open('x', encoding='utf-8') as trace, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.bind(('', 0))
                    sock.settimeout(.05)
                    # App execution bound is 1800 s. Leave 30 s to receive its
                    # terminal error/CRC instead of dropping the peer first.
                    limit=1830 if j.full else 30
                    end = time.monotonic() + limit
                    handshake_end = time.monotonic() + 5
                    seq, next_ping = 0, 0
                    emitted = set()
                    last_rx=time.monotonic()
                    done_at=None

                    def record(direction, data, peer):
                        trace.write(json.dumps(dict(direction=direction, monotonic_ns=time.perf_counter_ns(),
                                                    phase='interaction' if j.state=='done' else 'task',
                                                    peer=list(peer), hex=data.hex())) + '\n')
                        trace.flush()

                    def send(data):
                        j.sent(data)
                        record('tx', data, self.addr)
                        if sock.sendto(data, self.addr) != len(data):
                            raise OSError('short UDP send')

                    while time.monotonic() < end:
                        if self.cancel.is_set():
                            raise RuntimeError('Local receive cancelled; no STOP sent; board state requires user check')
                        t = time.monotonic()
                        stamp = (time.perf_counter_ns() // 1000) & 0xffffffff
                        if t >= next_ping:
                            send(wire.packet(5, j.audit.task if j.audit.start_seq is not None else 0,
                                             seq, stamp, struct.pack('<I', j.audit.session)))
                            seq = (seq + 1) & 65535
                            next_ping = t + .25
                        if j.audit.ready and j.audit.have_pong and j.audit.start_seq is None:
                            factory=board_scene.start_packet if j.full else wire.start_packet
                            send(factory(j.audit.task, seq, stamp, j.audit.session))
                            seq = (seq + 1) & 65535
                            update()
                        if j.audit.start_seq is None and t >= handshake_end:
                            raise TimeoutError('Fresh App identity/idle handshake timeout; no START sent')
                        if t-last_rx>30:
                            raise TimeoutError('30s without board receipt; no retry')
                        if done_at is not None and t-done_at>2:
                            raise TimeoutError('DONE received but pixels missing after bounded drain; no retry')
                        try:
                            data, peer = sock.recvfrom(2048)
                        except socket.timeout:
                            continue
                        record('rx', data, peer)
                        if peer != self.addr:
                            continue
                        last_rx=time.monotonic()
                        d=j.receive(data)
                        if j.audit.final is not None and done_at is None:done_at=last_rx
                        chunk=d.get('new_cells',[]) if j.full else []
                        if j.full and chunk:
                            import numpy as np
                            on_chunk(np.array([[c['y'],c['x']] for c in chunk]),
                                     np.array([c['class_id']+1 for c in chunk],dtype=np.uint8),
                                     np.array([c['confidence'] for c in chunk]))
                        for y, words in ([] if j.full else sorted(j.audit.rows.items())):
                            if y not in emitted:
                                # Existing map reserves label0 for NO DATA. Raw ID stays zero-based.
                                import numpy as np
                                on_chunk(np.array([[y, x] for x in range(5)]),
                                         np.array([(w & 255) + 1 for w in words], dtype=np.uint8),
                                         np.array([(w >> 16) / 65536 for w in words]))
                                emitted.add(y)
                        update(chunk=chunk)
                        if j.audit.complete():
                            # Bounded drain catches queued conflicting ROW / failure ACK.
                            quiet = min(end, time.monotonic() + .20)
                            while time.monotonic() < quiet:
                                try:
                                    data, peer = sock.recvfrom(2048)
                                except socket.timeout:
                                    continue
                                record('rx', data, peer)
                                if peer == self.addr:
                                    j.receive(data)
                            j.finish()
                            break
                    if j.state == 'running':
                        j.fail(f'{limit}s bound: missing ACK / all unique pixels / matching DONE; no retry')
                    if j.state == 'done':
                        # Keep precisely this socket/peer. The finite passive window
                        # never sends idle heartbeats or silently extends its deadline.
                        j.interaction = board_probe.Session(j.audit, j.full, time.monotonic())
                        update(final=True)
                        notified = True
                        on_done('done')
                        previous = None
                        while not self.cancel.is_set():
                            packets, seq = j.interaction.poll(time.monotonic(), seq,
                                (time.perf_counter_ns() // 1000) & 0xffffffff)
                            for packet in packets:
                                record('tx', packet, self.addr)
                                if sock.sendto(packet, self.addr) != len(packet):
                                    raise OSError('short probe UDP send')
                                j.tx_pkts += 1
                                j.tx_bytes += len(packet)
                            view = j.interaction.snapshot()
                            if view != previous:
                                previous = view
                                (j.out / 'interaction.json').write_text(json.dumps(dict(
                                    boot_id=f'{j.audit.boot:08x}', session=f'{j.audit.session:08x}',
                                    task=j.audit.task, **view, history=j.interaction.history), indent=2), encoding='utf-8')
                                if on_update:
                                    on_update(j.snapshot(include_cells=not j.full))
                            if view['state'] != 'open':
                                break
                            try:
                                data, peer = sock.recvfrom(2048)
                            except socket.timeout:
                                continue
                            record('rx', data, peer)
                            if peer == self.addr:
                                j.rx_pkts += 1
                                j.rx_bytes += len(data)
                                j.interaction.receive(data)
                        j.interaction.close('User closed the post-task session')
            except Exception as exc:
                if j.state == 'done' and j.interaction:
                    j.interaction.close(f'{type(exc).__name__}: {exc}')
                else:
                    j.fail(f'{type(exc).__name__}: {exc}')
            finally:
                try:
                    if j.interaction:
                        (j.out / 'interaction.json').write_text(json.dumps(dict(
                            boot_id=f'{j.audit.boot:08x}', session=f'{j.audit.session:08x}',
                            task=j.audit.task, **j.interaction.snapshot(), history=j.interaction.history), indent=2), encoding='utf-8')
                    update(final=True)
                except Exception as exc:
                    j.fail(f'Evidence write failure: {exc}')
                if not notified:
                    on_done('done' if j.state == 'done' else 'error:' + str(j.error))

        self.worker = threading.Thread(target=work, name='gcs-real-roi', daemon=False)
        self.worker.start()

    def pause(self):
        raise ValueError('PAUSE/RESUME/STOP are outside this board subset')

    resume = pause
    stop = pause

    def close(self):
        if self.worker and self.worker.is_alive():
            if not self.job or self.job.state != 'done':
                raise ValueError('Board attempt still receiving; cannot switch source')
            self.shutdown()

    def probe(self, job, row, col):
        with self.lock:
            if job is not self.job or not job or job.state != 'done' or not job.interaction:
                raise ValueError('Probe requires this completed task and its original live session')
            if not self.worker or not self.worker.is_alive():
                raise ValueError('Original UDP session has exited; no new socket is opened')
            return job.interaction.request(row, col, time.monotonic())

    def shutdown(self):
        self.cancel.set()
        if self.worker:
            self.worker.join(timeout=3)
            if self.worker.is_alive():
                raise RuntimeError('GCS ROI client did not exit')

    def upload_weights(self, *args):
        raise ValueError('Weight upload is outside this board subset')
