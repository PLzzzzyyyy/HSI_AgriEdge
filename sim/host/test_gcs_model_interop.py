"""GCS -> pipe -> compiled private Protocol/Models interop (NOT board testing).

Only socket construction is replaced. Real wire bytes are consumed/produced by
C++; SD/driver/numerics and UART records remain explicitly synthetic fixtures.
"""
from collections import defaultdict,deque
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_link as link
import board_history
import board_models as m
import gcs_model_verify
import gcs_task_verify
from sim.host.test_gcs_upload import candidate as synthetic
PEER=Path(os.environ['GCS_MODEL_PEER']) if os.environ.get('GCS_MODEL_PEER') else None
OUT=Path(os.environ.get('GCS_INTEROP_OUT',ROOT/'build/host/gcs_interop_test'))

class PipePeer:
    def __init__(self,root):
        self.root=root;self.root.mkdir(parents=True);self.log=(root/'pipe.txt').open('w',encoding='utf-8')
        self.error=(root/'peer_stderr.txt').open('w',encoding='utf-8');self.lock=threading.Lock()
        self.process=subprocess.Popen([str(PEER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.error,
            text=True,encoding='ascii',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        ready=self.process.stdout.readline();assert ready.startswith('FIXTURE '),ready;self.log.write(ready);self.log.flush()
        self.start=time.monotonic();self.offset=1000;self.freeze_time=False;self.queues=defaultdict(deque);self.port=1234;self.sockets=[]
        self.uart=['OFFLINE SYNTHETIC IO/NUMERICS - NOT BOARD UART',
            'S2C READY boot_id=12345678 registry=0 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app=model_lifecycle_r1']
    def now(self):return self.offset if self.freeze_time else int((time.monotonic()-self.start)*1e6)+self.offset
    def exchange(self,line):
        with self.lock:
            self.log.write('TX '+line+'\n');self.log.flush()
            self.process.stdin.write(line+'\n');self.process.stdin.flush();state=None
            for row in self.process.stdout:
                self.log.write(row);self.log.flush();row=row.strip()
                if row=='END':return state
                if row.startswith('PACKET '):
                    _,ip,port,hexdata=row.split(' ');self.queues[int(port)].append(bytes.fromhex(hexdata))
                elif row.startswith('LOG '):self.uart.append(row[4:])
                elif row.startswith('STATE '):
                    keys=('task','session','entries','saves','loads','jobs','probes','completed','parked','active_scene','active_crc','files')
                    state=dict(zip(keys,map(int,row[6:].split())))
                elif row.startswith('SCAN '):state=dict(zip(('complete','entries','rejected'),map(int,row[5:].split())))
                elif row.startswith('CONTRACT '):
                    _,name,*values=row.split();record=dict(zip(('width','height','classes','bands','pad','cube_bytes','crc'),map(int,values)))
                    record['scene']=name
                    if state is None:state=[]
                    state.append(record)
                else:raise AssertionError('Unknown peer output: '+row)
            raise AssertionError('Peer unexpectedly ended: '+str(self.process.poll()))
    def socket(self,*args):
        self.port+=1;s=PipeSocket(self,self.port);self.sockets.append(s);return s
    def snapshot(self):return self.exchange('STATE')
    def write_uart(self):
        path=self.root/'fixture_uart.txt';path.write_text('\n'.join(self.uart)+'\n',encoding='utf-8');return path
    def close(self):
        self.write_uart()
        if self.process.poll() is None:
            self.process.stdin.write('QUIT\n');self.process.stdin.flush()
        try:self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.wait();raise AssertionError('Owned fixture failed to exit')
        finally:
            for f in (self.process.stdin,self.process.stdout,self.error,self.log):f.close()
        assert self.process.returncode==0,self.process.returncode

class PipeSocket:
    def __init__(self,peer,port):
        self.peer=peer;self.port=port;self.closed=False;self.drop_ack=set();self.drop_row=None;self.drop_rows=set();self.sent=[]
        self.stall_engine=False;self.chunk_kind=None;self.freeze_on_start=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def bind(self,addr):assert addr==('',0)
    def settimeout(self,value):self.timeout=value
    def sendto(self,data,addr):
        assert addr==link.wire.TARGET;self.sent.append(data)
        if data[2]==m.WCHUNK:self.chunk_kind=data[13]
        if data[2]==1 and self.freeze_on_start:
            self.peer.offset=self.peer.now();self.peer.freeze_time=True;self.freeze_on_start=False
        self.peer.exchange(f'RX {self.peer.now()} 1 {self.port} {data.hex()}');return len(data)
    def recvfrom(self,size):
        self.peer.exchange(f'POLL {self.peer.now()}')
        q=self.peer.queues[self.port]
        while q:
            data=q.popleft()
            if data[2]==0x83 and data[12]==m.WCHUNK and self.chunk_kind==1 and self.stall_engine:continue
            if data[2]==0x83 and data[12] in self.drop_ack:
                self.drop_ack.remove(data[12]);continue
            if data[2]==0x81 and self.drop_row is not None:
                row,col,n,flags=struct.unpack_from('<4H',data,12)
                if (row,col)==self.drop_row and flags==0:self.drop_row=None;continue
            if data[2]==0x81 and self.drop_rows:
                row,col,n,flags=struct.unpack_from('<4H',data,12)
                if (row,col) in self.drop_rows and flags==0:self.drop_rows.remove((row,col));continue
            return data,link.wire.TARGET
        time.sleep(.002);raise link.socket.timeout()

@unittest.skipUnless(PEER,'Run via tools/test_gcs_interop.py to compile the actual private peer')
class Interop(unittest.TestCase):
    def setUp(self):self.peer=PipePeer(OUT/self._testMethodName);self.sources=[]
    def tearDown(self):
        for source in self.sources:source.shutdown()
        self.peer.close()
    def source(self,resolver=link.local_candidate):
        root=self.peer.root/'gcs';root.mkdir(exist_ok=True)
        source=link.BoardSource(root,resolver);self.sources.append(source);return source
    def wait(self,predicate,source,seconds=20):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            if not source.healthy:self.fail('Source failed: '+str(source.operation.error if source.operation else source.job.error if source.job else None))
            time.sleep(.005)
        op=source.operation.snapshot() if source.operation else {}
        self.fail('Interop wait expired; snapshot='+str(self.peer.snapshot())+' op='+str({k:op.get(k) for k in ('action','state','phase','kind','done','error')}))
    def upload(self,source,scene,version='v1',activate=True):
        source.request_models('upload',scene,version,activate=activate)
        self.wait(lambda:source.operation.complete,source)
        self.assertTrue(source.operation.snapshot()['ok'],source.operation.error)
    def test_actual_export_upload_task_segments_probe_and_evidence(self):
        source=self.source();events=[]
        with patch.object(link.socket,'socket',side_effect=self.peer.socket) as factory:
            source.authorize('12345678',True);source.request_models('query');self.wait(lambda:source.channel_ready,source)
            self.peer.sockets[0].drop_ack={m.WCHUNK,m.WACT}
            self.upload(source,'honghu');self.upload(source,'hanchuan')
            self.assertEqual(self.peer.snapshot()['entries'],4)
            self.assertEqual(self.peer.snapshot()['files'],12) # five kind0 files + one engine per scene
            self.assertEqual(self.peer.snapshot()['loads'],2) # lost WACT ACK cannot trigger a second LOAD_W
            self.peer.sockets[0].drop_row=(938,126)
            run=SimpleNamespace(id=1,kind='region',scene='honghu',version='v1',rect=[938,126,2,349])
            source.start(run,lambda *args:None,events.append);self.wait(lambda:events==['done'],source)
            a=run.board_job.audit;self.assertEqual(a.count,698)
            # Completion may precede the next 250-ms STATUS counter update;
            # the received ROW flags, not a stale counter snapshot, prove repair.
            records=[json.loads(line) for line in (run.board_job.out/'packets.jsonl').read_text().splitlines()]
            rows=[bytes.fromhex(r['hex']) for r in records if r['direction']=='rx' and bytes.fromhex(r['hex'])[2]==0x81]
            self.assertTrue(any(struct.unpack_from('<H',p,18)[0]==1 for p in rows))
            self.assertEqual(self.peer.snapshot()['loads'],3);self.assertEqual(self.peer.snapshot()['jobs'],1)
            h,_=source.candidate('hanchuan','v1');source.probe(run.board_job,1216,302,m.candidate_identity(h))
            self.wait(lambda:source.job.probe_result['state']=='done',source)
            run2=SimpleNamespace(id=2,kind='region',scene='hanchuan',version='v1',rect=[1216,302,1,1])
            source.start(run2,lambda *args:None,events.append);self.wait(lambda:events==['done','done'],source)
            self.assertEqual(factory.call_count,1);self.assertEqual(run.board_job.audit.identity['scene'],'honghu')
            source.shutdown()
        uart=self.peer.write_uart();reports=[]
        for job in (run.board_job,run2.board_job):
            self.assertEqual(board_history.load_job(job.out).audit.rows,job.audit.rows)
            result=gcs_task_verify.verify(job.out,uart);self.assertTrue(result['data_acceptance']);reports.append(result)
        for directory in source.root.glob('model_*'):
            result=gcs_model_verify.verify(directory,uart);self.assertTrue(result['data_acceptance'],result);reports.append(result)
        (self.peer.root/'reports.json').write_text(json.dumps(dict(scope='OFFLINE_PIPE_PROTOCOL_ONLY_NOT_BOARD_ACCEPTANCE',reports=reports),indent=2),encoding='utf-8')
    def test_pause_upload_stop_same_session_recovery_and_deferred_switch(self):
        packages={scene:synthetic(scene) for scene in ('longkou','hanchuan')}
        source=self.source(lambda scene,version:packages[scene]);events=[]
        with patch.object(link.socket,'socket',side_effect=self.peer.socket):
            source.authorize('12345678',True);self.upload(source,'longkou')
            self.peer.exchange('STEP 0')
            run=SimpleNamespace(id=1,kind='region',scene='longkou',version='v1',rect=[545,390,5,10])
            source.start(run,lambda *args:None,events.append);self.wait(lambda:source.job and source.job.audit.ack and source.job.command is None,source)
            source.pause();self.wait(lambda:source.job.state=='paused' and source.job.command is None,source)
            source.request_models('upload','hanchuan','v1',activate=True);self.wait(lambda:source.operation.phase=='await_idle',source)
            before=self.peer.snapshot();self.assertEqual(before['loads'],1);source.stop()
            self.wait(lambda:events==['stopped'],source);self.wait(lambda:source.operation.complete,source)
            self.assertTrue(source.operation.snapshot()['ok'],source.operation.error);self.assertEqual(self.peer.snapshot()['loads'],2)
            source.shutdown()
            old=board_history.load_job(run.board_job.out);self.peer.offset+=3000000000;restored=self.source(lambda scene,version:packages[scene]);second=[]
            restored.recover(old,True,(lambda *args:None,second.append,None));self.wait(lambda:second==['stopped'],restored)
            self.assertEqual(self.peer.snapshot()['jobs'],1)
            sent=self.peer.sockets[-1].sent;self.assertFalse(any(p[2] in (1,4) for p in sent))
            self.assertEqual(old.audit.identity['scene'],'longkou');self.assertEqual(self.peer.snapshot()['active_scene'],2)
            restored.shutdown()
    def test_sd_error_and_irreversible_load_fault_never_create_task_success(self):
        packages=synthetic('longkou');source=self.source(lambda *args:packages)
        with patch.object(link.socket,'socket',side_effect=self.peer.socket):
            source.authorize('12345678',True);self.peer.exchange('SDFAIL 1')
            source.request_models('upload','longkou','v1',activate=True);self.wait(lambda:source.operation.complete,source)
            self.assertFalse(source.operation.snapshot()['ok']);self.assertEqual(self.peer.snapshot()['loads'],0)
            self.peer.exchange('SDFAIL 0');self.upload(source,'longkou',activate=False)
            self.peer.exchange('LOADFAIL -203');source.request_models('activate','longkou','v1');self.wait(lambda:source.operation.complete,source)
            self.assertFalse(source.operation.snapshot()['ok']);self.assertTrue(source.healthy);self.assertEqual(self.peer.snapshot()['parked'],0)
            self.peer.exchange('LOADFAIL -55');source.request_models('activate','longkou','v1')
            end=time.monotonic()+10
            while source.worker.is_alive() and time.monotonic()<end:time.sleep(.005)
            self.assertFalse(source.worker.is_alive());self.assertFalse(source.healthy);self.assertEqual(self.peer.snapshot()['parked'],1)
            self.assertEqual(self.peer.snapshot()['jobs'],0)
            with self.assertRaises(ValueError):source.request_models('query')

    def test_unregistered_start_then_interrupted_upload_remains_model_recoverable(self):
        packages=synthetic('longkou');source=self.source(lambda *args:packages);events=[]
        with patch.object(link.socket,'socket',side_effect=self.peer.socket):
            source.authorize('12345678',True)
            run=SimpleNamespace(id=1,kind='region',scene='longkou',version='v1',rect=[0,0,1,1])
            source.start(run,lambda *args:None,events.append);self.wait(lambda:bool(events),source)
            self.assertIsNone(run.board_job.audit.start_seq);self.assertEqual(self.peer.snapshot()['task'],0)
            self.peer.sockets[0].stall_engine=True;source.request_models('upload','longkou','v1',activate=True)
            self.wait(lambda:any(p[2]==m.WCHUNK and p[13]==1 for p in self.peer.sockets[0].sent),source)
            source.shutdown();self.peer.offset+=1200000
            restored=self.source(lambda *args:packages)
            channel=source.channel_out.name
            entry=next(r for r in restored.model_channels() if r['channel']==channel)
            self.assertTrue(entry['recoverable'],entry)
            restored.recover_models(channel,True);self.wait(lambda:restored.channel_ready,restored)
            self.upload(restored,'longkou')
            self.assertEqual(self.peer.snapshot()['jobs'],0);self.assertEqual(self.peer.snapshot()['entries'],2)

    def test_hanchuan_609_fragmented_missing_rows_repair_through_real_queue(self):
        packages=synthetic('hanchuan');source=self.source(lambda *args:packages);events=[]
        with patch.object(link.socket,'socket',side_effect=self.peer.socket):
            source.authorize('12345678',True);self.upload(source,'hanchuan')
            # Freeze only once START is actually sent. Freezing beforehand can
            # also suppress the mandatory idle STATUS of the fresh handshake.
            self.peer.sockets[0].freeze_on_start=True
            self.peer.sockets[0].drop_rows={(y,302) for y in range(0,1217,2)}
            run=SimpleNamespace(id=1,kind='region',scene='hanchuan',version='v1',rect=[0,302,1217,1])
            source.start(run,lambda *args:None,events.append);self.wait(lambda:events==['done'],source)
            self.assertEqual(run.board_job.audit.count,1217)
            sent=[p for p in self.peer.sockets[0].sent if p[2]==6]
            self.assertTrue(sent);self.assertEqual(struct.unpack_from('<H',sent[0],12)[0],349)
            self.assertTrue(all(len(p)<=1412 for p in sent));self.assertLessEqual(len(sent),5)
            source.shutdown()
            report=gcs_task_verify.verify(run.board_job.out,self.peer.write_uart())
            self.assertTrue(report['data_acceptance']);self.assertFalse(report['batch_acceptance'])

    def test_uploaded_split_files_reload_from_ram_fs_and_bad_pair_is_not_active(self):
        packages=synthetic('honghu');source=self.source(lambda *args:packages)
        with patch.object(link.socket,'socket',side_effect=self.peer.socket):
            source.authorize('12345678',True);self.upload(source,'honghu');source.shutdown()
        self.assertEqual(self.peer.snapshot()['files'],6)
        scan=self.peer.exchange('RESTART 305419897')
        self.assertEqual(scan,dict(complete=1,entries=2,rejected=0));self.assertEqual(self.peer.snapshot()['active_scene'],-1)
        # Changing only the companion projection makes the surviving engine
        # fail the real pairing check on the next cold-object scan.
        self.peer.exchange('CORRUPT 1:/scenes/honghu/weights/demo/weights_all.bin')
        scan=self.peer.exchange('RESTART 305419898')
        self.assertEqual(scan,dict(complete=1,entries=1,rejected=1));self.assertEqual(self.peer.snapshot()['active_scene'],-1)

    def test_compiled_scene_contract_matches_python_inventory(self):
        contracts=self.peer.exchange('CONTRACTS');self.assertEqual(len(contracts),3)
        for record in contracts:
            spec=m.scene_spec(record['scene'])
            self.assertEqual((record['height'],record['width']),tuple(spec['shape']))
            for key in ('classes','bands','pad','cube_bytes'):self.assertEqual(record[key],spec[key])
            self.assertEqual(record['crc'],int(spec['cube_crc32'],16))

if __name__=='__main__':unittest.main()
