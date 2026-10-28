"""Offline request/receipt fixtures only; no real or simulated network board."""
from pathlib import Path
import queue
import json
import struct
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'gcs'))
import board_roi as b
import board_probe as p
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import gcs_probe_verify as verify_probe
if __package__:
    from .test_gcs_roi import status, ack, row
else:
    from test_gcs_roi import status, ack, row
w = b.wire


def logits(req=11, task=7, x=0, y=0, word=0x12340000, crc=w.WCRC):
    return w.packet(0x85, task, 9, 99, struct.pack('<HBBHHII9i',
        req, 0, 9, y, x, crc, word, 65536, 0, -1, -2, -3, -4, -5, -6, -7))


def pong(seq=10, stamp=100):
    return w.packet(0x84, 7, 9, 101, struct.pack('<HHII', seq, 0, stamp, 100))


class ProbeTests(unittest.TestCase):
    def session(self):
        self.audit = SimpleNamespace(boot=0x12345678, session=42, task=7, rows={0:[0x12340000]*5})
        return p.Session(self.audit, False, 0)

    def start(self, s):
        s.request(0, 0, 1)
        packets, seq = s.poll(1, 10, 100)
        self.assertEqual([x[2] for x in packets], [5, 9])
        self.assertEqual(seq, 12)
        return packets

    def test_idle_is_passive_fixed_deadline_and_no_resurrection(self):
        s = self.session()
        self.assertEqual(s.poll(200, 10, 100), ([], 10))
        s.poll(300, 10, 100)
        self.assertEqual(s.snapshot()['state'], 'closed')
        with self.assertRaises(ValueError):s.request(0, 0, 301)

    def test_identity_pong_logits_all_required_and_probabilities_are_derived(self):
        s = self.session(); self.start(s)
        s.receive(logits());s.receive(pong())
        self.assertEqual(s.current['state'], 'running')
        s.receive(status(7, 3))
        self.assertEqual(s.current['state'], 'done')
        self.assertAlmostEqual(sum(s.current['probabilities']), 1)
        self.assertEqual(s.current['logits_q16'][0], 65536)
        self.assertEqual(self.audit.rows[0][0], 0x12340000)
        s.close('user'); self.assertEqual(s.current['state'], 'done')

    def test_retries_same_sequence_bytes_no_new_inference_and_finite(self):
        s = self.session(); packets = self.start(s)
        for clock in (2, 3):self.assertEqual(s.poll(clock, 12, 999), ([packets[1]], 12))
        self.assertEqual(s.poll(4, 12, 999), ([], 12))
        s.poll(6, 12, 999);first=s.current['error']
        s.receive(logits());s.receive(status(7,3));s.receive(pong())
        self.assertEqual((s.current['state'], s.current['error']), ('error', first))

    def test_error_isolation_and_first_failure(self):
        for receipt in (logits(task=8), logits(x=1), logits(crc=1), logits(word=0x56780000),
                        status(7,3,boot=1), logits()[:-1], logits(word=0x12340001)):
            with self.subTest(receipt=receipt.hex()):
                s=self.session();self.start(s);s.receive(receipt);first=s.current['error']
                self.assertEqual(s.current['state'],'error');self.assertIsNotNone(first)
                s.receive(logits());self.assertEqual(s.current['error'],first)
                self.assertEqual(self.audit.rows[0][0],0x12340000)

    def test_pending_gate_old_seq_and_late_conflicting_duplicate(self):
        s=self.session();self.start(s)
        with self.assertRaises(ValueError):s.request(0,1,1)
        s.receive(logits(req=9));self.assertEqual(s.current['state'],'running')
        s.receive(logits());s.receive(status(7,3));s.receive(pong())
        changed=bytearray(logits());struct.pack_into('<i',changed,32,-100)
        s.receive(bytes(changed));self.assertEqual(s.current['state'],'error')
        self.assertIn('Conflicting',s.current['error'])

    def test_ack_failure_and_coordinate_validation(self):
        s=self.session()
        for r,c in ((-1,0),(550,0),(0,400),(True,0),(1.2,0)):
            with self.assertRaises(ValueError):s.request(r,c,0)
        self.start(s)
        s.receive(w.packet(0x83,7,0,0,struct.pack('<BBHI',9,6,11,0xfffffffb)))
        self.assertIn('code=6',s.current['error'])

    def test_readonly_uart_udp_probe_crosscheck_and_missing_or_duplicate_logit(self):
        s=self.session();packets=self.start(s)
        s.receive(logits());s.receive(pong());s.receive(status(7,3))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'session.json').write_text(json.dumps(dict(boot_id=self.audit.boot,session=42,task=7)))
            saved=dict(boot_id='12345678',session='0000002a',task=7,history=[],probe=s.current)
            (root/'interaction.json').write_text(json.dumps(saved))
            records=[]
            for direction,data in [('tx',packets[0]),('tx',packets[1]),('rx',pong()),('rx',status(7,3)),('rx',logits())]:
                records.append(dict(phase='interaction',direction=direction,hex=data.hex(),peer=list(w.TARGET),monotonic_ns=len(records)+1))
            (root/'packets.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
            uart='S2C PROBE session=0000002a task=7 seq=11 x=0 y=0 class_word=12340000\n'
            uart+=''.join(f'S2C LOGIT seq=11 class={i} q16={q}\n' for i,q in enumerate(s.current['logits_q16']))
            with patch.object(b.socket,'socket',side_effect=AssertionError('No socket')):
                self.assertTrue(verify_probe.verify(root,uart)['passed'])
                self.assertFalse(verify_probe.verify(root,uart+'S2C LOGIT seq=11 class=0 q16=65536\n')['passed'])
                self.assertFalse(verify_probe.verify(root,uart.replace('task=7','task=8'))['passed'])
                self.assertFalse(verify_probe.verify(root,'')['passed'])

    def test_original_socket_retained_done_notified_once_and_explicit_close(self):
        class FixtureSocket:
            def __init__(self):self.receipts=queue.Queue();self.sent=[];self.started=False;self.closed=False
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def bind(self,addr):self.bound=addr
            def settimeout(self,t):self.timeout=t
            def sendto(self,data,peer):
                self.sent.append(data)
                _,kind,_,task,seq,stamp=w.HEADER.unpack_from(data)
                if kind==5:
                    session=struct.unpack_from('<I',data,12)[0]
                    self.receipts.put(w.packet(0x84,task,0,0,struct.pack('<HHII',seq,0,stamp,0)))
                    self.receipts.put(status(task if self.started else 0,3 if self.started else 0,session=session))
                elif kind==1:
                    self.started=True
                    self.receipts.put(ack(task,seq))
                    for y in range(3):self.receipts.put(row(y,task))
                    self.receipts.put(status(task,3,session=42))
                elif kind==9:self.receipts.put(logits(seq,task))
                else:raise AssertionError('unexpected command')
                return len(data)
            def recvfrom(self,n):
                try:return self.receipts.get(timeout=self.timeout),w.TARGET
                except queue.Empty:raise b.socket.timeout()
        fixture=FixtureSocket();done=threading.Event();events=[]
        with tempfile.TemporaryDirectory() as tmp, patch.object(b.socket,'socket',return_value=fixture) as factory, \
             patch.object(b.secrets,'randbits',return_value=42), patch.object(b.secrets,'randbelow',return_value=6):
            source=b.BoardSource(Path(tmp));source.authorize('12345678',True)
            run=SimpleNamespace(id=1,kind='region',scene='longkou',version='v2',rect=b.RECT)
            source.start(run,lambda *x:None,lambda reason:(events.append(reason),done.set()))
            try:
                self.assertTrue(done.wait(3));self.assertEqual(events,['done'])
                self.assertTrue(source.worker.is_alive());self.assertFalse(fixture.closed)
                before=len(fixture.sent);time.sleep(.12);self.assertEqual(len(fixture.sent),before)
                source.probe(run.board_job,0,0)
                until=time.monotonic()+2
                while time.monotonic()<until and run.board_job.interaction.snapshot()['probe']['state'] not in ('done','error'):
                    time.sleep(.01)
                self.assertEqual(run.board_job.interaction.snapshot()['probe']['state'],'done')
                self.assertEqual(run.board_job.state,'done');self.assertEqual(factory.call_count,1)
            finally:source.shutdown()
            self.assertFalse(source.worker.is_alive());self.assertTrue(fixture.closed);self.assertEqual(events,['done'])
            with self.assertRaises(ValueError):source.probe(run.board_job,0,0)


if __name__ == '__main__':unittest.main(verbosity=2)
