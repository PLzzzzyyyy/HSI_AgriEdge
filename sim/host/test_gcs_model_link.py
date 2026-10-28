"""One injected socket for model+task lifecycle; NO actual UDP/UART/service."""
from pathlib import Path
import hashlib
import json
import queue
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_link as link
import board_history
import board_attention
import board_models as m
import gcs_model_verify
from sim.host.test_gcs_upload import candidate
w=link.wire

class Socket:
    def __init__(self):
        self.queue=queue.Queue();self.sent=[];self.boot=0x12345678;self.session=0;self.task=0;self.scene=0;self.crc=0;self.rect=[0,0,0,0]
        self.state=self.done=0;self.registry=[];self.staging=None;self.buffer=bytearray();self.pieces={};self.closed=False;self.sd_fail=False
        self.tick=0;self.upload_drop=False;self.dropped=False;self.complete_tasks=True;self.load_error=False;self.stall_engine=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def bind(self,addr):self.local=addr
    def settimeout(self,t):pass
    def recvfrom(self,n):
        try:return self.queue.get(timeout=.003),w.TARGET
        except queue.Empty:raise link.socket.timeout()
    def emit(self,kind,body,task=None):
        self.tick+=1;self.queue.put(w.packet(kind,self.task if task is None else task,self.tick,self.tick*1000,body))
    def status(self):
        y,x,h,width=self.rect;front=y+self.done//width if width else 0
        b=struct.pack('<IIfffBBH',self.done,h*width,*([float('nan')]*3),self.state,0,0)
        b+=struct.pack('<IIIHBB8IHHI',self.boot,self.session,self.crc,front,1,0,*([0]*8),0,0,0);self.emit(0x82,b)
    def info(self):
        y,x,h,width=self.rect
        b=struct.pack('<IBBBBIHBB4HIHBB',self.boot,1,4,16,len(self.registry),self.session,self.task,1 if self.task else 0,
                      self.scene,y,x,h,width,self.crc if self.task else 0,y+self.done//width if width else 0,self.state,0)
        for e in self.registry:b+=struct.pack('<BBHII16s',e['scene'],e['kind'],0,e['bytes'],int(e['wcrc'],16),e['tag'].encode())
        self.emit(0x86,b+bytes.fromhex('1'*32))
    def ack(self,kind,seq,code=0,value=0):self.emit(0x83,struct.pack('<BBHI',kind,code,seq,value),task=self.request_task)
    def row(self,y):
        x,width=self.rect[1],self.rect[3];n=m.scene_spec(self.scene)['classes'];word=0xffff0000|n-1
        self.emit(0x81,struct.pack('<4H',y,x,width,0)+struct.pack(f'<{width}I',*([word]*width)))
    def sendto(self,data,peer):
        assert peer==w.TARGET;self.sent.append(data);_,kind,_,task,seq,stamp=w.HEADER.unpack_from(data)
        self.request_task=task
        if kind==7:self.info()
        elif kind==5:
            self.session=struct.unpack_from('<I',data,12)[0];self.emit(0x84,struct.pack('<HHII',seq,0,stamp,stamp));self.status()
        elif kind==m.WBEGIN:
            scene,k,pad,total,crc,tag=m.BEGIN.unpack_from(data,12);key=(scene,k,total,crc,m.decode_tag(tag))
            if self.staging!=key:self.staging=key;self.buffer=bytearray()
            self.ack(kind,seq,value=len(self.buffer))
        elif kind==m.WCHUNK:
            sc,k,pad,off,total,crc=m.CHUNK.unpack_from(data,12);raw=data[28:]
            if off==len(self.buffer):self.buffer.extend(raw)
            elif off+len(raw)>len(self.buffer) or self.buffer[off:off+len(raw)]!=raw:self.ack(kind,seq,2,len(self.buffer));return len(data)
            if k==1 and self.stall_engine:pass
            elif self.upload_drop and not self.dropped:self.dropped=True
            else:self.ack(kind,seq,value=off+len(raw))
        elif kind==m.WCOMMIT:
            requested=struct.unpack_from('<I',data,12)[0]
            if self.staging is None or self.staging[3]!=requested:
                assert any(e['wcrc']==f'{requested:08x}' for e in self.registry)
                self.ack(kind,seq,4 if self.sd_fail else 0,0 if self.sd_fail or self.state in (1,2) else 1);return len(data)
            scene,k,total,crc,tag=self.staging;assert len(self.buffer)==total and zlib.crc32(self.buffer)==crc
            key=(scene,k,tag);self.pieces[key]=bytes(self.buffer)
            if not any(e['scene']==scene and e['kind']==k and e['tag']==tag for e in self.registry):
                self.registry.append(dict(scene=scene,kind=k,bytes=total,wcrc=f'{crc:08x}',tag=tag))
            self.ack(kind,seq,4 if self.sd_fail else 0,0 if self.sd_fail or self.state in (1,2) else 1)
        elif kind==m.WACT:
            if self.load_error:self.ack(kind,seq,6,0xfffffffb)
            else:
                # WACT must not rewrite the previous task's STATUS identity.
                if not self.task:self.crc=struct.unpack_from('<I',data,16)[0]
                self.ack(kind,seq)
        elif kind==1:
            mode,scene,slot,pad,y,x,h,width,crc,session=struct.unpack_from('<BBBB4HII',data,12)
            self.task=task;self.scene=scene;self.crc=crc;self.rect=[y,x,h,width];self.done=0;self.state=1;self.ack(kind,seq)
            if self.complete_tasks:
                self.done=h*width;self.state=3
                for yy in range(y,y+h):self.row(yy)
            self.status()
        elif kind in (2,3,4):
            self.state={2:0,3:2,4:1}[kind];self.ack(kind,seq);self.status()
        elif kind==6:
            n,_=struct.unpack_from('<HH',data,12)
            for off in range(16,16+4*n,4):
                row,count=struct.unpack_from('<HH',data,off)
                for yy in range(row,row+count):self.row(yy)
            self.ack(kind,seq)
        elif kind==9:
            scene,pad,row,col,res,crc=struct.unpack_from('<BBHHHI',data,12);n=m.scene_spec(scene)['classes'];values=[0]*(n-1)+[777]
            self.emit(0x85,struct.pack('<HBBHHII',seq,scene,n,row,col,crc,0xffff0000|n-1)+struct.pack(f'<{n}i',*values))
            # ABI4 requests require both raw attention fragments as well as LOGITS.
            # Deliberately reversed order exercises the production reassembler.
            raw=struct.pack('<432I',*([1<<24,0,0,0,0,0]*72));tensor_crc=zlib.crc32(raw)
            for part in (1,0):
                meta=board_attention.META.pack(seq,scene,n,row,col,crc,self.boot,self.session,tensor_crc,
                    432,part,2,part*216,216,12,6,24,0)
                self.emit(0x87,meta+raw[part*864:(part+1)*864])
        else:raise AssertionError(kind)
        return len(data)

class ModelLinkTests(unittest.TestCase):
    def wait(self,test,seconds=7):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if test():return
            time.sleep(.008)
        self.fail('Fixture state did not reach expected condition')

    def test_query_upload_activate_tasks_probe_and_history_one_socket(self):
        c,parts=candidate('honghu');c['version']='v1';h,hanparts=candidate('hanchuan');h['version']='v1'
        def resolve(scene,vid):self.assertEqual(vid,'v1');return (c,parts) if scene=='honghu' else (h,hanparts)
        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),resolve);sock=Socket();sock.upload_drop=True;events=[]
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    self.assertFalse(source.describe()['active']);self.assertEqual(factory.call_count,0)
                    source.authorize('12345678',True);source.request_models('query')
                    self.wait(lambda:source.operation.complete and source.channel_ready)
                    self.assertFalse(any(p[2]==1 for p in sock.sent))
                    for scene in ('honghu','hanchuan'):
                        source.request_models('upload',scene,'v1',activate=True)
                        self.wait(lambda:source.operation.complete)
                        self.assertTrue(source.operation.snapshot()['ok'],source.operation.error)
                        self.assertTrue(source.operation.snapshot()['persisted']);self.assertTrue(source.operation.activated)
                    run=SimpleNamespace(id=1,kind='region',scene='honghu',version='v1',rect=[939,474,1,1])
                    source.start(run,lambda *a:None,events.append);self.wait(lambda:events==['done'])
                    self.assertEqual(run.board_job.snapshot()['class_counts'][-1],1)
                    source.probe(run.board_job,1216,302,m.candidate_identity(h));self.wait(lambda:source.job.probe_result['state']=='done')
                    self.assertEqual(source.job.probe_result['class_id'],15);self.assertEqual(source.job.audit.counts[-1],1)
                    self.assertEqual(source.job.probe_result['attention_shape'],[12,6,6])
                    self.assertEqual(len(source.job.probe_result['attention_q24']),432)
                    first=run.board_job
                    run2=SimpleNamespace(id=2,kind='region',scene='hanchuan',version='v1',rect=[1216,302,1,1])
                    source.start(run2,lambda *a:None,events.append);self.wait(lambda:events==['done','done'])
                    self.assertEqual(factory.call_count,1);self.assertEqual(first.snapshot()['scene'],'honghu')
                    self.assertEqual(first.snapshot()['wcrc'],c['wcrc']);self.assertEqual(run2.board_job.snapshot()['wcrc'],h['wcrc'])
                finally:source.shutdown()
            self.assertTrue(sock.closed);self.assertFalse(source.worker.is_alive())
            replay=board_history.load_job(first.out);self.assertFalse(replay.integrity_error,replay.error)
            self.assertEqual(replay.audit.identity,m.candidate_identity(c));self.assertEqual(replay.probes[-1]['class_id'],15)
            self.assertEqual(board_history.load_job(run2.board_job.out).state,'done')
            summaries=list(Path(tmp).glob('model_*/summary.json'));self.assertEqual(len(summaries),3)
            self.assertTrue(all(json.loads(p.read_text())['ok'] for p in summaries))
            for summary in summaries:
                result=gcs_model_verify.verify(summary.parent)
                self.assertTrue(result['packet_checks_passed']);self.assertFalse(result['data_acceptance'])
                self.assertIsNone(result['uart_confirmed'])
                meta=json.loads((summary.parent/'session.json').read_text());cand=meta['candidate']
                lines=['S2C READY boot_id=12345678 registry=4 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app=model_lifecycle_r1']
                for r in result['acks']:
                    if r['type'] in (m.WCOMMIT,m.WACT):
                        sc=m.scene_spec(cand['scene'])['id'] if r['type']==m.WACT else -1;crc=cand['wcrc'] if r['type']==m.WACT else '00000000'
                        lines.append(f'S2C MODELCMD session={meta["session"]:08x} type={r["type"]} seq={r["seq"]} code={r["code"]} value={r["value"]:08x} crc={r["crc"]:08x} active_scene={sc} active_crc={crc} sd_rc=0')
                uart=summary.parent/'fixture_uart.txt';uart.write_text('\n'.join(lines)+'\n')
                self.assertTrue(gcs_model_verify.verify(summary.parent,uart)['data_acceptance'])
                if cand:
                    raw=(summary.parent/'kind1.bin').read_bytes();changed=bytearray(raw);changed[-1]^=1;(summary.parent/'kind1.bin').write_bytes(changed)
                    with self.assertRaisesRegex(ValueError,'SHA'):gcs_model_verify.verify(summary.parent,uart)
                    (summary.parent/'kind1.bin').write_bytes(raw)
                    metadata=summary.parent/'session.json';original=metadata.read_bytes()
                    altered=json.loads(original);altered['candidate']['wcrc']='12345678'
                    metadata.write_text(json.dumps(altered),encoding='utf-8')
                    with self.assertRaisesRegex(ValueError,'CRC'):gcs_model_verify.verify(summary.parent,uart)
                    metadata.write_bytes(original)
            # Explicit same-task recovery reuses persisted identity, not START.
            restored=board_history.load_job(run2.board_job.out);source2=link.BoardSource(Path(tmp),resolve);events2=[]
            sock.closed=False;before=len(sock.sent)
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source2.recover(restored,True,(lambda *a:None,events2.append,None));self.wait(lambda:events2==['done'])
                    self.assertFalse(any(p[2] in (1,4) for p in sock.sent[before:]))
                    self.assertEqual(restored.audit.identity,m.candidate_identity(h))
                finally:source2.shutdown()

    def test_wrong_boot_no_ping_or_start_and_sd_failure_no_act(self):
        c,parts=candidate()
        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),lambda *args:(c,parts));sock=Socket();sock.boot=5
            with patch.object(link.socket,'socket',return_value=sock):
                source.authorize('12345678',True);source.request_models('query');source.worker.join(3)
                self.assertFalse(source.worker.is_alive());self.assertFalse(source.healthy)
                self.assertEqual([p[2] for p in sock.sent],[7])
        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),lambda *args:(c,parts));sock=Socket();sock.sd_fail=True
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.authorize('12345678',True);source.request_models('upload','honghu','v1',activate=True)
                    self.wait(lambda:source.operation.complete)
                    self.assertFalse(source.operation.snapshot()['ok']);self.assertFalse(source.operation.snapshot()['persisted'])
                    self.assertNotIn(m.WACT,[p[2] for p in sock.sent]);self.assertNotIn(1,[p[2] for p in sock.sent])
                finally:source.shutdown()

    def test_missing_registration_does_not_start_or_prevent_explicit_upload(self):
        c,parts=candidate()
        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),lambda *args:(c,parts));sock=Socket();events=[]
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.authorize('12345678',True)
                    run=SimpleNamespace(id=1,kind='region',scene='honghu',version='v1',rect=[939,474,1,1])
                    source.start(run,lambda *a:None,events.append);self.wait(lambda:bool(events))
                    self.assertTrue(run.board_job.preflight_rejected);self.assertTrue(source.healthy)
                    self.assertFalse(any(p[2]==1 for p in sock.sent))
                    with self.assertRaises(ValueError):source.probe(run.board_job,939,474)
                    source.request_models('upload','honghu','v1',activate=True);self.wait(lambda:source.operation.complete)
                    self.assertTrue(source.operation.snapshot()['ok'],source.operation.error)
                    run2=SimpleNamespace(id=2,kind='region',scene='honghu',version='v1',rect=[939,474,1,1])
                    source.start(run2,lambda *a:None,events.append);self.wait(lambda:events[-1]=='done')
                    self.assertEqual(run.board_job.audit.count,0);self.assertIsNone(run.board_job.audit.start_seq)
                finally:source.shutdown()

    def test_upload_while_paused_waits_for_stop_then_persists_and_switches(self):
        c,parts=candidate('honghu');h,hp=candidate('hanchuan')
        def resolve(scene,vid):return (c,parts) if scene=='honghu' else (h,hp)
        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),resolve);sock=Socket();sock.complete_tasks=False;events=[]
            sock.registry=[dict(scene=1,kind=p['kind'],bytes=p['bytes'],wcrc=p['crc32'],tag='demo') for p in c['parts']]
            with patch.object(link.socket,'socket',return_value=sock):
                try:
                    source.authorize('12345678',True)
                    run=SimpleNamespace(id=1,kind='region',scene='honghu',version='v1',rect=[939,474,1,1])
                    source.start(run,lambda *a:None,events.append);self.wait(lambda:source.job and source.job.audit.ack and source.job.command is None)
                    source.pause();self.wait(lambda:source.job.state=='paused' and source.job.command is None)
                    source.request_models('upload','hanchuan','v1',activate=True)
                    self.wait(lambda:source.operation.phase=='await_idle')
                    self.assertIsNot(source.operation.snapshot()['persisted'],True);self.assertFalse(any(p[2]==m.WACT for p in sock.sent))
                    source.stop();self.wait(lambda:events==['stopped']);self.wait(lambda:source.operation.complete)
                    self.assertTrue(source.operation.snapshot()['ok'],source.operation.error);self.assertTrue(source.operation.activated)
                    self.assertEqual(run.board_job.snapshot()['wcrc'],c['wcrc'])
                finally:source.shutdown()

    def test_model_only_restart_explicit_query_then_engine_partial_resume(self):
        c,parts=candidate()
        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),lambda *args:(c,parts));sock=Socket();sock.stall_engine=True
            with patch.object(link.socket,'socket',return_value=sock):
                source.authorize('12345678',True);source.request_models('upload','honghu','v1',activate=True)
                self.wait(lambda:sock.staging is not None and sock.staging[1]==1 and len(sock.buffer)>0)
                source.shutdown()
            partial=len(sock.buffer);self.assertLess(partial,len(parts[1]));channel=source.channel_out.name
            restored=link.BoardSource(Path(tmp),lambda *args:(c,parts));sock.closed=False;sock.stall_engine=False;before=len(sock.sent)
            with patch.object(link.socket,'socket',return_value=sock) as factory:
                try:
                    self.assertEqual(factory.call_count,0);self.assertTrue(restored.model_channels()[0]['recoverable'])
                    restored.recover_models(channel,True);self.wait(lambda:restored.operation.complete and restored.channel_ready)
                    self.assertEqual(set(p[2] for p in sock.sent[before:]),{5,7})
                    before=len(sock.sent);restored.request_models('upload','honghu','v1',activate=True)
                    self.wait(lambda:restored.operation.complete);self.assertTrue(restored.operation.snapshot()['ok'],restored.operation.error)
                    chunks=[p for p in sock.sent[before:] if p[2]==m.WCHUNK and p[13]==1]
                    self.assertEqual(struct.unpack_from('<I',chunks[0],16)[0],partial)
                    self.assertFalse(any(p[2]==m.WBEGIN and p[13]==0 for p in sock.sent[before:]))
                    self.assertFalse(any(p[2]==1 for p in sock.sent))
                finally:restored.shutdown()
            with (source.channel_out/'packets.jsonl').open('a') as f:f.write('{')
            with self.assertRaisesRegex(ValueError,'截断'):link.BoardSource(Path(tmp)).recover_models(channel,True)

