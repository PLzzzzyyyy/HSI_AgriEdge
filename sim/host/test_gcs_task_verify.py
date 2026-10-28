"""Independent artifact/checkpoint fixtures; never a physical board claim."""
from pathlib import Path
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_task as t
import board_history
import gcs_task_verify as v
from sim.host.test_gcs_task_transport import status,row,ack,info


def fixture(root, stop=False):
    directory=root/'task_fixture';directory.mkdir()
    job=t.Job(0x12345678,42,2,[548,395,2,5],False);job.out=directory
    job.host_run=dict(id=9,kind='region',scene='longkou',version='v2',rect=[548,395,2,5],t0=100)
    meta=dict(boot_id=job.audit.boot,session=42,task=2,rect=[548,395,2,5],host_run=job.host_run,
              scope='TASK_LIFECYCLE',target=t.wire.TARGET)
    t.save_json(directory/'session.json',meta)
    count=5 if stop else 10;us=count*5000
    end=bytearray(status(2,0 if stop else 3,count));struct.pack_into('<f',end,20,5.)
    packets=[('tx',t.wire.packet(1,2,1,1,job.audit.start_body())),('rx',ack(2,1,1)),('rx',row(2,548,395,5))]
    if not stop:packets.append(('rx',row(2,549,395,5)))
    packets.append(('rx',bytes(end)))
    lines=[]
    for direction,data in packets:
        lines.append(json.dumps(dict(direction=direction,hex=data.hex(),peer=t.wire.TARGET,monotonic_ns=1)))
        if direction=='tx':job.audit.sent(data)
        else:job.audit.received(data)
    (directory/'packets.jsonl').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    job.last_status=job.audit.last_status;job.state='stopped' if stop else 'done';job.ended=t.legacy.now()
    t.save_json(directory/'summary.json',job.snapshot())
    crc=zlib.crc32(struct.pack(f'<{count}I',*([0xffff0002]*count)))
    uart=root/'uart.txt'
    uart.write_text('S2C READY boot_id=12345678 wcrc=27231983 roi=any scan=400x550 UDP=5010 app=task_lifecycle_r1\n'
        'S2C TASK_BEGIN session=0000002a task=1 x=1 y=1 w=1 h=1\n'
        'S2C TASK_DONE session=0000002a task=1 completed=1 compute_us=5000 crc32=12345678\n'
        'S2C TASK_BEGIN session=0000002a task=2 x=395 y=548 w=5 h=2\n'
        'S2C S3 scope=task session=0000002a task=2 wait_calls=10 wait_rx=2 max_gap_us=123 max_service_us=5\n'
        f'S2C TASK_{"STOP" if stop else "DONE"} session=0000002a task=2 completed={count} compute_us={us} crc32={crc:08x}\n',encoding='utf-8')
    return job,uart


