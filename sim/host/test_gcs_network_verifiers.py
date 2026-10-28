"""Offline synthetic records only: no real socket, media, service or ELF Build."""
from pathlib import Path
import hashlib,json,struct,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_log,board_task,gcs_boot_provision,gcs_sd_boot_verify,gcs_model_verify
from sim.host.test_gcs_board_log import BUILD,BOOT,BOOT_TEXT,FakeSocket,response
from sim.host.test_gcs_model_link import Socket,link,m,candidate
from sim.host import test_gcs_model_link as model_fixture

BASE=BOOT-2

def boot_artifact(root,generation=2):
    boot=BASE+generation
    text=BOOT_TEXT.replace(b'boot_id=12345678',f'boot_id={boot:08x}'.encode()).replace(b'generation=1',f'generation={generation}'.encode())
    class BootSocket(FakeSocket):
        def sendto(self,request,target):
            self.queue.append((response(request,text,boot=boot),target));return len(request)
    root.mkdir(parents=True)
    board_log.fetch(BootSocket(),board_task.wire.TARGET,root/'board_log',boot=boot)
    (root/'elf_audit.json').write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',**BUILD)))
    return root

class RecordsSocket(Socket):
    def __init__(self):
        super().__init__();self.model_records=b'';self.task_records={};self.timeout=.02;self.bad_records=False
    def gettimeout(self):return self.timeout
    def settimeout(self,value):self.timeout=value
    def emit(self,kind,body,task=None):
        if kind==0x86:body=body[:-16]+bytes.fromhex(BUILD['release_id'][:32])
        super().emit(kind,body,task)
    def sendto(self,data,target):
        kind=data[2];task,seq=struct.unpack_from('<HH',data,4)
        if kind==board_log.QUERY:
            self.sent.append(data);session=struct.unpack_from('<I',data,16)[0]
            raw=self.task_records.get((session,task),b'') if task else self.model_records if session else BOOT_TEXT
            packet=response(data,raw,flags=int(self.bad_records));self.queue.put(packet);return len(data)
        result=super().sendto(data,target)
        if kind in (m.WCOMMIT,m.WACT):
            crc=struct.unpack_from('<I',data,12 if kind==m.WCOMMIT else 16)[0]
            value=1 if kind==m.WCOMMIT and self.state not in (1,2) else 0
            scene=data[12] if kind==m.WACT else -1;active=crc if scene>=0 else 0
            self.model_records+=(f'S2C MODELCMD session={self.session:08x} type={kind} seq={seq} code=0 value={value:08x} crc={crc:08x} active_scene={scene} active_crc={active:08x} sd_rc=0\r\n').encode()
        if kind==1:self.task_records[self.session,task]=f'S2C offline task {task} completed\r\n'.encode()
        if kind==9:self.task_records[self.session,task]+=f'S2C offline PROBE req_seq={seq}\r\n'.encode()
        return result

class NetworkVerifiers(unittest.TestCase):
    def test_sd_network_records_and_copied_journal_no_uart_or_media_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);current=boot_artifact(root/'current');previous=boot_artifact(root/'previous',1)
            for slot,gen in ((0,2),(1,1)):
                (root/f'jrn{slot}.bin').write_bytes(gcs_boot_provision.record(slot,BASE,gen,0x0123456789abcdef))
            before=[(root/f'jrn{s}.bin').read_bytes() for s in (0,1)]
            with patch('socket.socket',side_effect=AssertionError('offline verifier must not connect')):
                r=gcs_sd_boot_verify.verify(journals=root,network_log=current,previous_network_log=previous)
            self.assertEqual(r['result'],'FILE_CORRELATION_PASS');self.assertEqual(r['identity']['transport'],'ethernet')
            self.assertNotIn('uart_sha256',r['identity']);self.assertFalse(r['independent_cold_start_acceptance'])
            self.assertEqual(before,[(root/f'jrn{s}.bin').read_bytes() for s in (0,1)])
            with self.assertRaises(ValueError):gcs_sd_boot_verify.verify(journals=root,network_log=current,previous_network_log=current)
            audit=json.loads((current/'elf_audit.json').read_text());audit['release_id']='0'*64
            (current/'elf_audit.json').write_text(json.dumps(audit))
            with self.assertRaises(ValueError):gcs_sd_boot_verify.verify(journals=root,network_log=current)

    def test_sd_tampered_pages_and_uart_fallback_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);current=boot_artifact(root/'current')
            with self.assertRaises(ValueError):gcs_sd_boot_verify.verify(uart=root/'none',journals=root,network_log=current)
            (current/'board_log'/'boot_log.bin').write_bytes(b'forged')
            with self.assertRaises(ValueError):gcs_sd_boot_verify.verify(journals=root,network_log=current)

    def test_model_raw_session_records_with_bound_release_and_no_uart(self):
        c,parts=candidate('longkou');sock=RecordsSocket()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=link.BoardSource(root,lambda *args:(c,parts))
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.authorize('12345678',True);source.request_models('upload','longkou','v2',activate=True)
                    model_fixture.ModelLinkTests().wait(lambda:source.operation.complete)
                    out=source.operation.out
                finally:source.shutdown()
            evidence=out/'board_logs'/'read_20261011_000000_000001'
            board_log.fetch(sock,source.addr,evidence,boot=BOOT,session=source.session)
            (evidence/'elf_audit.json').write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',**BUILD)))
            meta=json.loads((out/'session.json').read_text());meta['release_id']=BUILD['release_id'];meta['network_startup']='OFFLINE'
            (out/'session.json').write_text(json.dumps(meta))
            with patch('socket.socket',side_effect=AssertionError('No network in verifier')):
                result=gcs_model_verify.verify(out,network_log=evidence)
                self.assertTrue(result['data_acceptance']);self.assertTrue(result['board_log_confirmed'])
                self.assertEqual(result['log_transport'],'ethernet');self.assertNotIn('uart_confirmed',result)
                with self.assertRaises(ValueError):gcs_model_verify.verify(out,uart=root/'not_uart')
                (evidence/'model_log.bin').write_bytes(b'forged')
                with self.assertRaises(ValueError):gcs_model_verify.verify(out,network_log=evidence)

if __name__=='__main__':unittest.main()
