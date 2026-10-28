"""Real owner loop with an injected socket; never contacts a board or service."""
from pathlib import Path
from types import SimpleNamespace
import json,tempfile,time,unittest
from unittest.mock import patch
from sim.host.test_gcs_network_verifiers import RecordsSocket,boot_artifact,BUILD,BOOT,link,m,candidate,board_log,gcs_model_verify
import board_history

class NetworkOwner(unittest.TestCase):
    def wait(self,predicate):
        end=time.monotonic()+8
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.008)
        self.fail('Injected Ethernet owner did not reach expected state')
    def source(self,root):
        c,parts=candidate('longkou');c['version']='v2';startup=boot_artifact(root/'startup')
        source=link.BoardSource(root/'history',lambda *args:(c,parts))
        source.authorize('12345678',True,BUILD['release_id'],str(startup),str(startup/'elf_audit.json'))
        return source,c
    def ready_model(self,source):
        self.wait(lambda:source.describe()['model_operation'].get('board_log',{}).get('state')=='ready')
        return source.operation.out

    def test_model_only_records_and_explicit_recovery_preserve_original_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,c=self.source(root);sock=RecordsSocket()
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    source.request_models('upload','longkou','v2',activate=True)
                    out=self.ready_model(source);self.assertTrue(gcs_model_verify.verify(out)['data_acceptance'])
                    self.assertEqual(factory.call_count,1);self.assertFalse(any(p[2]==1 for p in sock.sent))
                    channel=source.channel_out.name;session=source.session
                finally:source.shutdown()
            restored=link.BoardSource(root/'history');restored.release_id=BUILD['release_id'];before=len(sock.sent)
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    restored.recover_models(channel,True);out=self.ready_model(restored)
                    self.assertEqual(restored.session,session);self.assertEqual(factory.call_count,1)
                    self.assertTrue(gcs_model_verify.verify(out)['data_acceptance'])
                    self.assertTrue(all(p[2] in (5,7,board_log.QUERY) for p in sock.sent[before:]))
                    self.assertEqual(restored.network_startup,source.network_startup)
                finally:restored.shutdown()
            self.assertFalse(restored.worker.is_alive());self.assertTrue(sock.closed)

    def test_task_probe_history_and_recovery_read_on_owned_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,c=self.source(root);sock=RecordsSocket();events=[]
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    source.request_models('upload','longkou','v2',activate=True);self.ready_model(source)
                    run=SimpleNamespace(id=1,kind='region',scene='longkou',version='v2',rect=[549,399,1,1])
                    source.start(run,lambda *a:None,events.append);self.wait(lambda:events==['done'])
                    job=run.board_job;first=Path(job.board_log_evidence);original=(first/'packets.jsonl').read_bytes()
                    source.probe(job,549,399,m.candidate_identity(c))
                    self.wait(lambda:job.probe_result['state']=='done' and job.board_log_evidence!=str(first))
                    self.assertIn(b'PROBE',board_log.audit(job.board_log_evidence,BOOT,source.session,job.audit.task)['task_log'])
                    self.assertEqual((first/'packets.jsonl').read_bytes(),original)
                    source.read_evidence(job);self.assertEqual(factory.call_count,1)
                    run2=SimpleNamespace(id=2,kind='region',scene='longkou',version='v2',rect=[548,398,1,1])
                    source.start(run2,lambda *a:None,events.append);self.wait(lambda:events==['done','done'])
                    with self.assertRaises(ValueError):source.read_evidence(job)
                    board_log.audit(job.board_log_evidence,BOOT,source.session,job.audit.task)
                    self.assertEqual(factory.call_count,1)
                finally:source.shutdown()
            job=board_history.load_job(run2.board_job.out);self.assertFalse(job.integrity_error,job.error)
            saved=job.board_log_evidence;restored=link.BoardSource(root/'history');restored.release_id=BUILD['release_id'];before=len(sock.sent);done=[]
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    restored.recover(job,True,(lambda *a:None,done.append,None));self.wait(lambda:done==['done'])
                    self.assertNotEqual(job.board_log_evidence,saved);self.assertEqual(job.board_log_state,'ready')
                    self.assertTrue(any(p[2]==board_log.QUERY for p in sock.sent[before:]))
                    self.assertFalse(any(p[2] in (1,4) for p in sock.sent[before:]))
                    restored.read_evidence(job)
                finally:restored.shutdown()

    def test_failed_latest_model_read_cannot_reuse_older_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,c=self.source(Path(tmp));sock=RecordsSocket()
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.request_models('query');self.ready_model(source)
                    sock.bad_records=True;source.request_models('query')
                    self.wait(lambda:source.describe()['model_operation'].get('board_log',{}).get('state')=='error')
                    with self.assertRaises(ValueError):gcs_model_verify.verify(source.operation.out)
                    self.assertFalse(any(p[2] in (1,m.WACT) for p in sock.sent))
                finally:source.shutdown()

if __name__=='__main__':unittest.main()