class VerifyTests(unittest.TestCase):
    def test_multi_task_uart_and_partial_stopped_coverage(self):
        for stop in (False,True):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as d:
                job,uart=fixture(Path(d),stop)
                report=v.verify(job.out,uart)
                self.assertTrue(report['data_acceptance']);self.assertFalse(report['batch_acceptance'])
                self.assertEqual(report['received_pixels'],5 if stop else 10)
                self.assertTrue(report['s3']['passed']);self.assertFalse(report['probe']['passed'])
                restored=board_history.load_job(job.out)
                self.assertEqual(restored.audit.rows,job.audit.rows)
                self.assertEqual(restored.state,job.state)

    def test_crc_timing_and_faults_are_not_papered_over(self):
        for old,new in [('compute_us=50000','compute_us=50001'),('x=395','x=394'),('task=2','task=3')]:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as d:
                job,uart=fixture(Path(d));uart.write_text(uart.read_text().replace(old,new))
                with self.assertRaises(ValueError):v.verify(job.out,uart)
        with tempfile.TemporaryDirectory() as d:
            job,uart=fixture(Path(d));uart.write_text(uart.read_text()+'S2C HALTED: retain DMA\n')
            with self.assertRaisesRegex(ValueError,'fault'):v.verify(job.out,uart)

    def test_export_mask_and_conflict_are_checked_per_word(self):
        with tempfile.TemporaryDirectory() as d:
            job,uart=fixture(Path(d))
            snap=job.snapshot();snap['cells'][0]['class_word']='FFFF0001'
            t.save_json(job.out/'summary.json',snap)
            with self.assertRaisesRegex(ValueError,'Export'):v.verify(job.out,uart)
            t.save_json(job.out/'summary.json',job.snapshot())
            with (job.out/'packets.jsonl').open('a') as f:
                f.write(json.dumps(dict(direction='rx',peer=t.wire.TARGET,hex=row(2,548,395,5,word=1).hex()))+'\n')
            with self.assertRaisesRegex(ValueError,'Conflicting'):v.verify(job.out,uart)

    def test_history_checks_peer_and_does_not_trust_probe_summary(self):
        with tempfile.TemporaryDirectory() as d:
            job,_=fixture(Path(d))
            snap=job.snapshot();snap['probes']=[dict(state='done',class_word='00000000',logits_q16=[0]*9)]
            t.save_json(job.out/'summary.json',snap)
            restored=board_history.load_job(job.out)
            self.assertEqual(restored.probes,[])
            path=job.out/'packets.jsonl';lines=path.read_text().splitlines()
            item=json.loads(lines[2]);item['peer']=['192.168.1.99',5010];lines[2]=json.dumps(item)
            path.write_text('\n'.join(lines)+'\n')
            restored=board_history.load_job(job.out)
            self.assertTrue(restored.integrity_error);self.assertEqual(restored.audit.count,0)

    def test_recovery_requires_recorded_info_ping_status_not_summary_flags(self):
        with tempfile.TemporaryDirectory() as d:
            job,uart=fixture(Path(d));path=job.out/'packets.jsonl'
            packets=[dict(direction='event',event='recovery_begin')]
            for direction,raw in [('tx',t.wire.packet(7,0,3,3,b'')),('rx',info(task=2,state=3,done=10)),
                                  ('tx',t.wire.packet(5,2,4,4,struct.pack('<I',42)))]:
                packets.append(dict(direction=direction,peer=t.wire.TARGET,hex=raw.hex()))
            path.write_text(path.read_text()+''.join(json.dumps(p)+'\n' for p in packets))
            with self.assertRaisesRegex(ValueError,'handshake'):v.verify(job.out,uart)
            end=bytearray(status(2,3,10));struct.pack_into('<f',end,20,5.)
            pong=t.wire.packet(0x84,2,5,5,struct.pack('<HHII',4,0,4,5))
            with path.open('a') as f:
                for raw in (pong,bytes(end)):f.write(json.dumps(dict(direction='rx',peer=t.wire.TARGET,hex=raw.hex()))+'\n')
            result=v.verify(job.out,uart);self.assertEqual(result['recovery_attempts'],1)

    def test_probe_history_reconstructed_from_packets_and_conflicting_repeat_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            job,_=fixture(Path(d));path=job.out/'packets.jsonl';q=[0,0,100,0,0,0,0,0,0]
            logits=t.wire.packet(0x85,2,13,105,struct.pack('<HBBHHII9i',11,0,9,548,395,t.wire.WCRC,0xffff0002,*q))
            packets=[('tx',t.wire.packet(5,2,10,110,struct.pack('<I',42))),
                     ('tx',t.wire.packet(9,2,11,111,struct.pack('<BBHHHI',0,0,548,395,0,t.wire.WCRC))),
                     ('rx',t.wire.packet(0x84,2,12,101,struct.pack('<HHII',10,0,110,101))),
                     ('rx',status(2,3,10)),('rx',logits)]
            with path.open('a') as f:
                for direction,raw in packets:f.write(json.dumps(dict(direction=direction,peer=t.wire.TARGET,hex=raw.hex()))+'\n')
            restored=board_history.load_job(job.out)
            self.assertFalse(restored.integrity_error);self.assertEqual(restored.probes[0]['state'],'done')
            self.assertEqual(restored.probes[0]['logits_q16'],q)
            self.assertAlmostEqual(sum(restored.probes[0]['probabilities']),1)
            bad=bytearray(logits);struct.pack_into('<i',bad,36,101)
            with path.open('a') as f:f.write(json.dumps(dict(direction='rx',peer=t.wire.TARGET,hex=bad.hex()))+'\n')
            self.assertTrue(board_history.load_job(job.out).integrity_error)

    def test_stopped_control_verification_is_separate_from_raw_data_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            job,uart=fixture(Path(d),stop=True);path=job.out/'packets.jsonl';lines=path.read_text().splitlines()
            for direction,raw in [('tx',t.wire.packet(2,2,8,8,b'')),('rx',ack(2,2,8,549))]:
                lines.insert(-1,json.dumps(dict(direction=direction,peer=t.wire.TARGET,hex=raw.hex())))
            path.write_text('\n'.join(lines)+'\n')
            result=v.verify(job.out,uart)
            self.assertTrue(result['data_acceptance']);self.assertFalse(result['controls']['passed'])
            with uart.open('a') as f:f.write('S2C CONTROL session=0000002a task=2 type=2 seq=8 completed=5\n')
            self.assertTrue(v.verify(job.out,uart)['controls']['passed'])

    def test_server_passive_history_and_verified_zip(self):
        import server as s
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            job,uart=fixture(Path(d))
            with patch.object(t.socket,'socket',side_effect=AssertionError('No socket')):
                state=s.State(Path(d))
                self.assertIsNone(state.board_source.boot);self.assertIsNone(state.board_source.worker)
                self.assertEqual(state.runs[9].n,10);self.assertEqual(state.next_id,10)
                report=v.verify(job.out,uart)
                state.runs[9].board_job.host_run['uart_evidence']=str(Path(d))
                with patch.object(s,'S',state),patch.object(s.UART,'snapshot',return_value={}):
                    result=s.api_board_acceptance(9,{k:report[k] for k in ('boot_id','session','task','browser_words_sha256')})
                    self.assertTrue(result['report']['checks']['browser_raw_words_and_seen_exact'])
                    response=s.api_board_words(9)
                    self.assertEqual(hashlib.sha256(response.body).hexdigest(),report['browser_words_sha256'])
                    with zipfile.ZipFile(job.out/'data_acceptance.zip') as z:
                        manifest=json.loads(z.read('sha256.json'))
                        for name,digest in manifest.items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),digest)
                    bad=dict(boot_id=report['boot_id'],session=report['session'],task=2,browser_words_sha256='bad')
                    with self.assertRaises(s.HTTPException):s.api_board_acceptance(9,bad)


if __name__=='__main__':unittest.main(verbosity=2)
