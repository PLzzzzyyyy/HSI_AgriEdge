"""Synthetic Ethernet records, independent replay and passive historical export."""
from pathlib import Path
import hashlib,io,json,sys,tempfile,unittest,zipfile
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_log,board_timing,board_task,board_history,server as s,gcs_task_verify
from sim.host.test_gcs_model_business import fixture
from sim.host.test_gcs_timing import phase_text
from sim.host.test_gcs_board_log import BOOT_TEXT,BUILD,FakeSocket,response

def network_fixture(root):
    job,old=fixture(root,'longkou')
    task_text=('\n'.join(old.read_text().splitlines()[1:])+'\n'+phase_text()).replace('\r\n','\n').replace('\n','\r\n').encode()
    class RecordsSocket(FakeSocket):
        def sendto(self,request,target):
            self.sent.append(request)
            self.queue.append((response(request,task_text if request[4] or request[5] else BOOT_TEXT),target))
            return len(request)
    evidence=job.out/'board_logs'/'read_20261011_000000_000001'
    board_log.fetch(RecordsSocket(),board_task.wire.TARGET,evidence,boot=job.audit.boot,session=job.audit.session,task=job.audit.task)
    (evidence/'elf_audit.json').write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',**BUILD)))
    job.board_log_evidence=str(evidence);job.board_log_state='ready'
    job.host_run.update(network_startup='OFFLINE/network_start',build_evidence=str(evidence/'elf_audit.json'))
    meta=json.loads((job.out/'session.json').read_text());meta['host_run']=job.host_run
    board_task.save_json(job.out/'session.json',meta);board_task.save_json(job.out/'summary.json',job.snapshot())
    return job,evidence

class NetworkRecords(unittest.TestCase):
    def test_network_verifier_uses_bound_elf_without_uart_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,evidence=network_fixture(Path(tmp))
            report=gcs_task_verify.verify(job.out,network_log=evidence)
            self.assertTrue(report['data_acceptance']);self.assertEqual(report['log_transport'],'ethernet')
            self.assertIn('board_log_task_identity',report['checks']);self.assertNotIn('uart_task_identity',report['checks'])
            timing=board_timing.from_network(job.snapshot(),evidence)
            self.assertTrue(timing['available']);self.assertEqual(timing['transport'],'ethernet')
            self.assertEqual(timing['phases'][1]['us'],5000)

    def test_historical_acceptance_packages_original_network_pages_no_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,evidence=network_fixture(Path(tmp))
            report=gcs_task_verify.verify(job.out,network_log=evidence,elf_audit=evidence/'elf_audit.json')
            cmd={k:report[k] for k in ('boot_id','session','task','browser_words_sha256')}
            with patch.object(s.board_link.socket,'socket',side_effect=AssertionError('No network from history')),\
                 patch.object(s.UART,'snapshot',side_effect=AssertionError('No UART dependency')):
                actual=s.task_acceptance(1,job,cmd)
                self.assertTrue(actual['report']['data_acceptance'])
                self.assertTrue(s.task_phase_timing(job)['available'])
            with zipfile.ZipFile(job.out/'data_acceptance.zip') as archive:
                self.assertNotIn('uart.txt',archive.namelist())
                self.assertEqual(archive.read('board_log/packets.jsonl'),(evidence/'packets.jsonl').read_bytes())
                self.assertEqual(archive.read('board_log/board_log.txt'),(evidence/'board_log.txt').read_bytes())
                for name,digest in json.loads(archive.read('sha256.json')).items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
            restored=board_history.load_job(job.out)
            self.assertEqual(restored.board_log_state,'ready');self.assertFalse(restored.integrity_error)

    def test_tampered_or_latest_failed_records_never_fall_back_to_uart(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,evidence=network_fixture(Path(tmp))
            with patch.object(s.UART,'snapshot',side_effect=AssertionError('No UART fallback')):
                job.board_log_state='error';job.board_log_error='OFFLINE incomplete read'
                self.assertFalse(s.task_phase_timing(job)['available'])
                with self.assertRaises(ValueError):s.task_acceptance(1,job,{})
                job.board_log_state='ready';(evidence/'task_log.bin').write_bytes(b'tampered')
                self.assertFalse(s.task_phase_timing(job)['available'])
                with self.assertRaises(ValueError):s.task_acceptance(1,job,{})

    def test_get_is_passive_explicit_read_of_history_only_uses_saved_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,evidence=network_fixture(Path(tmp));run=SimpleNamespace(board_job=job)
            with patch.object(s,'_run',return_value=run),\
                 patch.object(s.board_link.socket,'socket',side_effect=AssertionError('No new UDP owner')),\
                 patch.object(s.UART,'snapshot',side_effect=AssertionError('No UART')):
                self.assertTrue(s.api_task_timing(1)['available'])
                result=s.api_board_records(1)
                self.assertFalse(result['refreshed']);self.assertEqual(result['board_log']['state'],'ready')

if __name__=='__main__':unittest.main()
