"""UART fixtures only: no COM port opened and no actual random identity drawn."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import uart_capture as u

READY=b'S2C READY boot_id=12345678 registry=6 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app=model_lifecycle_r1\r\n'
CURRENT_READY=READY.replace(b'model_lifecycle_r1',u.APP_ID.encode())
BUILD=(f'S2C BUILD app={u.APP_ID} release={"1"*64} sources={"2"*64} xsa={"3"*64}\r\n').encode()
def build_evidence(tmp):
    path=Path(tmp)/'synthetic_elf_audit.json'
    path.write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',app_id=u.APP_ID,release_id='1'*64,source_set_sha256='2'*64,hardware_xsa_sha256='3'*64)))
    return str(path)


class UartTests(unittest.TestCase):
    def parser(self):
        self.entropy=Mock(return_value=0x12345678);self.claim=Mock()
        return u.Identity(0,self.entropy,self.claim)

    def test_prompt_fragmentation_exactly_one_frame_and_ready(self):
        p=self.parser()
        self.assertEqual(p.feed(u.PROMPT,1),[]);self.entropy.assert_not_called()
        self.assertEqual(p.feed(b'\r\n',2),[b'12345678\n'])
        self.entropy.assert_called_once_with();self.claim.assert_called_once_with(0x12345678)
        self.assertEqual(p.feed(READY,3),[]);self.assertEqual(p.state,'ready')

    def test_fsbl_lfcr_prompt_at_every_read_boundary(self):
        stream=b'FSBL banner\n\rPMU-FW is not running.\n\r'+u.PROMPT+b'\r\n'
        for split in range(len(stream)+1):
            with self.subTest(split=split):
                p=self.parser()
                frames=p.feed(stream[:split],1)+p.feed(stream[split:],2)
                self.assertEqual(frames,[b'12345678\n'])
                self.entropy.assert_called_once_with()
                self.assertEqual(p.feed(READY,3),[])
                self.assertEqual(p.state,'ready')
        p=self.parser();frames=[]
        for byte in stream:frames+=p.feed(bytes([byte]),1)
        self.assertEqual(frames,[b'12345678\n'])

    def test_line_endings_do_not_relax_prompt_or_failure_guards(self):
        for payload in (b' '+u.PROMPT,b'noise'+u.PROMPT,u.PROMPT+b' ',
                        u.PROMPT.replace(b'hex',b'he\rx')):
            p=self.parser()
            self.assertEqual(p.feed(b'FSBL\n\r'+payload+b'\r\n',1),[])
            self.entropy.assert_not_called()
        for payload in (u.PROMPT+b'\n\r'+u.PROMPT+b'\n',
                        u.PROMPT+b'\n\rS2C STOP identity failure\r\n'):
            p=self.parser();self.assertEqual(p.feed(payload,1),[])
            self.assertEqual(p.state,'error')

    def test_saved_settings_from_last_confirmed_open_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch('serial.Serial',side_effect=AssertionError('No COM')):
            root=Path(tmp);d=root/'capture_20261010_184240_932101';d.mkdir()
            session=dict(port='COM6',baudrate=115200,operator_confirmed=True,
                         framing='8N1',flow_control=False,dtr=False,rts=False)
            (d/'session.json').write_text(json.dumps(session))
            c=u.Capture(root,Mock())
            self.assertEqual(c.snapshot()['settings'],dict(port='COM6',baudrate=115200))
            self.assertFalse(c.snapshot()['active'])
            (root/'capture_20261010_190000_000000').mkdir()
            self.assertEqual(u.Capture(root,Mock()).snapshot()['settings'],c.snapshot()['settings'])
            for bad in (dict(session,operator_confirmed=False),dict(session,port='COM0'),
                        dict(session,baudrate=123),dict(session,flow_control=True)):
                (d/'session.json').write_text(json.dumps(bad))
                self.assertIsNone(u.Capture(root,Mock()).snapshot()['settings'])
            (d/'session.json').write_text('broken json')
            self.assertIsNone(u.Capture(root,Mock()).snapshot()['settings'])

    def test_stale_ready_duplicate_prompt_mismatch_and_fatal_no_retry(self):
        for payload in (READY,u.PROMPT+b'\n'+u.PROMPT+b'\n',b'S2C STOP identity failure\r\n'):
            p=self.parser();self.assertEqual(p.feed(payload,1),[]);self.assertEqual(p.state,'error')
            first=p.error;p.feed(u.PROMPT+b'\n',2);self.assertEqual(p.error,first)
        p=self.parser();p.feed(u.PROMPT+b'\n',1)
        p.feed(READY.replace(b'12345678',b'12345679'),2);self.assertEqual(p.state,'error')
        p=self.parser();p.feed(u.PROMPT+b'\n',1)
        p.feed(READY.replace(b' app=model_lifecycle_r1',b''),2);self.assertEqual(p.state,'error')
        for bad in (READY.replace(b'registry=6',b'registry=49'),READY.replace(b'banks=1',b'banks=2'),
                    b'S2C READY boot_id=12345678 wcrc=27231983 roi=any scan=400x550 UDP=5010 app=task_lifecycle_r1\r\n'):
            p=self.parser();p.feed(u.PROMPT+b'\n',1);p.feed(bad,2);self.assertEqual(p.state,'error')

    def test_timeout_and_rng_failure_have_no_fallback(self):
        p=self.parser();p.feed(b'',180);self.assertEqual(p.state,'error');self.entropy.assert_not_called()
        p=self.parser();self.entropy.side_effect=RuntimeError('OS entropy unavailable')
        self.assertEqual(p.feed(u.PROMPT+b'\n',1),[]);self.assertEqual(p.state,'error');self.claim.assert_not_called()

    def test_confirmation_and_status_are_inert(self):
        with tempfile.TemporaryDirectory() as tmp, patch('serial.Serial',side_effect=AssertionError('No COM access')), \
             patch.object(u.secrets,'randbits',side_effect=AssertionError('No actual entropy')):
            c=u.Capture(tmp,lambda b:None);self.assertFalse(c.snapshot()['active'])
            for port,baud,confirmed in [('COM5',115200,False),('',115200,True),('COM5',None,True)]:
                with self.assertRaises(ValueError):c.start(port,baud,confirmed)
            self.assertEqual(c.stop()['state'],'disconnected')
            c.active=True
            with self.assertRaisesRegex(ValueError,'already active'):c.start('COM5',115200,True)
            c.active=False

    def test_exclusive_open_failure_no_retry_no_entropy(self):
        fake=Mock();fake.open.side_effect=OSError('Access denied: occupied')
        with tempfile.TemporaryDirectory() as tmp, patch('serial.Serial',return_value=fake) as factory, \
             patch.object(u.secrets,'randbits',side_effect=AssertionError('No entropy')):
            c=u.Capture(tmp,Mock());c.start('COM5',115200,True,build_evidence(tmp));c.worker.join(2)
            self.assertFalse(c.worker.is_alive());self.assertEqual(c.snapshot()['state'],'error')
            self.assertIn('occupied',c.snapshot()['error']);fake.write.assert_not_called();fake.close.assert_called_once()
            self.assertFalse(fake.dtr);self.assertFalse(fake.rts);self.assertEqual(factory.call_count,1)

    def test_worker_records_raw_bytes_once_releases_and_no_auto_task(self):
        sd=b'S2C IDENTITY source=sd-journal boot_id=12345678 generation=1 nonce=1234567887654321 abi=4\r\n'
        class SerialFixture:
            def __init__(self,partial=False):self.opened=False;self.closed=False;self.frames=[];self.phase=0;self.partial=partial
            def open(self):self.opened=True
            def read(self,n):
                time.sleep(.005)
                if self.phase==0:self.phase=1;return b'FSBL\n\r'+(u.PROMPT+b'\r\n' if self.partial else BUILD+sd)
                if self.phase==1:self.phase=2;return CURRENT_READY
                return b''
            def write(self,data):self.frames.append(data);return 3 if self.partial else len(data)
            def close(self):self.closed=True
        for partial in (False,True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as tmp:
                fake=SerialFixture(partial);ready=threading.Event();calls=[]
                with patch('serial.Serial',return_value=fake),patch.object(u.secrets,'randbits',return_value=0x12345678):
                    c=u.Capture(tmp,lambda b:(calls.append(b),ready.set()));c.start('COM5',115200,True,build_evidence(tmp))
                    try:
                        if partial:c.worker.join(2)
                        else:self.assertTrue(ready.wait(2))
                    finally:c.stop()
                self.assertTrue(fake.closed);self.assertEqual(fake.frames,[])
                self.assertEqual(calls,[] if partial else ['12345678'])
                records=[json.loads(x) for x in (c.out/'serial_events.jsonl').read_text().splitlines()]
                self.assertEqual(sum(x['direction']=='tx_attempt' for x in records),0)
                if partial:self.assertIn('Old UART-input',c.snapshot()['error'])
                else:
                    self.assertEqual((c.out/'uart.bin').read_bytes(),b'FSBL\n\r'+BUILD+sd+CURRENT_READY)
                    self.assertEqual(c.snapshot()['tx_bytes'],0)
                    self.assertEqual(c.snapshot()['settings'],dict(port='COM5',baudrate=115200))


if __name__=='__main__':unittest.main(verbosity=2)
