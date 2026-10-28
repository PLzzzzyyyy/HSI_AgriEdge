"""Bounded post-task PROBE state machine. No sockets, model imports or inference.

The caller retains the original UDP peer. Only an explicit request emits traffic;
idle sessions expire after five minutes, without heartbeat or deadline extension.
"""
import math
import struct
import threading
import board_scene

wire = board_scene.wire
SESSION_SECONDS = 300
REQUEST_SECONDS = 5


def decode(data):
    if len(data) < 12 or data[2] != 0x85:
        return board_scene.decode(data)
    magic, kind, ver, task, seq, stamp = wire.HEADER.unpack_from(data)
    if magic != 0x4548 or ver != 1 or len(data) != 64:
        raise ValueError('LOGITS header/version/length')
    req, scene, ncls, row, col, wcrc, word = struct.unpack_from('<HBBHHII', data, 12)
    if scene or ncls != 9 or row >= 550 or col >= 400 or word & 0xff00 or word & 255 > 8:
        raise ValueError('LOGITS scene/shape/CLASS')
    logits = list(struct.unpack_from('<9i', data, 28))
    if logits[word & 255] != max(logits):
        raise ValueError('CLASS/logits argmax mismatch')
    return dict(kind=kind, task=task, seq=seq, t_us=stamp, req_seq=req,
                scene=scene, row=row, col=col, wcrc=wcrc, class_word=f'{word:08X}',
                class_id=word & 255, confidence_q16=word >> 16, logits_q16=logits)


class Session:
    def __init__(self, audit, full, clock):
        self.audit, self.full = audit, full
        self.deadline = clock + SESSION_SECONDS
        self.state, self.reason = 'open', None
        self.current = None
        self.history = []
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return dict(state=self.state, reason=self.reason, max_seconds=SESSION_SECONDS,
                        idle_heartbeat=False, probe=dict(self.current) if self.current else None)

    def fail(self, error):
        if self.current and self.current['state'] in ('queued', 'running', 'done'):
            self.current.update(state='error', error=str(error))

    def close(self, reason):
        with self.lock:
            if self.state == 'open':
                if self.current and self.current['state'] in ('queued', 'running'):
                    self.fail(reason)
                self.state, self.reason = 'closed', str(reason)

    def request(self, row, col, clock):
        with self.lock:
            if self.state != 'open' or clock >= self.deadline:
                raise ValueError('Probe session closed/expired; no peer migration or second START')
            if type(row) is not int or type(col) is not int or not 0 <= row < 550 or not 0 <= col < 400:
                raise ValueError('Probe coordinate outside LongKou')
            if self.current and self.current['state'] in ('queued', 'running'):
                raise ValueError('One probe already pending')
            if self.current:
                self.history.append(dict(self.current))
                self.history = self.history[-32:]
            self.current = dict(state='queued', row=row, col=col, error=None, req_seq=None)
            return dict(self.current)

    def poll(self, clock, seq, stamp):
        """Worker only: return packets plus next sequence; no idle traffic."""
        with self.lock:
            if clock >= self.deadline:
                self.close('Five-minute post-task session expired')
            if self.state != 'open' or not self.current:
                return [], seq
            c = self.current
            if c['state'] == 'queued':
                req = (seq + 1) & 65535
                self.ping_seq, self.ping_stamp = seq, stamp
                self.have_status = self.have_pong = False
                self.result = None
                self.request_end, self.retry_at, self.attempts = clock + REQUEST_SECONDS, clock + 1, 1
                self.packet = wire.packet(9, self.audit.task, req, stamp,
                    struct.pack('<BBHHHI', 0, 0, c['row'], c['col'], 0, wire.WCRC))
                c.update(state='running', req_seq=req)
                return [wire.packet(5, self.audit.task, seq, stamp, struct.pack('<I', self.audit.session)),
                        self.packet], (req + 1) & 65535
            if c['state'] == 'running':
                if clock >= self.request_end:
                    self.fail('Probe timeout: LOGITS and fresh identity/PONG required')
                elif clock >= self.retry_at and self.attempts < 3:
                    # Same sequence and exact bytes: board returns cached result, never recomputes.
                    self.retry_at, self.attempts = clock + 1, self.attempts + 1
                    return [self.packet], seq
            return [], seq

    def receive(self, data):
        with self.lock:
            try:
                d = decode(data)
                if d['kind'] == 0x82:
                    a = self.audit
                    total = 220000 if self.full else 15
                    if (d['boot_id'], d['session'], d['task'], d['wcrc'], d['state'], d['done'], d['total']) != (
                            a.boot, a.session, a.task, wire.WCRC, 3, total, total):
                        raise ValueError('Post-task boot/session/task/model/state mismatch')
                    if self.current and self.current['state'] == 'running':
                        self.have_status = True
                elif d['kind'] == 0x84:
                    if self.current and self.current['state'] == 'running':
                        if (d['task'], d['ping_seq'], d['t1']) == (self.audit.task, self.ping_seq, self.ping_stamp):
                            self.have_pong = True
                elif d['kind'] in (0x85, 0x83):
                    c = self.current
                    if not c or c['state'] not in ('running', 'done'):
                        return  # late response cannot resurrect an errored request
                    req = d['req_seq'] if d['kind'] == 0x85 else d['acked_seq']
                    if req != c['req_seq']:
                        return  # old request is isolated; no chance to satisfy the new one
                    if d['task'] != self.audit.task:
                        raise ValueError('Probe task mismatch')
                    if d['kind'] == 0x83:
                        if d['acked_type'] == 9:
                            raise ValueError(f"Probe ACK failure code={d['code']} value={d['value']:08x}")
                        return
                    if (d['row'], d['col'], d['wcrc']) != (c['row'], c['col'], wire.WCRC):
                        raise ValueError('Probe coordinate/model mismatch')
                    row = self.audit.rows.get(c['row'], [])
                    previous = row[c['col']] if c['col'] < len(row) else None
                    if previous is not None and d['class_word'] != f'{previous:08X}':
                        raise ValueError('Probe CLASS differs from committed task ROW')
                    result = {k: d[k] for k in ('class_word', 'class_id', 'confidence_q16', 'logits_q16')}
                    if self.result is not None and self.result != result:
                        raise ValueError('Conflicting duplicate LOGITS')
                    self.result = result
                # Completion is gated by new PONG + STATUS, not previous task success.
                if self.current and self.current['state'] == 'running' and self.result and self.have_status and self.have_pong:
                    q = self.result['logits_q16']
                    exp = [math.exp((v - max(q)) / 65536) for v in q]
                    self.current.update(self.result, state='done', probabilities=[v / sum(exp) for v in exp],
                        probability_source='CPU softmax of board Q16 logits; not PC model inference',
                        attention_source='not returned by board', spectrum_source='not returned by board')
            except Exception as exc:
                self.fail(exc)
                self.close(exc)
