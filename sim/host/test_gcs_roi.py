"""New GCS adapter regressions; offline packet fixtures, never board traffic."""
import csv
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'gcs'))
import board_roi as b
w = b.wire


def status(task=0, state=0, boot=0x12345678, session=42, done=None, wcrc=w.WCRC):
    done = (15 if state == 3 else 0) if done is None else done
    body = struct.pack('<IIfffBBH', done, 15 if task else 0, *([float('nan')]*3), state, 0, 0)
    tail = struct.pack('<IIIHBB8IHHI', boot, session, wcrc, 3 if state == 3 else 0, 1, 0, *([0]*8), 0, 0, 0)
    return w.packet(0x82, task, 1, 99, body+tail)


def ack(task=7, seq=1, code=0):
    return w.packet(0x83, task, 3, 100, struct.pack('<BBHI', 1, code, seq, 0))


def row(y, task=7, word=0x12340000):
    return w.packet(0x81, task, 4+y, 101, struct.pack('<HHHH5I', y, 0, 5, 0, *([word]*5)))


class GcsAdapterTests(unittest.TestCase):
    def job(self):
        j=b.Job(0x12345678,42,7)
        j.sent(w.packet(5,0,0,123,struct.pack('<I',42)))
        j.receive(w.packet(0x84,0,0,126,struct.pack('<HHII',0,0,123,125)))
        j.receive(status())
        j.sent(w.start_packet(7,1,127,42))
        return j

    def test_exact_cells_no_reference_or_inference(self):
        j=self.job()
        with patch.object(w,'reference',side_effect=AssertionError('must not read history')):
            j.receive(row(1,word=0xFEDC0008))
            s=j.snapshot()
        self.assertEqual(s['received_pixels'],5)
        self.assertEqual(s['cells'][0],dict(x=0,y=1,class_word='FEDC0008',class_id=8,confidence_q16=65244,confidence=65244/65536))
        self.assertIsNone(s['temperature']); self.assertIsNone(s['phy'])
        json.dumps(s,allow_nan=False)

    def test_complete_only_ack_15_unique_and_done(self):
        for missing in ('ack','row','done',None):
            with self.subTest(missing=missing):
                j=self.job()
                if missing!='ack': j.receive(ack())
                for y in range(2 if missing=='row' else 3): j.receive(row(y))
                if missing!='done': j.receive(status(7,3))
                self.assertEqual(j.finish(),missing is None)
                self.assertEqual(j.state,'done' if missing is None else 'error')

    def test_exact_duplicate_does_not_fill_missing_row(self):
        j=self.job();j.receive(ack());j.receive(row(0));j.receive(row(0));j.receive(row(1));j.receive(status(7,3))
        self.assertEqual(j.snapshot()['received_pixels'],10)
        self.assertEqual(j.snapshot()['duplicates'],1)
        self.assertFalse(j.finish())

    def test_conflicting_duplicate_permanent_failure(self):
        j=self.job(); j.receive(row(0))
        with self.assertRaisesRegex(ValueError,'conflicting'): j.receive(row(0,word=0xFFFF0001))
        first=j.error
        for p in (row(1),row(2),ack(),status(7,3)): j.receive(p)
        self.assertFalse(j.finish());self.assertEqual(j.error,first)
        self.assertEqual(j.snapshot()['received_pixels'],5)

    def test_wrong_identity_model_ack_old_task_fail_closed(self):
        bad=[status(7,3,boot=5),status(7,3,session=5),status(7,3,wcrc=5),
             row(0,task=8),ack(task=8),ack(seq=2),status(8,3)]
        for p in bad:
            with self.subTest(packet=p.hex()):
                j=self.job()
                with self.assertRaises(ValueError):j.receive(p)
                j.receive(status(7,3));self.assertFalse(j.finish())

    def test_execution_failure_after_all_rows(self):
        j=self.job();j.receive(ack())
        for y in range(3):j.receive(row(y))
        with self.assertRaisesRegex(ValueError,'ACK failure'):j.receive(ack(code=6))
        j.receive(status(7,3));self.assertFalse(j.finish())
        self.assertEqual(j.snapshot()['received_pixels'],15)

    def test_done_inconsistent_or_failure_state(self):
        for p in (status(7,3,done=14),status(7,2)):
            j=self.job()
            with self.assertRaises(ValueError):j.receive(p)
            self.assertFalse(j.finish())

    def test_decode_corruption_latches(self):
        for p in (b'bad',row(0)[:-1],row(0,word=0x12340100),row(0,word=0x12340009)):
            j=self.job()
            with self.assertRaises(ValueError):j.receive(p)
            self.assertFalse(j.finish())

    def test_out_of_order_rows_exact_export(self):
        j=self.job();j.receive(status(7,3))
        for y in (2,0,1):j.receive(row(y,word=0x87650000+y))
        j.receive(ack());self.assertTrue(j.finish())
        s=j.snapshot();data=list(csv.DictReader(io.StringIO(b.csv_text(s))))
        self.assertEqual(len(data),15)
        self.assertEqual([(int(c['x']),int(c['y'])) for c in data],[(x,y) for y in range(3) for x in range(5)])
        for c in data:
            self.assertEqual(float(c['confidence']),int(c['confidence_q16'])/65536)
            self.assertEqual(c['boot_id'],'12345678')

    def test_late_conflict_before_finalization_not_success(self):
        j=self.job();j.receive(ack())
        for y in range(3):j.receive(row(y))
        j.receive(status(7,3));self.assertTrue(j.audit.complete())
        with self.assertRaises(ValueError):j.receive(row(2,word=0xF0000001))
        self.assertFalse(j.finish())

    def test_gate_inert_no_socket_no_entropy_before_start(self):
        with tempfile.TemporaryDirectory() as d, patch.object(b.socket,'socket',side_effect=AssertionError('UDP')), patch.object(b.secrets,'randbits',side_effect=AssertionError('entropy')):
            src=b.BoardSource(Path(d));self.assertFalse(src.describe()['authorized'])
            for text,confirmed in [('e4196b84',True),('e86a03b1',True),('12345678',False),('123',True),('00000000',True)]:
                with self.assertRaises(ValueError):src.authorize(text,confirmed)
            src.authorize('12345678',True);self.assertTrue(src.describe()['authorized'])
            src.validate(dict(kind='region',scene='longkou',version='v2',rect=b.RECT))
            self.assertEqual(src.addr,('192.168.1.10',5010))
            self.assertIsNone(src.telemetry()['temp_c']);src.close()

    def test_scope_gate_and_durable_single_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            src=b.BoardSource(Path(d));good=dict(kind='region',scene='longkou',version='v2',rect=b.RECT)
            with self.assertRaises(ValueError):src.validate(good)
            src.authorize('12345678',True)
            src.validate(dict(kind='scan',scene='longkou',version='v2',rect=None))
            for key,value in [('kind','scan'),('scene','honghu'),('version','v1'),('rect',[0,0,5,3])]:
                with self.assertRaises(ValueError):src.validate({**good,key:value})
            (Path(d)/'boots').mkdir();(Path(d)/'boots/12345678.json').write_text('{}')
            self.assertFalse(src.describe()['authorized'])
            with self.assertRaises(ValueError):src.validate(good)
            with self.assertRaises(ValueError):b.BoardSource(Path(d)).authorize('12345678',True)
            for fn in (src.pause,src.resume,src.stop,src.upload_weights):
                with self.assertRaises(ValueError):fn()


if __name__=='__main__':unittest.main(verbosity=2)
