"""Offline injected owner: deferred records, controls, cancellation and overflow."""
from pathlib import Path
from types import SimpleNamespace
import json,struct,tempfile,threading,time,unittest
from unittest.mock import patch
from sim.host import test_gcs_network_owner as owner

link=owner.link
board_log=owner.board_log

class LifecycleSocket(owner.RecordsSocket):
    def __init__(self):
        super().__init__()
        self.complete_tasks=False
        self.reads=[];self.hold_controls=False;self.controls=[]
        self.drop_records=False;self.read_started=threading.Event();self.source=None

    def sendto(self,data,target):
        if data[2]==board_log.QUERY:
            operation=self.source.operation if self.source else None
            job=self.source.job if self.source else None
            self.reads.append(dict(state=self.state,control=bool(self.controls),
                transfer=bool(operation and not operation.complete),
                command=bool(job and job.command),recovering=bool(job and job.recovering)))
            self.read_started.set()
            if self.drop_records:
                self.sent.append(data);return len(data)
        if self.hold_controls and data[2] in (2,3,4):
            self.sent.append(data);self.controls.append(data);return len(data)
        return super().sendto(data,target)

    def reply_control(self):
        data=self.controls.pop(0);kind=data[2]
        self.request_task,seq=struct.unpack_from('<HH',data,4)
        self.state={2:0,3:2,4:1}[kind];self.ack(kind,seq);self.status()

class NetworkLifecycle(unittest.TestCase):
    wait=owner.NetworkOwner.wait
    source=owner.NetworkOwner.source
    ready_model=owner.NetworkOwner.ready_model

    def begin_task(self,source,sock):
        sock.source=source
        source.request_models('upload','longkou','v2',activate=True);self.ready_model(source)
        run=SimpleNamespace(id=1,kind='region',scene='longkou',version='v2',rect=[549,399,1,1])
        events=[];source.start(run,lambda *args:None,events.append)
        self.wait(lambda:source.job and source.job.audit.ack and source.job.command is None)
        sock.reads.clear();return run.board_job,events

    def assert_reads_idle(self,sock):
        self.assertTrue(sock.reads)
        self.assertTrue(all(r['state'] not in (1,2) and not any(r[k] for k in
            ('control','transfer','command','recovering')) for r in sock.reads),sock.reads)

    def test_running_paused_and_inflight_controls_defer_all_model_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,_=self.source(Path(tmp));sock=LifecycleSocket()
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    job,events=self.begin_task(source,sock)
                    pending=[]
                    for control in (source.pause,source.resume,source.stop):
                        source.request_models('query');operation=source.operation;pending.append(operation)
                        self.wait(lambda:getattr(operation,'board_log',{}).get('state')=='pending_idle')
                        sock.hold_controls=True;control();self.wait(lambda:bool(sock.controls))
                        self.assertEqual(sock.reads,[])
                        self.assertTrue(all(p.board_log['state']=='pending_idle' for p in pending))
                        with source.lock:sock.reply_control();sock.hold_controls=False
                        self.wait(lambda:job.command is None)
                    self.wait(lambda:events==['stopped'])
                    self.wait(lambda:all(p.board_log['state']=='ready' for p in pending))
                    self.assert_reads_idle(sock);self.assertEqual(factory.call_count,1)
                    for operation in pending:
                        self.assertTrue(owner.gcs_model_verify.verify(operation.out)['data_acceptance'])
                finally:source.shutdown()
            self.assertFalse(source.worker.is_alive());self.assertTrue(sock.closed)

    def test_paused_upload_does_not_lose_model_acks_to_terminal_log_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,_=self.source(Path(tmp));sock=LifecycleSocket()
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    job,events=self.begin_task(source,sock)
                    source.pause();self.wait(lambda:job.state=='paused' and job.command is None)
                    source.request_models('upload','longkou','v2',activate=True)
                    self.wait(lambda:source.operation.phase=='await_idle')
                    self.assertEqual(sock.reads,[])
                    source.stop();self.wait(lambda:events==['stopped'])
                    self.ready_model(source)
                    self.wait(lambda:job.board_log_state=='ready')
                    self.assertTrue(owner.gcs_model_verify.verify(source.operation.out)['data_acceptance'])
                    self.assert_reads_idle(sock);self.assertEqual(factory.call_count,1)
                finally:source.shutdown()

    def test_shutdown_finishes_every_deferred_receipt_without_reading_or_sending_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,_=self.source(Path(tmp));sock=LifecycleSocket()
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    self.begin_task(source,sock);pending=[]
                    for _ in range(2):
                        source.request_models('query');operation=source.operation;pending.append(operation)
                        self.wait(lambda:getattr(operation,'board_log',{}).get('state')=='pending_idle')
                    source.shutdown()
                    for operation in pending:
                        saved=json.loads((operation.out/'summary.json').read_text())
                        self.assertEqual(saved['board_log']['state'],'error')
                        self.assertIsNotNone(saved['board_log']['error'])
                        self.assertFalse(owner.gcs_model_verify.verify(operation.out)['data_acceptance'])
                    self.assertEqual(sock.reads,[])
                    self.assertFalse(any(p[2]==2 for p in sock.sent))
                finally:source.shutdown()
            self.assertFalse(source.worker.is_alive());self.assertTrue(sock.closed)

    def test_shutdown_cancels_unanswered_record_page_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,_=self.source(Path(tmp));sock=LifecycleSocket();sock.source=source;sock.drop_records=True
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.request_models('query');self.assertTrue(sock.read_started.wait(3))
                    start=time.monotonic();source.shutdown()
                    self.assertLess(time.monotonic()-start,1.0)
                    self.assertFalse(source.worker.is_alive());self.assertTrue(sock.closed)
                    saved=json.loads((source.operation.out/'summary.json').read_text())
                    self.assertEqual(saved['board_log']['state'],'error')
                    receipt=json.loads((Path(saved['board_log']['evidence'])/'receipt.json').read_text())
                    self.assertEqual(receipt['result'],'FAIL');self.assertIn('cancel',receipt['error'].lower())
                    self.assertFalse(any(p[2] in (1,2,4,owner.m.WACT) for p in sock.sent))
                finally:source.shutdown()

    def test_model_overflow_preserves_older_evidence_but_never_reuses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,_=self.source(Path(tmp));sock=LifecycleSocket();sock.source=source
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.request_models('query');old=self.ready_model(source)
                    good=Path(source.operation.board_log['evidence']);before=(good/'packets.jsonl').read_bytes()
                    sock.bad_records=True;source.request_models('query')
                    self.wait(lambda:getattr(source.operation,'board_log',{}).get('state')=='error')
                    self.assertIn('overflow',source.operation.board_log['error'])
                    with self.assertRaises(ValueError):
                        owner.gcs_model_verify.verify(source.operation.out)
                    self.assertEqual((good/'packets.jsonl').read_bytes(),before)
                    self.assertTrue(owner.gcs_model_verify.verify(old)['data_acceptance'])
                    self.assertTrue(source.healthy)
                finally:source.shutdown()

if __name__=='__main__':unittest.main()
