"""Lifecycle candidate fixtures; no real socket/UART/model or hardware actions."""
from pathlib import Path
import sys,struct,tempfile,unittest,queue,time
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_task as t
import board_history
w=t.wire

def status(task=0,state=0,done=0,rect=(548,395,2,5),session=42,boot=0x12345678):
    y,x,h,width=rect
    body=struct.pack('<IIfffBBH',done,h*width if task else 0,*([float('nan')]*3),state,0,0)
    body+=struct.pack('<IIIHBB8IHHI',boot,session,w.WCRC,y+done//width if task else 0,1,0,*([0]*8),0,0,0)
    return w.packet(0x82,task,100,100,body)
def row(task,y,x,n,word=0xffff0002,flags=0):
    return w.packet(0x81,task,101,101,struct.pack('<4H',y,x,n,flags)+struct.pack(f'<{n}I',*([word]*n)))
def ack(task,kind,seq,value=0):return w.packet(0x83,task,100,100,struct.pack('<BBHI',kind,0,seq,value))

def info(task=1,session=42,boot=0x12345678,rect=(548,395,2,5),state=2,done=0):
    y,x,h,width=rect
    return w.packet(0x86,task,100,100,struct.pack('<IBBBBIHBB4HIHBB',boot,1,3,16,0,session,task,1,0,y,x,h,width,w.WCRC,y+done//width,state,0))

class AuditTests(unittest.TestCase):
    def test_info_is_strict_and_mismatch_never_marks_recovery_confirmed(self):
        a=self.ready();a.begin_recovery();a.sent(w.packet(7,0,10,1,b''))
        with self.assertRaisesRegex(ValueError,'mismatch'):a.received(info(task=7,boot=99))
        self.assertFalse(a.accepted_via_info)
        a.received(info(task=7));self.assertTrue(a.accepted_via_info)
        for off,value in ((17,2),(18,32),(43,1)):
            b=bytearray(info(task=7));b[off]=value
            with self.assertRaises(ValueError):t.decode(b)

    def test_running_repair_waits_for_aged_frontier_and_rate_limits(self):
        a=self.ready();schedule=t.RepairSchedule()
        a.received(status(7,1,5));schedule.observe(10,a)
        self.assertEqual(schedule.due(10.49,a),[])
        self.assertEqual(schedule.due(11.49,a),[548])
        self.assertEqual(schedule.due(11.8,a),[])
        a.received(row(7,548,395,5));self.assertEqual(schedule.due(12.5,a),[])
        self.assertEqual(struct.unpack('<6H',t.row_request([1,2,4])),(2,0,1,2,4,1))
    def test_board_timing_is_not_receive_elapsed_and_old_codec_remains_strict(self):
        a=self.ready();packet=bytearray(status(7,1,5));struct.pack_into('<f',packet,20,5.0)
        d=a.received(bytes(packet));self.assertEqual(d['ms_per_px'],5.0)
        j=t.Job(0x12345678,42,7,[548,395,2,5],False);j.audit=a
        self.assertEqual(j.snapshot()['performance']['pixels_per_second'],200)
        self.assertEqual(j.snapshot()['performance']['computed_pixels'],5)
        with self.assertRaises(ValueError):w.decode(bytes(packet))
        for ms in (0,-1,float('inf')):
            struct.pack_into('<f',packet,20,ms)
            with self.assertRaises(ValueError):t.decode(bytes(packet))
        packet=bytearray(status(7,1,5));struct.pack_into('<f',packet,24,30)
        with self.assertRaises(ValueError):t.decode(bytes(packet)) # no invented temperature
    def ready(self):
        a=t.Audit(0x12345678,42,7,[548,395,2,5],False)
        a.sent(w.packet(1,7,1,1,a.start_body()));a.received(ack(7,1,1));return a
    def test_roi_and_tail_absolute_coordinates(self):
        a=self.ready();a.received(row(7,549,395,5));a.received(status(7,3,10))
        self.assertFalse(a.complete());self.assertEqual(a.missing_rows(),[548])
        a.sent(w.packet(6,7,2,2,struct.pack('<4H',1,0,548,1)))
        a.received(row(7,548,395,5,flags=1));self.assertTrue(a.complete());self.assertEqual(a.count,10)
        a.received(row(7,548,395,5));self.assertEqual(a.count,10)
        with self.assertRaisesRegex(ValueError,'conflicting'):a.received(row(7,548,395,5,word=1))
        self.assertEqual(a.rows[548][395],0xffff0002)
    def test_old_task_does_not_contaminate_and_boot_error_fatal(self):
        a=self.ready();self.assertIsNone(a.received(row(6,548,395,5)))
        self.assertEqual(a.count,0)
        with self.assertRaisesRegex(ValueError,'boot/session'):a.received(status(7,1,5,boot=9))
    def test_runtime_failure_is_not_discarded_after_start_ack(self):
        a=self.ready();a.commands.clear()
        packet=w.packet(0x83,7,99,99,struct.pack('<BBHI',1,6,1,0xfffffffb))
        with self.assertRaisesRegex(ValueError,'runtime failure'):a.received(packet)
    def test_stop_is_partial_not_done(self):
        a=self.ready();a.received(row(7,548,395,5));a.received(status(7,0,5))
        self.assertTrue(a.complete());self.assertEqual(a.final['state'],0)
        with self.assertRaisesRegex(ValueError,'incomplete DONE'):a.received(status(7,3,5))
    def test_terminal_equal_count_wrong_coordinates_never_completes(self):
        for terminal_first in (False,True):
            with self.subTest(terminal_first=terminal_first):
                a=self.ready()
                if terminal_first:
                    a.received(status(7,0,5))
                    with self.assertRaisesRegex(ValueError,'frontier'):a.received(row(7,549,395,5))
                    self.assertEqual(a.count,0)
                else:
                    a.received(row(7,549,395,5))
                    with self.assertRaisesRegex(ValueError,'frontier'):a.received(status(7,0,5))
                self.assertFalse(a.complete())
    def test_rect_validation_no_clamping(self):
        for r in ([549,399,2,1],[-1,0,1,1],[0,0,1,True],[0,0,0,1]):
            with self.assertRaises(ValueError):t.rect_for(dict(kind='region',scene='longkou',version='v2',rect=r))
        self.assertEqual(t.rect_for(dict(kind='region',scene='longkou',version='v2',rect=[549,399,1,1])),[549,399,1,1])

class FixtureSocket:
    def __init__(self):self.rx=queue.Queue();self.sent=[];self.mode='manual';self.rect=[548,395,2,5];self.session=0;self.task=0;self.closed=False;self.drop_control=False;self.state=1;self.done=0
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def bind(self,addr):pass
    def settimeout(self,n):pass
    def put(self,p):self.rx.put((p,w.TARGET))
    def sendto(self,data,addr):
        self.sent.append(data);_,kind,_,task,seq,stamp=w.HEADER.unpack_from(data)
        if kind==7:
            self.put(info(self.task,self.session,getattr(self,'boot',0x12345678),self.rect,self.state,self.done))
        elif kind==5:
            self.session=struct.unpack_from('<I',data,12)[0]
            self.put(w.packet(0x84,self.task,0,0,struct.pack('<HHII',seq,0,stamp,0)))
            if not self.task:self.put(status(session=self.session))
            else:self.put(status(self.task,self.state,self.done,self.rect,self.session))
        elif kind==1:
            self.state=1;self.done=0
            self.task=task;self.rect=list(struct.unpack_from('<4H',data,16));self.put(ack(task,1,seq))
            self.put(status(task,1,0,self.rect,self.session))
            if self.mode=='complete':
                y,x,h,width=self.rect
                self.put(row(task,y,x,width));self.put(status(task,3,h*width,self.rect,self.session))
                self.state=3;self.done=h*width
        elif kind in (2,3,4):
            self.state={2:0,3:2,4:1}[kind]
            if not self.drop_control:self.put(ack(task,kind,seq,self.rect[0]))
            self.put(status(task,{2:0,3:2,4:1}[kind],0,self.rect,self.session))
        elif kind==6:
            self.put(ack(task,6,seq,1));y,x,h,width=self.rect
            for r in range(y,y+self.done//width):self.put(row(task,r,x,width,flags=1))
        elif kind==9:
            r,c=struct.unpack_from('<HH',data,14)
            body=struct.pack('<HBBHHII9i',seq,0,9,r,c,w.WCRC,0xffff0002,0,0,10,0,0,0,0,0,0)
            self.put(w.packet(0x85,task,102,102,body))
        return len(data)
    def recvfrom(self,n):
        try:return self.rx.get(timeout=.01)
        except queue.Empty:raise t.socket.timeout()

class SourceTests(unittest.TestCase):
    def wait(self,fn):
        end=time.monotonic()+3
        while time.monotonic()<end:
            if fn():return
            time.sleep(.01)
        self.fail('fixture condition timed out')
    def test_restart_is_passive_then_explicit_recovery_only_info_ping_rowreq(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=t.BoardSource(root);source.authorize('12345678',True)
            sock=FixtureSocket();events=[]
            run=SimpleNamespace(id=17,kind='region',scene='longkou',version='v2',rect=[548,395,2,5])
            with patch.object(t.socket,'socket',return_value=sock):
                source.start(run,lambda *a:None,events.append)
                self.wait(lambda:source.job and source.job.audit.ack and not source.job.command)
                source.shutdown()
            with patch.object(t.socket,'socket',side_effect=AssertionError('passive restore')):
                jobs,errors=board_history.load_all(root)
                self.assertEqual(errors,[]);self.assertEqual(len(jobs),1)
                job=jobs[0];self.assertEqual(job.state,'error');self.assertEqual(job.audit.count,0)
                restored=t.BoardSource(root)
            peer=FixtureSocket();peer.task=job.audit.task;peer.session=job.audit.session;peer.state=3;peer.done=10
            recovered=[]
            with patch.object(t.socket,'socket',return_value=peer):
                try:
                    restored.recover(job,True,(lambda *a:None,recovered.append,None))
                    self.wait(lambda:recovered==['done'])
                    self.assertEqual(job.audit.count,10);self.assertTrue(job.audit.accepted_via_info)
                    self.assertEqual({p[2] for p in peer.sent},{5,6,7})
                finally:restored.shutdown()
            replay=board_history.load_job(job.out)
            self.assertEqual(replay.state,'done');self.assertEqual(replay.audit.count,10)
            self.assertEqual(replay.host_run['id'],17)
            # A torn last record is not silently ignored or reported complete.
            with (job.out/'packets.jsonl').open('a') as f:f.write('{')
            torn=board_history.load_job(job.out)
            self.assertTrue(torn.integrity_error);self.assertEqual(torn.state,'error')
            with self.assertRaisesRegex(ValueError,'完整性'):restored.recover(torn,True,(None,None,None))

    def test_recovery_wrong_boot_sends_no_ping_start_or_resume(self):
        with tempfile.TemporaryDirectory() as d:
            j=t.Job(0x12345678,42,1,[548,395,2,5],False);j.out=Path(d)
            j.audit.sent(w.packet(1,1,1,1,j.audit.start_body()))
            (j.out/'packets.jsonl').touch()
            sock=FixtureSocket();sock.task=1;sock.session=42;sock.boot=0x99999999
            source=t.BoardSource(Path(d));events=[]
            with patch.object(t.socket,'socket',return_value=sock):
                try:
                    source.recover(j,True,(lambda *a:None,events.append,None));source.worker.join(3)
                    self.assertFalse(source.worker.is_alive());self.assertTrue(j.integrity_error)
                    self.assertEqual([p[2] for p in sock.sent],[7])
                finally:source.shutdown()
    def test_same_peer_pause_resume_stop_new_task_and_bounded_repair(self):
        with tempfile.TemporaryDirectory() as d:
            s=t.BoardSource(Path(d));s.authorize('12345678',True);sock=FixtureSocket();events=[];cells=[]
            def run(i):return SimpleNamespace(id=i,kind='region',scene='longkou',version='v2',rect=[548,395,2,5],board_job=None)
            first=run(1)
            with patch.object(t.socket,'socket',return_value=sock) as factory:
                try:
                    s.start(first,lambda c,l,q:cells.extend(c.tolist()),events.append)
                    self.wait(lambda:s.job and s.job.audit.ack and s.job.command is None)
                    self.assertEqual(s.job.state,'running');s.pause()
                    self.wait(lambda:s.job.state=='paused' and s.job.command is None)
                    s.probe(first.board_job,549,399);self.wait(lambda:s.job.probe_result['state']=='done')
                    self.assertEqual(s.job.state,'paused');self.assertEqual(s.job.audit.count,0)
                    s.resume();self.wait(lambda:s.job.state=='running' and s.job.command is None)
                    s.stop();self.wait(lambda:events==['stopped'])
                    self.assertEqual(first.board_job.snapshot()['received_pixels'],0)
                    sock.mode='complete';second=run(2);s.start(second,lambda c,l,q:cells.extend(c.tolist()),events.append)
                    self.wait(lambda:events==['stopped','done'])
                    self.assertEqual(second.board_job.snapshot()['received_pixels'],10)
                    self.assertEqual(len(cells),10);self.assertEqual(first.board_job.snapshot()['received_pixels'],0)
                    self.assertEqual(factory.call_count,1)
                    self.assertEqual(sum(p[2]==6 for p in sock.sent),1)
                    self.assertNotEqual(first.board_job.audit.task,second.board_job.audit.task)
                    # A periodic metadata refresh must not overwrite the final
                    # export with an empty cells array while the peer stays open.
                    time.sleep(.6)
                    import json
                    self.assertEqual(len(json.loads((second.board_job.out/'summary.json').read_text(encoding='utf-8'))['cells']),10)
                finally:s.shutdown()
                self.assertTrue(sock.closed);self.assertFalse(s.worker.is_alive())
                self.assertEqual(second.board_job.state,'done')
                with self.assertRaises(ValueError):s.start(run(3),lambda *a:None,events.append)
                self.assertEqual(first.board_job.snapshot()['interaction']['state'],'closed')
    def test_lost_stop_ack_never_reports_local_success_and_sends_four_times(self):
        with tempfile.TemporaryDirectory() as d:
            s=t.BoardSource(Path(d));s.authorize('12345678',True);sock=FixtureSocket();sock.drop_control=True;events=[]
            r=SimpleNamespace(id=1,kind='region',scene='longkou',version='v2',rect=[548,395,2,5],board_job=None)
            with patch.object(t.socket,'socket',return_value=sock):
                try:
                    s.start(r,lambda *a:None,events.append)
                    self.wait(lambda:s.job and s.job.audit.ack and s.job.command is None);s.stop()
                    s.worker.join(7)
                    self.assertFalse(s.worker.is_alive());self.assertEqual(len(events),1)
                    self.assertTrue(events[0].startswith('error:'));self.assertEqual(s.job.state,'error')
                    self.assertEqual(sum(p[2]==2 for p in sock.sent),4)
                finally:s.shutdown()
    def test_old_consumed_boot_never_reauthorized(self):
        with tempfile.TemporaryDirectory() as d:
            s=t.BoardSource(Path(d))
            with patch.object(t.socket,'socket',side_effect=AssertionError('no socket')):
                with self.assertRaises(ValueError):s.authorize('bb6bd8e3',True)
                s.authorize('12345678',True)
                self.assertTrue(s.describe()['authorized'])

if __name__=='__main__':unittest.main(verbosity=2)
