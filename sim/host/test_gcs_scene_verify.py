"""Full-size deterministic offline data; never board acceptance evidence."""
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import gcs_scene_verify as v


class VerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit=SimpleNamespace(boot=0x12345678,session=42,task=7,
            rows={y:[((x+y)%65536)<<16 | ((x+y)%9) for x in range(400)] for y in range(550)})
        lines=['S2C READY boot_id=12345678 wcrc=27231983',
               'S2C FULL_EXEC session=0000002a task=7 size=400x550 bound_s=1800']
        crc=0
        for y,words in cls.audit.rows.items():
            raw=struct.pack('<400I',*words);crc=zlib.crc32(raw,crc)
            lines.append(f'S2C FULL_ROW y={y} n=400 crc32={zlib.crc32(raw):08x}')
        lines.append('S2C S3 scope=scene session=0000002a task=7 wait_calls=1234 wait_rx=12 max_gap_us=12000 max_service_us=150')
        lines.append(f'S2C FULL_RESULT rc=0 driver=0 completed=220000 halted=0 crc32={crc:08x}')
        cls.uart='\r\n'.join(lines)+'\r\n';cls.crc=crc

    def test_550_rows_and_whole_crc(self):
        self.assertEqual(v.verify_uart(self.uart,self.audit),f'{self.crc:08x}')
        self.assertTrue(v.verify_s3(self.uart,self.audit)['passed'])

    def test_s3_missing_wrong_identity_no_rx_and_lease_gap_not_pass(self):
        for text in ('',self.uart.replace('wait_rx=12','wait_rx=0'),self.uart.replace('max_gap_us=12000','max_gap_us=1000000'),
                     self.uart.replace('scope=scene session=0000002a','scope=scene session=0000002b')):
            self.assertFalse(v.verify_s3(text,self.audit)['passed'])

    def test_missing_duplicate_identity_failure_and_crc_rejected(self):
        bad=[self.uart.replace('FULL_ROW y=100','FULL_ROW y=101'),
             self.uart.replace('task=7','task=8'),self.uart.replace('rc=0 driver=0','rc=-5 driver=-5'),
             self.uart.replace(f'crc32={self.crc:08x}', 'crc32=00000000'),
             self.uart.replace('n=400','n=399',1),self.uart+'S2C READY boot_id=12345678\n']
        for text in bad:
            with self.subTest(text=text[:90]):
                with self.assertRaises(ValueError):v.verify_uart(text,self.audit)

    def test_replay_summary_uart_and_download_match_without_network(self):
        b=v.b;w=b.wire
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);packets=[];job=b.Job(self.audit.boot,42,7,True)
            def packet(direction,data):
                packets.append(dict(direction=direction,peer=list(w.TARGET),hex=data.hex()))
                (job.sent if direction=='tx' else job.receive)(data)
            packet('tx',w.packet(5,0,0,100,struct.pack('<I',42)))
            packet('rx',w.packet(0x84,0,0,100,struct.pack('<HHII',0,0,100,100)))
            def status(task,done,state):
                body=struct.pack('<IIfffBBH',done,220000 if task else 0,*[float('nan')]*3,state,0,0)
                tail=struct.pack('<IIIHBB8IHHI',self.audit.boot,42,w.WCRC,done//400,1,0,*[0]*8,0,0,0)
                return w.packet(0x82,task,0,100,body+tail)
            packet('rx',status(0,0,0));packet('tx',b.board_scene.start_packet(7,1,100,42))
            packet('rx',w.packet(0x83,7,0,100,struct.pack('<BBHI',1,0,1,0)))
            for y,words in self.audit.rows.items():
                for col in (0,348):
                    segment=words[col:col+348]
                    packet('rx',w.packet(0x81,7,0,100,struct.pack('<4H',y,col,len(segment),0)+struct.pack(f'<{len(segment)}I',*segment)))
            packet('rx',status(7,220000,3));self.assertTrue(job.finish())
            (root/'session.json').write_text(json.dumps(dict(boot_id=self.audit.boot,session=42,task=7,full_scene=True,target=list(w.TARGET))))
            (root/'packets.jsonl').write_text('\n'.join(json.dumps(p) for p in packets))
            summary=job.snapshot();encoded=json.dumps(summary)
            (root/'summary.json').write_text(encoded);(root/'export.json').write_text(encoded)
            (root/'uart.txt').write_text(self.uart)
            with patch.object(b.socket,'socket',side_effect=AssertionError('No network')):
                result=v.verify(root,root/'uart.txt',root/'export.json')
            self.assertTrue(result['data_acceptance'])
            # Actual REST function -> verified downloadable bundle, all offline.
            import server as server
            job.out=root;(root/'results.csv').write_text(b.csv_text(job.snapshot()))
            receipt=dict(boot_id='12345678',evidence=str(root),error=None)
            cmd={k:result[k] for k in ('boot_id','session','task','browser_words_sha256')}
            with patch.dict(server.S.runs,{987:SimpleNamespace(board_job=job)}), patch.object(server.UART,'snapshot',return_value=receipt), \
                 patch.object(b.socket,'socket',side_effect=AssertionError('No network')):
                response=server.api_board_acceptance(987,cmd)
                self.assertTrue(response['report']['data_acceptance'])
                self.assertTrue((root/'data_acceptance.zip').is_file())
                with self.assertRaises(server.HTTPException):server.api_board_acceptance(987,{**cmd,'browser_words_sha256':'bad'})
            summary['cells'][-1]['class_word']='00000000'
            with self.assertRaises(ValueError):v.verify_export(summary,job.snapshot())


if __name__=='__main__':unittest.main(verbosity=2)