class TaskDeadlineTests(unittest.TestCase):
    """A slow previous-task archive must not spend an unsent INFO's timeout."""
    wait=ModelLinkTests.wait

    def archive_then_start(self,drop_info=False):
        c,parts=candidate('honghu');c['version']='v1'
        offset=[0.0]
        clock=SimpleNamespace(monotonic=lambda:time.monotonic()+offset[0],
                              perf_counter_ns=time.perf_counter_ns,time=time.time)

        class QueuedStatusSocket(Socket):
            def __init__(self):
                super().__init__();self.followup_info=[]

            def sendto(self,data,peer):
                if data[2]==7 and self.task:
                    self.followup_info.append(clock.monotonic())
                    if drop_info:
                        self.sent.append(data);return len(data)
                return super().sendto(data,peer)

        with tempfile.TemporaryDirectory() as tmp:
            source=link.BoardSource(Path(tmp),lambda *args:(c,parts));sock=QueuedStatusSocket();events=[]
            sock.registry=[dict(scene=1,kind=p['kind'],bytes=p['bytes'],wcrc=p['crc32'],tag=c['tag']) for p in c['parts']]
            first=None;delayed=[];save=link.t.save_json

            def slow_archive(path,value):
                if first and source.pending and Path(path)==first.out/'summary.json' and not delayed:
                    # Inject local serialization time, not network delay. A
                    # queued old STATUS precedes the new INFO_R, as on board.
                    offset[0]+=2.5;delayed.append(True);sock.status()
                save(path,value)

            with patch.object(link.socket,'socket',return_value=sock) as factory, \
                 patch.object(link,'time',clock),patch.object(link.t,'save_json',side_effect=slow_archive):
                try:
                    source.authorize('12345678',True)
                    run=SimpleNamespace(id=1,kind='region',scene='honghu',version='v1',rect=[939,474,1,1])
                    source.start(run,lambda *args:None,events.append);self.wait(lambda:len(events)==1)
                    self.assertEqual(events,['done']);first=run.board_job
                    previous=first.snapshot()
                    run2=SimpleNamespace(id=2,kind='region',scene='honghu',version='v1',rect=[938,473,1,1])
                    source.start(run2,lambda *args:None,events.append);self.wait(lambda:len(events)==2)
                    ended=clock.monotonic()
                    self.assertEqual(delayed,[True]);self.assertEqual(factory.call_count,1)
                    self.assertEqual(first.snapshot()['cells'],previous['cells'])
                    self.assertEqual(first.audit.task,1);self.assertEqual(run2.board_job.audit.task,2)
                    if drop_info:
                        self.assertTrue(events[-1].startswith('error:'),events)
                        self.assertIsNone(run2.board_job.audit.start_seq)
                        self.assertEqual(run2.board_job.audit.count,0)
                        self.assertEqual(len(sock.followup_info),4)
                        self.assertGreaterEqual(ended-sock.followup_info[0],1.19)
                        self.assertFalse(any(p[2]==1 and w.HEADER.unpack_from(p)[3]==2 for p in sock.sent))
                    else:
                        self.assertEqual(events,['done','done'],run2.board_job.error)
                        self.assertTrue(source.healthy);self.assertEqual(run2.board_job.audit.count,1)
                        self.assertEqual(len(sock.followup_info),1)
                finally:source.shutdown()
            self.assertTrue(sock.closed);self.assertFalse(source.worker.is_alive())
            replay=board_history.load_job(first.out)
            self.assertFalse(replay.integrity_error,replay.error);self.assertEqual(replay.audit.count,1)

    def test_new_task_gets_fresh_info_deadline_after_slow_terminal_archive(self):
        self.archive_then_start()

    def test_missing_info_still_retries_and_fails_closed_without_start(self):
        self.archive_then_start(drop_info=True)


if __name__=='__main__':unittest.main()
