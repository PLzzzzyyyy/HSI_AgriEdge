import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import uart_capture as u
RECORD=b'S2C IDENTITY source=sd-journal boot_id=12345678 generation=1 nonce=1234567887654321 abi=4\r\n'
def ready():return ('S2C READY boot_id=12345678 registry=6 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app='+u.APP_ID+'\r\n').encode()
class TestSdIdentity(unittest.TestCase):
    def test_observe_no_entropy_no_tx(self):
        claimed=[];p=u.SdIdentity(0,claimed.append)
        for b in RECORD+ready():self.assertEqual(p.feed(bytes([b]),1),[])
        self.assertEqual((p.state,p.boot,p.generation),('ready',0x12345678,1));self.assertEqual(claimed,[p.boot])
    def test_no_hot_ready_or_old_prompt(self):
        for raw in (ready(),u.PROMPT+b'\n',RECORD+RECORD,RECORD.replace(b'abi=4',b'abi=3')):
            p=u.SdIdentity(0,lambda b:None);self.assertEqual(p.feed(raw,1),[]);self.assertEqual(p.state,'error')
    def test_mismatch_fail_timeout(self):
        for tail in (ready().replace(b'12345678',b'12345679'),b'S2C STOP identity failed\n'):
            p=u.SdIdentity(0,lambda b:None);p.feed(RECORD+tail,1);self.assertEqual(p.state,'error')
        p=u.SdIdentity(0,lambda b:None);p.feed(b'',181);self.assertEqual(p.state,'error')
    def test_claim_fails_no_fallback(self):
        def claim(b):raise ValueError('previous boot')
        p=u.SdIdentity(0,claim);self.assertEqual(p.feed(RECORD+ready(),1),[]);self.assertEqual(p.state,'error')
if __name__=='__main__':unittest.main()
