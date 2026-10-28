import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'gcs'))
import board_log

TARGET=('192.168.1.10',5010)
BOOT=0x12345678
BUILD={'app_id':'gcs_r1_abi4','release_id':'a'*64,'source_set_sha256':'b'*64,'hardware_xsa_sha256':'c'*64}
BOOT_TEXT=('S2C BUILD app=gcs_r1_abi4 release='+BUILD['release_id']+' sources='+BUILD['source_set_sha256']+' xsa='+BUILD['hardware_xsa_sha256']+'\r\n'
    'S2C IDENTITY source=sd-journal boot_id=12345678 generation=1 nonce=0123456789abcdef abi=4\r\n'
    'S2C boot_id=12345678 MODEL_SCAN int16; no inference yet\r\n'
    'S2C MODEL_SCAN complete=1 entries=14 rejected=0 rc=0 cleanup=0 reject_rc=0 reject_code=0\r\n'
    'S2C DP init_rc=0 1920x1080; picture requires user check; no SD assets\r\n'
    'S2C READY boot_id=12345678 registry=14 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app=gcs_r1_abi4\r\n').encode()
TASK_TEXT=b'S2C retained real board task records\r\n'*100

def response(request,raw,boot=BOOT,flags=0):
    magic,kind,version,task,seq,stamp=struct.unpack_from('<HBBHHI',request)
    requested_boot,session,offset,size=struct.unpack_from('<4I',request,12)
    assert (magic,kind,version)==(0x4548,0x14,1)
    size=size or len(raw);body=raw[:size];page=body[offset:offset+1372]
    return (struct.pack('<HBBHHI',magic,0x88,1,task,seq+7,0)+
        struct.pack('<IIHBBIIIHH',boot,session,seq,1,flags,offset,size,zlib.crc32(body),len(page),0)+page)

class FakeSocket:
    def __init__(self,mutator=None):self.queue=[];self.sent=[];self.mutator=mutator;self.timeout=.02
    def gettimeout(self):return self.timeout
    def settimeout(self,value):self.timeout=value
    def sendto(self,request,target):
        self.sent.append(request)
        task=struct.unpack_from('<H',request,4)[0]
        packet=response(request,TASK_TEXT if task else BOOT_TEXT)
        if self.mutator:packet=self.mutator(packet)
        if packet is not None:self.queue.append((packet,target))
        return len(request)
    def recvfrom(self,n):
        if not self.queue:raise socket.timeout()
        return self.queue.pop(0)

class BoardLogTest(unittest.TestCase):
    def test_full_build_and_live_no_uart_boot_identity(self):
        result=board_log.parse_boot(BOOT_TEXT,BUILD)
        self.assertEqual(result['state'],'ready')
        self.assertEqual((result['boot_id'],result['generation'],result['registry_count']),(BOOT,1,14))
        self.assertFalse(result['independent_cold_start_verified'])
        partial=BOOT_TEXT.split(b'S2C MODEL_SCAN complete=')[0]
        self.assertEqual(board_log.parse_boot(partial,BUILD)['state'],'scanning_models')
        with self.assertRaises(ValueError):board_log.parse_boot(BOOT_TEXT[:160]+BOOT_TEXT[242:],BUILD)
        with self.assertRaises(ValueError):board_log.parse_boot(BOOT_TEXT,{**BUILD,'release_id':'d'*64})

    def test_readback_pages_replay_and_file_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'pull';sock=FakeSocket()
            result=board_log.fetch(sock,TARGET,out,boot=BOOT,session=99,task=7,timeout=.1)
            self.assertEqual(result['result'],'PASS')
            self.assertTrue(all(r[2]==0x14 for r in sock.sent))
            audited=board_log.audit(out)
            self.assertEqual(audited['boot_log'],BOOT_TEXT)
            self.assertEqual(audited['task_log'],TASK_TEXT)
            self.assertEqual(audited['board_log'],BOOT_TEXT+TASK_TEXT)
            self.assertGreater(len(sock.sent),2)
            (out/'board_log.txt').write_bytes(BOOT_TEXT+TASK_TEXT+b'fake')
            with self.assertRaises(ValueError):board_log.audit(out)

    def test_model_session_pages_are_distinct_from_boot_and_tasks(self):
        class ModelSocket(FakeSocket):
            def sendto(self,request,target):
                self.sent.append(request)
                session=struct.unpack_from('<I',request,16)[0]
                self.queue.append((response(request,TASK_TEXT if session else BOOT_TEXT),target))
                return len(request)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'models'
            board_log.fetch(ModelSocket(),TARGET,out,boot=BOOT,session=99,task=0,timeout=.1)
            replay=board_log.audit(out,BOOT,99,0)
            self.assertEqual(replay['model_log'],TASK_TEXT)
            self.assertEqual(replay['task_log'],b'')
            self.assertEqual((out/'model_log.bin').read_bytes(),TASK_TEXT)
            self.assertFalse((out/'task_log.bin').exists())
            with self.assertRaises(ValueError):board_log.audit(out,BOOT,98,0)
            with self.assertRaises(ValueError):board_log.audit(out,BOOT,99,7)

    def test_wrong_boot_crc_overflow_and_timeout_fail_closed(self):
        def changed_boot(p):return p[:12]+struct.pack('<I',BOOT+1)+p[16:]
        def changed_crc(p):return p[:32]+struct.pack('<I',0)+p[36:]
        def overflow(p):return p[:23]+b'\1'+p[24:]
        for mutation in (changed_boot,changed_crc,overflow,lambda p:None):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                out=Path(d)/'pull'
                with self.assertRaises((ValueError,TimeoutError)):
                    board_log.fetch(FakeSocket(mutation),TARGET,out,boot=BOOT,session=99,task=7,timeout=.02)
                self.assertEqual(json.loads((out/'receipt.json').read_text())['result'],'FAIL')

    def test_unbound_discovery_and_raw_trace_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'pull'
            board_log.fetch(FakeSocket(),TARGET,out,boot=0,timeout=.1)
            self.assertEqual(board_log.audit(out)['boot'],BOOT)
            records=[json.loads(x) for x in (out/'packets.jsonl').read_text().splitlines()]
            packet=bytearray.fromhex(records[1]['hex']);packet[-5]^=1;records[1]['hex']=packet.hex()
            (out/'packets.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in records))
            with self.assertRaises(ValueError):board_log.audit(out)

    def test_decode_rejects_reserved_trailing_and_bad_offset(self):
        req=board_log.request(BOOT,0,0,0,0,3);packet=response(req,BOOT_TEXT)
        self.assertEqual(board_log.decode(packet)['data'],BOOT_TEXT)
        for bad in (packet+b'x',packet[:38]+b'\1\0'+packet[40:],packet[:24]+struct.pack('<I',9999)+packet[28:]):
            with self.assertRaises(ValueError):board_log.decode(bad)

if __name__=='__main__':unittest.main()
