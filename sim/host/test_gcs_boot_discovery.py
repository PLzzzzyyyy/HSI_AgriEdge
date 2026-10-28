from pathlib import Path
import sys,tempfile,unittest,struct,json
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'gcs'))
import board_boot as b
RELEASE='1'*64
def info(boot=0x12345678,abi=4,session=0,task=0,release=RELEASE):
    return b.task.wire.packet(0x86,task,1,0,struct.pack('<IBBBBIHBB4HIHBB',boot,1,abi,16,0,session,task,0,0,0,0,0,0,0,0,0,0)+(bytes.fromhex(release[:32]) if abi==4 else b''))
class Socket:
    def __init__(self,data):self.data=data;self.sent=[];self.closed=False;self.responses=[]
    def __enter__(self):return self
    def __exit__(self,*a):self.closed=True
    def bind(self,a):pass
    def settimeout(self,t):pass
    def sendto(self,data,peer):self.sent.append(data);return len(data)
    def recvfrom(self,n):
        if self.responses:return self.responses.pop(0)
        if self.data is None:raise b.socket.timeout()
        return self.data,b.task.wire.TARGET
class Discovery(unittest.TestCase):
    def test_no_confirmation_no_traffic(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',side_effect=AssertionError('no socket')):
            with self.assertRaises(ValueError):b.discover(tmp,b.task.wire.TARGET,False)
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_explicit_info_only_and_close(self):
        fake=Socket(info())
        with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',return_value=fake):
            r=b.discover(tmp,b.task.wire.TARGET,True,RELEASE);self.assertEqual(r['boot_id'],'12345678');self.assertFalse(r['independent_cold_start_verified'])
            self.assertEqual([x[2] for x in fake.sent],[7]);self.assertTrue(fake.closed)
            rows=[json.loads(x) for x in (Path(r['evidence'])/'packets.jsonl').read_text().splitlines()];self.assertEqual(len(rows),2)
    def test_old_or_existing_owner_refused(self):
        for raw in (info(abi=3),info(boot=0xbb6bd8e3),info(boot=0),info(session=42),info(task=1),info(release='2'*64)):
            fake=Socket(raw)
            with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',return_value=fake):
                with self.assertRaises(ValueError):b.discover(tmp,b.task.wire.TARGET,True,RELEASE)
                self.assertTrue(fake.closed);self.assertEqual([x[2] for x in fake.sent],[7])
                receipt=json.loads(next(Path(tmp).rglob('discovery.json')).read_text())
                self.assertEqual(receipt['result'],'FAIL');self.assertFalse(receipt['task_started'])
    def test_wrong_endpoint_and_non_boolean_confirmation_are_passive(self):
        for target,confirmed in ((('127.0.0.1',5010),True),(b.task.wire.TARGET,1)):
            with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',side_effect=AssertionError('no socket')):
                with self.assertRaises(ValueError):b.discover(tmp,target,confirmed)
                self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_untrusted_peer_is_recorded_but_not_authorized(self):
        fake=Socket(info());fake.responses=[(info(boot=0x87654321),('192.168.1.11',5010))]
        with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',return_value=fake):
            r=b.discover(tmp,b.task.wire.TARGET,True,RELEASE)
            self.assertEqual(r['boot_id'],'12345678')
            rows=[json.loads(x) for x in (Path(r['evidence'])/'packets.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),3);self.assertEqual(rows[1]['peer'],['192.168.1.11',5010])
    def test_malformed_version_and_non_info_do_not_fallback(self):
        wrong=bytearray(info());wrong[3]=2
        for raw in (bytes(wrong),info()[:-1],b.task.wire.packet(0x80,0,1,0,b'')):
            fake=Socket(raw)
            with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',return_value=fake):
                with self.assertRaises(ValueError):b.discover(tmp,b.task.wire.TARGET,True,RELEASE)
                self.assertTrue(fake.closed);self.assertEqual([x[2] for x in fake.sent],[7])
    def test_timeout_is_bounded_and_retains_failure(self):
        fake=Socket(None)
        with tempfile.TemporaryDirectory() as tmp,patch.object(b.socket,'socket',return_value=fake),patch.object(b.time,'monotonic',side_effect=[i*.1 for i in range(100)]):
            with self.assertRaises(TimeoutError):b.discover(tmp,b.task.wire.TARGET,True,RELEASE)
            self.assertLessEqual(len(fake.sent),3);self.assertTrue(fake.closed)
            receipt=json.loads(next(Path(tmp).rglob('discovery.json')).read_text())
            self.assertEqual(receipt['result'],'FAIL');self.assertIn('No valid new ABI4 INFO',receipt['error'])
if __name__=='__main__':unittest.main()
