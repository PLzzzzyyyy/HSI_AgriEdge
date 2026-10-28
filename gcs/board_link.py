"""Model-enabled production GCS owner, reusing the private v1 task audit.

Construction, UI refresh and history loading are passive. Only explicit user
START / model query-transfer / recovery creates the sole UDP socket. It is not
the v0 fake board or a PC inference source.
"""
import copy
from datetime import datetime
import json
from pathlib import Path
import secrets
import socket
import struct
import threading
import time
import re
import board_display as display
import zlib
import board_keys
import board_power

import board_task as t
import board_models as m
import board_log
from board_upload import Transfer,IO_TIMEOUT

wire=t.wire
CHANNEL_SECONDS=6*3600  # observation bound, NOT task performance or driver time

def local_candidate(scene,version):
    import engine as E
    version=E.version(scene,version)
    if not version.get('pkg'):raise ValueError('该版本尚无配套int16板端导出包')
    candidate=m.load_candidate(E.DATA,scene,version['pkg']);candidate['version']=version['id']
    return candidate,m.package_parts(E.DATA,scene,version['pkg'])

class BoardSource(t.BoardSource):
    def __init__(self,root=None,resolver=local_candidate):
        super().__init__(root)
        self.root=Path(self.root);self.resolver=resolver
        self.channel_out=None;self.channel_ready=False;self.channel_info=None
        self.registry=[];self.operation=None;self.operation_out=None;self.on_model=None
        self.known_tasks=set();self.latest_task=0;self.model_records=[]
        self.release_id=None
        self.network_startup=None;self.build_evidence=None;self.evidence_sequence=0;self.evidence_request=None
        self.display_pending=None;self.display_status=dict(state='idle');self.display_serial=0
        self.temperature_sample=None;self.temperature_received=0.
        self.power_sample=None;self.power_received=0.
        self.mirror_request=None;self.mirror_png=None;self.mirror_at=0.;self.mirror_counter=secrets.randbelow(2**31)+1
        self.display_observer_until=0.
        self.key_events=[];self.key_responses=[];self.key_seen={};self.keys_enabled=True;self.key_executing=False;self.key_thread=None
        self.terminal_resume_pending=False

    def telemetry(self):
        data=super().telemetry();sample=self.temperature_sample or {}
        age=time.monotonic()-self.temperature_received
        valid=sample.get('valid',False) and age<3 and sample.get('sample_age_ms',9999)<3000 and bool(self.worker and self.worker.is_alive())
        data.update(device='AXU5EV-E · 芯片温度 / 芯片功耗 / 任务能耗',temp_c=sample.get('temp_c') if valid else None,
                    temp_peak_c=sample.get('temp_peak_c') if valid else None,temp_state='valid' if valid else 'stale' if sample else 'unavailable',
                    temp_age_s=round(age,1) if sample else None,temp_source='PS_SYSMON_DIE',display=dict(self.display_status))
        estimate=self.power_sample or {};power_age=time.monotonic()-self.power_received
        fresh=bool(estimate) and power_age<3 and estimate['sample_age_ms']<3000 and bool(self.worker and self.worker.is_alive())
        data.update(power_w=None,power_est_w=estimate.get('power_est_w') if fresh else None,
                    power_est_state='valid' if fresh else 'stale' if estimate else 'unavailable',
                    power_estimate=dict(estimate,age_s=round(power_age,1)) if estimate else None)
        return data

    def take_key(self):
        with self.lock:return self.key_events.pop(0) if self.key_events else None

    def receive_key(self,data):
        with self.lock:
            event=board_keys.decode(data,self.boot,self.session)
            known=self.key_seen.get(event['id'])
            if known:
                if any(known[k]!=event[k] for k in ('key','gesture','boot_id','session','requested_scene')):raise ValueError('Key event replay changed')
                self.key_responses.append(known)
            elif self.key_seen and event['id']<=max(self.key_seen):
                self.key_responses.append(dict(event,state=4,code=4))
            else:
                result=dict(event,state=2,code=12 if event['gesture']==3 else 11)
                if self.key_events or self.key_executing:result.update(state=4,code=2)
                else:self.key_events.append(event)
                self.key_seen[event['id']]=result;self.key_responses.append(result)
                if len(self.key_seen)>256:del self.key_seen[min(self.key_seen)]

    def finish_key(self,event,state=3,code=0,scene=None):
        with self.lock:
            if (event['boot_id'],event['session'])!=(self.boot,self.session):return
            result=dict(event,state=state,code=code,scene=scene or event['scene'])
            self.key_seen[event['id']]=result;self.key_responses.append(result)

    def queue_display(self,job,revision,parcel,row,threshold,name_bits):
        with self.lock:
            if job is not self.job or not self.healthy or not self.channel_ready or not self.worker or not self.worker.is_alive():raise ValueError('请恢复当前任务连接后同步；历史任务不能覆盖 DP')
            if self.display_pending:raise ValueError('上次地块同步尚未确认')
            self.display_serial=(self.display_serial+1)&0xffffffff or 1
            body=display.parcel_body(job,revision,parcel,row,threshold,name_bits,self.display_serial)
            self.display_pending=dict(body=body,job=job,serial=self.display_serial,next=0.,attempts=0,seq=None,deadline=time.monotonic()+5)
            self.display_status=dict(state='queued',serial=self.display_serial,revision=revision,parcel_id=parcel['id'] if parcel else None,run_id=(job.host_run or {}).get('id'))
            return dict(self.display_status)

    def request_mirror(self):
        with self.lock:
            if not self.healthy or not self.channel_ready or not self.worker or not self.worker.is_alive():raise ValueError('请先连接板卡或恢复任务连接')
            if not self.mirror_request:
                self.mirror_counter=(self.mirror_counter+1)&0xffffffff or 1
                self.mirror_request=dict(id=self.mirror_counter,offset=0,data=bytearray(),next=0.,deadline=time.monotonic()+12,crc=None,total=None)
            self.display_observer_until=time.monotonic()+15
            return self.mirror_request['id']

    def authorize(self,text,confirmed,release_id=None,network_startup=None,build_evidence=None,terminal_info=None):
        if release_id is not None and (not isinstance(release_id,str) or not re.fullmatch('[0-9a-f]{64}',release_id)):
            raise ValueError('Invalid reviewed release identity')
        if terminal_info is None:super().authorize(text,confirmed)
        else:
            boot=wire.boot_value(text)
            if confirmed is not True or not terminal_info.get('terminal_owned') or terminal_info['boot_id']!=boot or terminal_info['state'] not in (0,3):
                raise ValueError('需明确确认同一启动的空闲终端连接')
            if boot in (*t.legacy.OLD_BOOTS,0xbb6bd8e3) or not boot:raise ValueError('旧启动禁止重用')
            with self.lock:
                if self.worker and self.worker.is_alive():raise ValueError('已有活动连接，不能替换')
                self.boot=boot;self.job=self.pending=None;self.session=None;self.next_task=1;self.sequence=0;self.healthy=True
        with self.lock:
            self.release_id=release_id
            self.temperature_sample=None;self.temperature_received=0.;self.mirror_png=None;self.mirror_request=None
            self.power_sample=None;self.power_received=0.
            self.display_pending=None;self.display_status=dict(state='idle')
            self.key_events=[];self.key_responses=[];self.key_seen={}
            self.network_startup=network_startup;self.build_evidence=build_evidence
            self.evidence_sequence=0;self.evidence_request=None
            self.registry=[];self.channel_info=None;self.channel_ready=False;self.channel_out=None
            self.operation=None;self.operation_out=None;self.known_tasks=set();self.latest_task=0;self.model_records=[]
            self.terminal_resume_pending=False
        return self.describe()

    def describe(self):
        s=super().describe()
        s.update(label='板卡 · 三景多模型',capabilities=dict(roi=True,controls=True,probe=True,rowreq=True,models=True),
                 channel_ready=self.channel_ready,registry=copy.deepcopy(self.registry),
                 model_operation=self.model_snapshot(self.operation) if self.operation else None,
                 authorized=bool(self.boot and self.healthy and (self.session is None or s['active'])))
        s['model_channel']=self.channel_out.name if self.channel_out else None
        s['release_id']=self.release_id
        s['connection_transport']='ethernet' if self.network_startup else None
        s['startup_evidence']=self.network_startup
        s['evidence_operation']=bool(self.evidence_request)
        s['physical_keys']=dict(backend_required=False,offline_execution=True,executing=self.key_executing,
            last=copy.deepcopy(self.key_seen[max(self.key_seen)]) if self.key_seen else None)
        return s

    def model_snapshot(self,operation):
        result=operation.snapshot()
        result['board_log']=copy.deepcopy(getattr(operation,'board_log',dict(state='unavailable',error=None,evidence=None)))
        result['board_log']['required']=bool(self.network_startup)
        return result

    def restore_network_records(self,meta,boot):
        """Restore only validated local context, before opening a recovery socket."""
        data=meta.get('host_run') or meta
        startup=data.get('network_startup');binding=data.get('build_evidence')
        if not startup:
            self.network_startup=self.build_evidence=None
            return
        from board_release import expected_build
        expected=expected_build(binding)
        if meta.get('release_id')!=expected['release_id'] or self.release_id not in (None,expected['release_id']):
            raise ValueError('恢复记录的App/源码/ELF绑定不符')
        replay=board_log.audit(Path(startup)/'board_log',boot,0,0)
        parsed=board_log.parse_boot(replay['boot_log'],expected)
        if parsed['boot_id']!=boot or parsed['state']!='ready':raise ValueError('恢复缺少同启动的完整以太网就绪记录')
        self.release_id=expected['release_id'];self.network_startup=startup;self.build_evidence=binding

    def read_evidence(self,job,timeout=10):
        """Explicit refresh, marshalled onto the existing sole UDP owner."""
        with self.lock:
            if not self.network_startup or not self.build_evidence:raise ValueError('尚无可信以太网启动证据')
            if job is not self.job or not self.worker or not self.worker.is_alive() or not self.healthy:
                raise ValueError('原任务连接不在；只能读取已保存证据，不另起UDP接管')
            if job.state not in ('done','stopped') or job.error or job.command or job.recovering:
                raise ValueError('只能回读健康终态任务的板端记录')
            if self.pending or self.operation and not self.operation.complete or job.probe_result and job.probe_result['state'] in ('queued','running'):
                raise ValueError('请先结束任务/模型/探查操作')
            if self.evidence_request is None:
                job.board_log_state='queued';job.board_log_error=None;job.board_log_event=threading.Event();self.evidence_request=job
            elif self.evidence_request is not job:raise ValueError('已有其他证据回读')
            event=job.board_log_event
        if not event.wait(timeout):raise TimeoutError('等待板端证据回读超时；不打开另一连接')
        with self.lock:
            if job.board_log_state!='ready':raise ValueError(job.board_log_error or '板端记录未完整回读')
            return job.board_log_evidence

    def candidate(self,scene,version):
        candidate,parts=self.resolver(scene,version)
        if candidate['scene']!=scene:raise ValueError('Candidate scene mismatch')
        m.candidate_identity(candidate)
        return candidate,parts

    def _claim(self,purpose,session=None):
        if self.session is not None:return
        self.session=session or secrets.randbits(32) or 1
        self.root.mkdir(parents=True,exist_ok=True);(self.root/'boots').mkdir(exist_ok=True)
        self.channel_out=self.root/datetime.now().strftime('channel_%Y%m%d_%H%M%S_%f');self.channel_out.mkdir()
        # Exclusive persistent claim before first network traffic. No old boot
        # reuse and no hidden fresh-session takeover of an existing task.
        try:
            with (self.root/'boots'/f'{self.boot:08x}.json').open('x',encoding='utf-8') as f:
                json.dump(dict(boot_id=f'{self.boot:08x}',session=self.session,claimed=t.legacy.now(),purpose=purpose,
                               channel=str(self.channel_out),model_lifecycle=True),f);f.flush();t.os.fsync(f.fileno())
        except Exception:
            self.session=None;raise
        t.save_json(self.channel_out/'session.json',dict(boot_id=self.boot,session=self.session,target=self.addr,scope='MODEL_LIFECYCLE_CHANNEL',release_id=self.release_id,network_startup=self.network_startup,build_evidence=self.build_evidence))

    def resume_terminal(self,info):
        """Explicit idle-terminal handoff after CRC-verified INFO; never resumes a job."""
        if not info.get('terminal_owned') or info['boot_id']!=self.boot or info['state'] not in (0,3):
            raise ValueError('终端尚未空闲或启动身份不符')
        session=info['session'] or secrets.randbits(32) or 1
        claim=self.root/'boots'/f'{self.boot:08x}.json'
        if claim.exists():
            old=json.loads(claim.read_text(encoding='utf-8'))
            if old['session']!=session:raise ValueError('终端会话与本机原始连接记录不符')
            self.session=session
            self.channel_out=self.root/datetime.now().strftime('channel_%Y%m%d_%H%M%S_%f');self.channel_out.mkdir()
            t.save_json(self.channel_out/'session.json',dict(boot_id=self.boot,session=session,target=self.addr,
                scope='EXPLICIT_IDLE_TERMINAL_HANDOFF',release_id=self.release_id,network_startup=self.network_startup,
                build_evidence=self.build_evidence,terminal_info=info))
        else:self._claim('terminal_reconnect',session=session)
        self.next_task=info['task']+1
        self.known_tasks={info['task']} if info['task'] else set()
        self.latest_task=info['task'];self.sequence=0;self.terminal_resume_pending=True

    def _launch(self):
        if self.worker and self.worker.is_alive():return
        self.cancel.clear();self.worker=threading.Thread(target=self._work,name='gcs-model-task-owner',daemon=False);self.worker.start()

    def validate(self,cmd):
        t.rect_for(cmd)
        if not self.boot or not self.healthy:raise ValueError('请先连接板卡并等待新启动就绪')
        if self.pending or self.job and self.job.state not in ('done','stopped') and not getattr(self.job,'preflight_rejected',False):raise ValueError('当前任务尚未结束')
        if self.operation and not self.operation.complete:raise ValueError('模型事务尚未确认')
        if self.evidence_request:raise ValueError('请等待上一任务板端记录回读结束')
        if self.job and (self.job.command or self.job.probe_result and self.job.probe_result['state'] in ('queued','running')):
            raise ValueError('任务控制或探查尚未结束')
        if self.session is not None and not (self.worker and self.worker.is_alive()):raise ValueError('原连接已关闭；需要显式恢复，不能新建任务掩盖状态')
        if self.session is None and (self.root/'boots'/f'{self.boot:08x}.json').exists():raise ValueError('旧启动已使用，不能自动重发任务')
        if self.next_task>65535:raise ValueError('任务号已用尽，需要新启动')
        return self.candidate(cmd['scene'],cmd['version'])[0]

    def start(self,run,on_chunk,on_done,pace_rows=0,on_update=None):
        with self.lock:
            candidate=self.validate(dict(kind=run.kind,scene=run.scene,version=run.version,rect=run.rect))
            self.display_pending=None;self.display_status=dict(state='idle')
            self._claim('task');fresh=not self.known_tasks
            rect=t.rect_for(dict(kind=run.kind,scene=run.scene,rect=run.rect))
            j=t.Job(self.boot,self.session,self.next_task,rect,fresh,identity=m.candidate_identity(candidate));self.next_task+=1
            j.lock=self.lock;j.candidate=candidate;j.callbacks=(on_chunk,on_done,on_update)
            j.out=self.root/datetime.now().strftime('task_%Y%m%d_%H%M%S_%f');j.out.mkdir()
            j.host_run=dict(id=run.id,kind=run.kind,scene=run.scene,version=run.version,rect=run.rect,t0=getattr(run,'t0',time.time()),
                            origin=getattr(run,'origin',None),
                            uart_evidence=None if self.network_startup else getattr(run,'uart_evidence',None),
                            network_startup=self.network_startup,build_evidence=self.build_evidence)
            run.board_job=j;run.lock=self.lock;self.pending=j;self._launch()

    def request_models(self,action,scene=None,version=None,activate=False,on_update=None):
        with self.lock:
            if action!='query' and self.key_executing and self.key_thread!=threading.get_ident():
                raise ValueError('板载按键操作尚未确认，请稍候切换模型')
            if action not in ('query','upload','activate'):raise ValueError('未知模型操作')
            if not self.boot or not self.healthy:raise ValueError('新启动身份尚未就绪或故障未解除')
            if self.evidence_request:raise ValueError('请等待板端记录回读结束')
            if self.pending or self.job and self.job.recovering:raise ValueError('先完成任务启动/恢复')
            if self.operation and not self.operation.complete:raise ValueError('已有模型事务，不能并发上传')
            if self.job and self.job.probe_result and self.job.probe_result['state'] in ('queued','running'):raise ValueError('先等待单点探查完成')
            if self.session is not None and not (self.worker and self.worker.is_alive()) and not self.terminal_resume_pending:raise ValueError('连接已关闭；需显式恢复同一会话')
            candidate,parts=self.candidate(scene,version) if action!='query' else (None,None)
            session=self.session or secrets.randbits(32) or 1
            # A host job can be rejected before any START reached the board.
            # Model traffic uses the last actually transmitted task identity,
            # never that unstarted host job (which cannot be task-recovered).
            operation=Transfer(self.boot,session,action,candidate,parts,activate,task=self.latest_task) # validate BEFORE consuming boot
            self.root.mkdir(parents=True,exist_ok=True)
            out=self.root/datetime.now().strftime('model_%Y%m%d_%H%M%S_%f');out.mkdir()
            operation.out=out;operation.callback=on_update
            if action=='upload':
                for kind,raw in enumerate(parts):(out/f'kind{kind}.bin').write_bytes(raw)
            t.save_json(out/'session.json',dict(boot_id=self.boot,session=session,action=action,candidate=candidate,
                activate=activate,target=self.addr,scope='MODEL_TRANSACTION',release_id=self.release_id,network_startup=self.network_startup,build_evidence=self.build_evidence))
            self._claim('models',session);self.operation=operation;self.operation_out=out
            self.on_model=on_update;self._launch();return self.operation.snapshot()

    def _model_channel(self,name):
        if not isinstance(name,str) or not re.fullmatch(r'channel_\d{8}_\d{6}_\d{6}',name):raise ValueError('模型连接目录标识无效')
        directory=(self.root/name).resolve()
        if not directory.is_relative_to(self.root.resolve()):raise ValueError('模型连接目录越界')
        meta=json.loads((directory/'session.json').read_text(encoding='utf-8'))
        boot,session=meta.get('boot_id'),meta.get('session')
        if self.release_id is not None and meta.get('release_id')!=self.release_id:raise ValueError('记录来自旧版或另一App发布；仅可离线查看')
        if meta.get('scope')!='MODEL_LIFECYCLE_CHANNEL' or tuple(meta.get('target',()))!=self.addr or any(type(v) is not int or not 0<v<2**32 for v in (boot,session)):
            raise ValueError('不是可恢复的模型专用会话')
        if boot in (*t.legacy.OLD_BOOTS,0xbb6bd8e3):raise ValueError('旧启动禁止重用')
        claim=json.loads((self.root/'boots'/f'{boot:08x}.json').read_text(encoding='utf-8'))
        if (claim.get('boot_id'),claim.get('session'))!=(f'{boot:08x}',session):raise ValueError('启动占用记录与模型连接不符')
        next_seq=0
        for line in (directory/'packets.jsonl').read_text(encoding='utf-8').splitlines(keepends=True):
            if not line.endswith('\n'):raise ValueError('模型连接日志截断')
            rec=json.loads(line)
            if tuple(rec.get('peer',()))!=self.addr:raise ValueError('模型连接peer不符')
            data=bytes.fromhex(rec['hex'])
            if len(data)<12:raise ValueError('模型连接包截断')
            magic,kind,version,task,seq,stamp=wire.HEADER.unpack_from(data)
            if magic!=0x4548 or version!=1:raise ValueError('模型连接头错误')
            if task:raise ValueError('连接含任务身份；请在任务历史页恢复对应任务，不接管为模型会话')
            if kind==board_log.QUERY and rec['direction']=='tx':
                q=board_log._query(data)
                if q['boot']!=boot or q['session'] not in (0,session):raise ValueError('恢复模型记录查询身份不符')
                continue # diagnostic sequence is not a command/heartbeat sequence
            if kind==board_log.REPLY and rec['direction']=='rx':
                page=board_log.decode(data)
                if page['boot']!=boot or page['session'] not in (0,session):raise ValueError('恢复模型记录页身份不符')
                continue
            if rec['direction']=='rx' and len(data)==20 and kind==0x83 and data[12]==board_log.QUERY:continue
            if rec['direction']=='rx' and kind==display.TEMP:
                display.temperature(data,boot,session);continue
            if rec['direction']=='rx' and kind==board_power.MESSAGE:
                board_power.decode(data,boot,session);continue
            if rec['direction']=='tx' and kind==display.MIRROR:
                if len(data)!=28 or struct.unpack_from('<II',data,12)!=(boot,session):raise ValueError('镜像记录身份不符')
                next_seq=(seq+1)&65535;continue
            if rec['direction']=='rx' and kind==display.FRAME:
                if len(data)<40:raise ValueError('镜像记录截断')
                display.frame_chunk(data,boot,session,struct.unpack_from('<I',data,20)[0]);continue
            if rec['direction']=='rx' and kind==0x83 and len(data)==20 and data[12]==display.MIRROR:continue
            if rec['direction']=='tx':
                if kind not in (5,7,m.WBEGIN,m.WCHUNK,m.WCOMMIT,m.WACT):raise ValueError('模型日志含非模型任务')
                if kind==5 and data[12:]!=struct.pack('<I',session):raise ValueError('恢复会话PING不符')
                if kind==7 and len(data)!=12:raise ValueError('恢复INFO格式错误')
                if kind==m.WBEGIN:
                    if len(data)!=40:raise ValueError('恢复WBEGIN格式错误')
                    sc,k,pad,size,crc,tag=m.BEGIN.unpack_from(data,12)
                    expected=m.ENGINE_BYTES if k==1 else sum(n for _,n in m.part_files(sc)) if k==0 else 0
                    if sc>2 or k>1 or pad or not crc or size!=expected:raise ValueError('恢复WBEGIN身份错误')
                    m.decode_tag(tag)
                if kind==m.WCHUNK:
                    if not 28<len(data)<=1412:raise ValueError('恢复WCHUNK格式错误')
                    sc,k,pad,off,size,crc=m.CHUNK.unpack_from(data,12)
                    expected=m.ENGINE_BYTES if k==1 else sum(n for _,n in m.part_files(sc)) if k==0 else 0
                    if sc>2 or k>1 or pad or not crc or size!=expected or off+len(data)-28>size:raise ValueError('恢复WCHUNK范围错误')
                if kind==m.WCOMMIT and (len(data)!=16 or not struct.unpack_from('<I',data,12)[0]):raise ValueError('恢复WCOMMIT格式错误')
                if kind==m.WACT:
                    if len(data)!=20:raise ValueError('恢复WACT格式错误')
                    sc,when,pad,crc=m.ACT.unpack_from(data,12)
                    if sc>2 or when or pad or not crc:raise ValueError('恢复WACT身份错误')
                next_seq=(seq+1)&65535
            elif rec['direction']=='rx':
                d=t.decode(data)
                if kind not in (0x82,0x83,0x84,0x86):raise ValueError('模型日志出现任务数据')
                if kind==0x82 and (d['done'],d['total'],d['state'])!=(0,0,0):raise ValueError('模型日志存在活动任务状态')
                if kind in (0x82,0x86) and (d['boot_id']!=boot or kind==0x82 and d['session']!=session):raise ValueError('恢复启动/会话不符')
                if kind==0x86 and self.release_id is not None and d.get('release_tag')!=self.release_id[:32]:raise ValueError('恢复记录INFO发布身份不符')
                if kind==0x83 and d['code']==6 and d['value']!=((-203)&0xffffffff):raise ValueError('存在不可恢复的板端故障回执')
            else:raise ValueError('未知模型日志方向')
        return directory,boot,session,next_seq

    def model_channels(self):
        rows=[]
        for directory in sorted(self.root.glob('channel_*'),reverse=True)[:16]:
            try:
                if self.channel_out==directory and self.worker and self.worker.is_alive():raise ValueError('此连接仍有活动网络线程，不重复恢复')
                _,boot,session,_=self._model_channel(directory.name)
                rows.append(dict(channel=directory.name,boot_id=f'{boot:08x}',session=f'{session:08x}',recoverable=True))
            except (ValueError,OSError,KeyError,TypeError) as exc:
                rows.append(dict(channel=directory.name,recoverable=False,error=str(exc)))
        return rows

    def recover_models(self,name,confirmed,on_update=None):
        with self.lock:
            if confirmed is not True:raise ValueError('请明确确认恢复此模型连接；不会自动上传、激活或开始任务')
            if self.worker and self.worker.is_alive():raise ValueError('已有连接，不能重复恢复')
            directory,boot,session,seq=self._model_channel(name)
            self.restore_network_records(json.loads((directory/'session.json').read_text(encoding='utf-8')),boot)
            self.boot=boot;self.session=session;self.sequence=seq;self.channel_out=directory;self.job=self.pending=None
            self.next_task=1;self.known_tasks=set();self.latest_task=0;self.channel_info=None;self.channel_ready=False;self.registry=[];self.healthy=True
            operation=Transfer(boot,session,'query');out=self.root/datetime.now().strftime('model_%Y%m%d_%H%M%S_%f');out.mkdir()
            operation.out=out;operation.callback=on_update
            t.save_json(out/'session.json',dict(boot_id=boot,session=session,action='query',candidate=None,activate=False,target=self.addr,
                channel=str(directory),scope='MODEL_TRANSACTION',explicit_recovery=True,release_id=self.release_id,network_startup=self.network_startup,build_evidence=self.build_evidence))
            self.operation=operation;self.operation_out=out;self._launch();return operation.snapshot()

    def probe(self,job,row,col,identity=None):
        with self.lock:
            if self.key_executing and self.key_thread!=threading.get_ident():
                raise ValueError('板载按键操作尚未确认，请稍候探查')
            if self.operation and not self.operation.complete:raise ValueError('模型事务尚未确认，不能并发探查')
            if job is not self.job or not self.healthy or not self.worker or not self.worker.is_alive() or job.command or job.recovering:
                raise ValueError('当前任务连接不可探查')
            if getattr(job,'preflight_rejected',False) or job.audit.start_seq is None:
                raise ValueError('预检失败或未开始的任务不能探查；请先显式开始有效任务')
            if job.state not in ('running','paused','done','stopped') or not (job.audit.ack or job.audit.accepted_via_info):
                raise ValueError('尚无已确认的健康任务可探查')
            identity=m.task_identity(identity or job.audit.identity);h,width=identity['shape']
            if type(row) is not int or type(col) is not int or not 0<=row<h or not 0<=col<width:raise ValueError('探查坐标越界')
            if job.probe_result and job.probe_result['state'] in ('queued','running'):raise ValueError('已有探查请求')
            if len(job.used_probe_sequences)>=65536:raise ValueError('本任务探查请求标识已用尽；需显式新任务，不重用旧探查标识')
            if not any(e['scene']==m.SCENES.index(identity['scene']) and e['kind']==1 and e['wcrc']==identity['wcrc'] and e['tag']==identity['model'] for e in self.registry):
                raise ValueError('探查模型尚未在该会话登记')
            job.probe_result=dict(state='queued',row=row,col=col,error=None,identity=identity,attention_requested=True)
            return copy.deepcopy(job.probe_result)

    def recover(self,job,confirmed,callbacks):
        with self.lock:
            if not job.audit.model_lifecycle:raise ValueError('旧App历史只读，不能按新版接管')
            if confirmed is not True:raise ValueError('需明确确认恢复同一任务；不自动START/RESUME')
            if self.worker and self.worker.is_alive():raise ValueError('已有活动连接')
            if job.audit.boot in (*t.legacy.OLD_BOOTS,0xbb6bd8e3) or job.integrity_error:raise ValueError('旧启动或证据完整性错误，禁止恢复')
            if self.release_id is not None and json.loads((job.out/'session.json').read_text(encoding='utf-8')).get('release_id')!=self.release_id:
                raise ValueError('任务记录来自旧版或另一App发布；不能恢复')
            self.restore_network_records(json.loads((job.out/'session.json').read_text(encoding='utf-8')),job.audit.boot)
            job.audit.begin_recovery();job.command=None;job.probe_result=None;job.callbacks=callbacks;job.lock=self.lock
            job.used_probe_sequences={p['req_seq'] for p in job.probes}
            job.recovering=True;job.channel_open=True
            self.boot=job.audit.boot;self.session=job.audit.session;self.sequence=getattr(job,'next_sequence',0)
            self.next_task=job.audit.task+1;self.known_tasks={job.audit.task};self.latest_task=job.audit.task
            self.registry=[];self.channel_ready=False;self.channel_info=None;self.operation=None;self.healthy=True;self.pending=job
            self.channel_out=self.root/datetime.now().strftime('channel_%Y%m%d_%H%M%S_%f');self.channel_out.mkdir()
            t.save_json(self.channel_out/'session.json',dict(boot_id=self.boot,session=self.session,target=self.addr,scope='MODEL_LIFECYCLE_RECOVERY',task=job.audit.task,release_id=self.release_id,network_startup=self.network_startup,build_evidence=self.build_evidence))
            self._launch();return job.snapshot(False)

    def close(self):
        if self.operation and not self.operation.complete:raise ValueError('模型事务仍在执行，不能假装已结束')
        super().close()

    def _work(self):
        j=None;trace=None;model_trace=None;current_op=None;hello=None;op_notified=False
        started=time.monotonic();idle_end=started+300;next_ping=0.;pings={};have_pong=False;channel_status=None
        task_start=started;last_rx=started;next_update=0.;notified=False;repair=None;repair_at=0.;repair_retries=0
        info_next=0.;info_tries=0;recovery_status=False
        pending_model_records=[]
        channel=(self.channel_out/'packets.jsonl').open('a',encoding='utf-8')
        def record(file,direction,data):
            if file:
                file.write(json.dumps(dict(direction=direction,peer=self.addr,monotonic_ns=time.perf_counter_ns(),hex=data.hex()))+'\n');file.flush()
        def update(final=False):
            if not j:return
            t.save_json(j.out/'summary.json',j.snapshot(include_cells=final or j.state in ('done','stopped','error')))
            if final:(j.out/'results.csv').write_text(t.csv_text(j.snapshot()),encoding='utf-8-sig')
            if j.callbacks[2]:j.callbacks[2](j.snapshot(False))
        def model_update(operation=None):
            operation=operation or current_op
            if operation:
                s=self.model_snapshot(operation);s['evidence']=str(operation.out);t.save_json(operation.out/'summary.json',s)
                if operation.callback:operation.callback(s)
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.bind(('',0));sock.settimeout(.02)
                def send(kind,body=b'',seq=None,stamp=None,task=None,model=False):
                    if seq is None:seq=self.sequence;self.sequence=(seq+1)&65535
                    if stamp is None:stamp=(time.perf_counter_ns()//1000)&0xffffffff
                    target=(j.audit.task if j else self.latest_task) if task is None else (task or 0)
                    if kind==5 and self.terminal_resume_pending:target=65535
                    data=wire.packet(kind,target,seq,stamp,body)
                    record(channel,'tx',data)
                    if current_op and not current_op.complete:record(model_trace,'tx',data)
                    if j and not model:j.audit.sent(data);record(trace,'tx',data);j.tx_pkts+=1;j.tx_bytes+=len(data);j.next_sequence=self.sequence
                    if kind==5:
                        pings[seq]=stamp
                        if len(pings)>128:pings.pop(next(iter(pings)))
                    if sock.sendto(data,self.addr)!=len(data):raise OSError('Short board UDP send')
                    return seq
                def send_model(kind,body,seq=None):return send(kind,body,seq=seq,task=self.latest_task,model=True)
                def pull_model_evidence(operation):
                    operation.board_log=dict(state='reading',error=None,evidence=None)
                    out=operation.out/'board_logs'/datetime.now().strftime('read_%Y%m%d_%H%M%S_%f')
                    sequence=self.evidence_sequence;self.evidence_sequence=(sequence+128)&65535
                    try:
                        from board_release import expected_build
                        board_log.fetch(sock,self.addr,out,boot=self.boot,session=self.session,task=0,
                            sequence=sequence,expected_build=expected_build(self.build_evidence),
                            on_packet=lambda direction,raw:record(channel,direction,raw),cancelled=self.cancel.is_set)
                        board_log.audit(out,self.boot,self.session,0)
                        (out/'elf_audit.json').write_bytes(Path(self.build_evidence).read_bytes())
                        operation.board_log=dict(state='ready',error=None,evidence=str(out.resolve()))
                    except (OSError,ValueError,RuntimeError) as exc:
                        operation.board_log=dict(state='error',error=str(exc),evidence=str(out.resolve()))
                    model_update(operation)

                def pull_evidence(job):
                    # Health/terminal/idle checks are made while holding this
                    # same producer lock. No second socket or task sequence.
                    job.board_log_state='reading';job.board_log_error=None
                    out=job.out/'board_logs'/datetime.now().strftime('read_%Y%m%d_%H%M%S_%f')
                    sequence=self.evidence_sequence;self.evidence_sequence=(sequence+128)&65535
                    try:
                        from board_release import expected_build
                        expected=expected_build(self.build_evidence)
                        board_log.fetch(sock,self.addr,out,boot=job.audit.boot,session=job.audit.session,task=job.audit.task,
                            sequence=sequence,expected_build=expected,on_packet=lambda direction,raw:record(channel,direction,raw),
                            cancelled=self.cancel.is_set)
                        board_log.audit(out,job.audit.boot,job.audit.session,job.audit.task)
                        (out/'elf_audit.json').write_bytes(Path(self.build_evidence).read_bytes())
                        job.board_log_evidence=str(out.resolve());job.board_log_state='ready'
                    except (OSError,ValueError,RuntimeError) as exc:
                        job.board_log_state='error';job.board_log_error=str(exc)
                    finally:
                        if self.evidence_request is job:self.evidence_request=None
                        if job.board_log_event:job.board_log_event.set()
                    update(True)
                def terminal_evidence(job):
                    if not self.network_startup or not self.build_evidence:return
                    # A terminal STATUS can arrive while a model transaction
                    # is awaiting persistence/activation. Do not consume its
                    # ACKs in the synchronous diagnostic reader.
                    job.board_log_state='queued';job.board_log_error=None;self.evidence_request=job
                    if (self.healthy and self.channel_ready and not self.pending and not job.command and not job.recovering
                        and not (current_op and not current_op.complete or hello and not hello.complete)
                        and not (job.probe_result and job.probe_result['state'] in ('queued','running'))):
                        pull_evidence(job)
                while not self.cancel.is_set() and (self.keys_enabled or time.monotonic()-started<CHANNEL_SECONDS):
                    with self.lock:
                        now=time.monotonic()
                        for event in self.key_responses[:]:
                            send(board_keys.RECEIPT,board_keys.receipt(self.boot,self.session,event['id'],event['state'],event['code'],event['scene']),model=True)
                            self.key_responses.remove(event)
                        dp=self.display_pending
                        if dp:
                            if dp['job'] is not j or now>dp['deadline']:
                                self.display_status.update(state='error',error='地块同步超时或任务已切换');self.display_pending=None
                            elif now>=dp['next']:
                                if dp['seq'] is None:dp['seq']=send(display.PARCEL,dp['body'],model=True)
                                else:send(display.PARCEL,dp['body'],seq=dp['seq'],model=True)
                                dp['next']=now+.4;dp['attempts']+=1
                        mirror=self.mirror_request
                        if mirror:
                            if now>mirror['deadline']:self.mirror_request=None
                            elif now>=mirror['next']:
                                send(display.MIRROR,struct.pack('<IIII',self.boot,self.session,mirror['id'],mirror['offset']),model=True)
                                mirror['next']=now+.3
                        if self.pending:
                            if j:j.channel_open=False;update(True)
                            if trace:trace.close()
                            # Archiving the previous full-scene result can be
                            # slow. Its local I/O is not the new task's wait.
                            now=time.monotonic()
                            j=self.job=self.pending;self.pending=None;task_start=last_rx=now;notified=False;idle_end=None
                            a=j.audit;trace=(j.out/'packets.jsonl').open('a' if j.recovering else 'x',encoding='utf-8')
                            if j.recovering:
                                trace.write(json.dumps(dict(direction='event',event='recovery_begin',at=t.legacy.now()))+'\n');trace.flush()
                                j.recoveries.append(dict(started=t.legacy.now(),previous_error=j.error,state='querying'))
                                hello=None;info_next=0.;info_tries=0;recovery_status=False
                            else:
                                t.save_json(j.out/'session.json',dict(boot_id=a.boot,session=a.session,task=a.task,identity=a.identity,fresh=a.fresh,
                                    rect=[a.y,a.x,a.height,a.width],host_run=j.host_run,target=self.addr,scope='MODEL_TASK_LIFECYCLE',
                                    channel=str(self.channel_out),candidate=j.candidate,source_sha256=wire.sha(Path(__file__)),release_id=self.release_id))
                                hello=Transfer(self.boot,self.session,'query')
                            repair=t.RepairSchedule();repair_at=0.;repair_retries=0;next_update=0.
                        if self.operation is not current_op:
                            if current_op and not op_notified:model_update()
                            if model_trace:model_trace.close()
                            current_op=self.operation;op_notified=False;idle_end=None
                            model_trace=(current_op.out/'packets.jsonl').open('x',encoding='utf-8') if current_op else None
                        running=bool(j and j.state in ('running','paused'))
                        idle=not running and not self.pending and not (j and (j.command or j.recovering or
                            j.probe_result and j.probe_result['state'] in ('queued','running')))
                        if (self.evidence_request is j and j and idle and self.channel_ready and self.healthy
                            and not (current_op and not current_op.complete or hello and not hello.complete)):
                            pull_evidence(j)
                        # Never assign a new wire deadline from a timestamp
                        # captured before blocking snapshots/record reads.
                        now=time.monotonic()
                        transfer=current_op if current_op and not current_op.complete else hello if hello and not hello.complete else None
                        if transfer and (transfer.phase=='query' or self.channel_ready):transfer.tick(now,send_model,idle=idle)
                        # Bind only after an INFO from this boot; a new session
                        # must never claim another current task by sending PING.
                        need_link=bool(self.display_pending or self.mirror_request or transfer or running or current_op and not op_notified or
                            hello and not self.channel_ready or j and (j.command or j.recovering or j.probe_result and j.probe_result['state'] in ('queued','running')))
                        if self.channel_info and (need_link or self.channel_ready) and now>=next_ping:
                            send(5,struct.pack('<I',self.session),task=a.task if j and a.start_seq else 0);next_ping=now+.25
                        if current_op and not op_notified:
                            if current_op.complete and (current_op.state=='error' or self.channel_ready):
                                if current_op.state=='done' and self.network_startup and self.build_evidence:
                                    current_op.board_log=dict(state='pending_idle',error=None,evidence=None)
                                    pending_model_records.append(current_op)
                                model_update();op_notified=True;self.model_records.append(self.model_snapshot(current_op));idle_end=now+300 if idle else None
                                if current_op.fatal:self.healthy=False
                            elif now>=next_update:model_update();next_update=now+.25
                        if idle and self.channel_ready and self.healthy and not transfer:
                            for operation in pending_model_records[:]:
                                pull_model_evidence(operation);pending_model_records.remove(operation)
                        now=time.monotonic()
                        if not self.healthy:break
                        if need_link and not self.channel_ready and now-last_rx>30:
                            raise TimeoutError('模型会话INFO/PONG/STATUS握手超时；未假定可用')
                        if j:
                            a=j.audit
                            if j.recovering:
                                if now-task_start>30:raise TimeoutError('恢复INFO/PONG/STATUS超时；未发START或RESUME')
                                if not a.info and now>=info_next and info_tries<4:
                                    send(7,task=0);info_tries+=1;info_next=now+.3
                                if a.info and a.have_pong and recovery_status:
                                    j.recovering=False;j.error=None;j.recoveries[-1].update(state='reconciled',ended=t.legacy.now(),info=a.info)
                                    j.state='paused' if a.state==2 else 'running';self.channel_ready=True
                            elif a.start_seq is None and hello and hello.complete:
                                if hello.error:raise ValueError(hello.error)
                                if not m.registered(j.candidate,hello.entries):
                                    j.preflight_rejected=True;j.fail('任务模型尚未在板卡精确登记；未发START，先上传配套包')
                                    hello=None;notified=True;idle_end=now+300;update(True);j.callbacks[1]('error:'+j.error)
                                elif self.channel_ready and a.ready and a.have_pong:
                                    j.command=dict(kind=1,state='queued',sequences=[],attempts=0);hello=None
                            if j.state=='running' and a.start_seq is None and now-task_start>30:raise TimeoutError('启动模型/身份预检超时；未发任务')
                            c=j.command
                            if c:
                                if c['state']=='queued':c.update(state='waiting',deadline=now+IO_TIMEOUT,next=now)
                                if c['state']=='waiting' and now>=c['next'] and c['attempts']<4:
                                    seq=send(c['kind'],a.start_body() if c['kind']==1 else b'')
                                    c['sequences'].append(seq);c['attempts']+=1;c['next']=now+.3
                                    if c['kind']==1:self.known_tasks.add(a.task);self.latest_task=a.task
                                if now>=c['deadline']:raise TimeoutError('任务控制回执超时；不假装任务已改变')
                            p=j.probe_result
                            if p and p['state']=='queued':
                                if (self.sequence+1)&65535 in j.used_probe_sequences:
                                    # One real heartbeat advances the global v1
                                    # sequence; do not skip seq numbers or reuse
                                    # a PROBE ID after a long task/pause wrap.
                                    send(5,struct.pack('<I',a.session))
                                else:
                                    identity=p['identity'];scene=m.SCENES.index(identity['scene']);crc=int(identity['wcrc'],16)
                                    stamp=(time.perf_counter_ns()//1000)&0xffffffff
                                    p.update(state='running',ping_seq=send(5,struct.pack('<I',a.session),stamp=stamp),stamp=stamp,
                                        req_seq=send(9,struct.pack('<BBHHHI',scene,int(p.get('attention_requested',False)),p['row'],p['col'],0,crc),stamp=stamp),
                                        deadline=now+IO_TIMEOUT,next=now+1,attempts=1,have_pong=False,have_status=False)
                                    j.used_probe_sequences.add(p['req_seq'])
                            elif p and p['state']=='running':
                                if now>=p['next'] and p['attempts']<3:
                                    if not p['have_pong']:send(5,struct.pack('<I',a.session),seq=p['ping_seq'],stamp=p['stamp'])
                                    send(9,struct.pack('<BBHHHI',m.SCENES.index(p['identity']['scene']),int(p.get('attention_requested',False)),p['row'],p['col'],0,int(p['identity']['wcrc'],16)),seq=p['req_seq'],stamp=p['stamp'])
                                    p.update(attempts=p['attempts']+1,next=now+1)
                                if now>=p['deadline']:raise TimeoutError('探查/恢复原模型超时，未提交探查结果')
                            if not j.recovering and a.final and not a.complete() and now>=repair_at:
                                rows=repair.due(now,a,immediate=True)
                                if rows:
                                    if repair_retries>=5:raise TimeoutError(f'补传后仍缺 {a.final["done"]-a.count} 像素')
                                    send(6,t.row_request(rows));repair_retries+=1;repair_at=now+.6
                            elif not j.recovering and not a.final and a.start_seq is not None:
                                rows=repair.due(now,a)
                                if rows:send(6,t.row_request(rows))
                            if c and c['state']=='applying' and a.last_status and a.state in ({2:0,3:2,4:1}[c['kind']],3):
                                for seq in c['sequences']:a.commands.pop(seq,None)
                                j.command=None
                            if not j.recovering and a.complete() and not j.command and not notified:
                                j.state='done' if a.final['state']==3 else 'stopped';j.ended=j.ended or t.legacy.now();notified=True
                                terminal_evidence(j)
                                idle_end=now+300;update(True);j.callbacks[1](j.state)
                            if need_link and now-last_rx>IO_TIMEOUT:raise TimeoutError('板卡长时未回执；状态未确认，不自动新START')
                            if need_link and now>=next_update:update();next_update=now+.5
                        if idle_end and now>=idle_end and now>=self.display_observer_until and not transfer and not self.keys_enabled:break
                    try:data,peer=sock.recvfrom(2048)
                    except socket.timeout:continue
                    if peer!=self.addr:continue
                    with self.lock:
                        now=time.monotonic();record(channel,'rx',data)
                        if len(data)>2 and data[2]==board_keys.EVENT:
                            self.receive_key(data)
                            continue
                        if len(data)>2 and data[2]==display.TEMP:
                            self.temperature_sample=display.temperature(data,self.boot,self.session);self.temperature_received=now
                            continue
                        if len(data)>2 and data[2]==board_power.MESSAGE:
                            estimate=board_power.decode(data,self.boot,self.session)
                            if not self.power_sample or estimate['counter']>self.power_sample['counter']:
                                self.power_sample=estimate;self.power_received=now
                            if j and board_power.accept_job(j,estimate):
                                record(trace,'rx',data);update()
                            continue
                        if len(data)>2 and data[2]==display.FRAME:
                            mirror=self.mirror_request
                            if mirror and len(data)>=24 and struct.unpack_from('<I',data,20)[0]==mirror['id']:
                                total,offset,crc,payload=display.frame_chunk(data,self.boot,self.session,mirror['id'])
                                if mirror['total'] is None:mirror.update(total=total,crc=crc)
                                if (total,crc)!=(mirror['total'],mirror['crc']):raise ValueError('Mirror frame changed during transfer')
                                if offset==mirror['offset']:
                                    mirror['data'].extend(payload);mirror['offset']+=len(payload);mirror['next']=0.
                                    if mirror['offset']==total:
                                        if zlib.crc32(mirror['data'])!=crc:raise ValueError('Mirror CRC')
                                        self.mirror_png=display.png_from_rle(mirror['data']);self.mirror_at=now;self.mirror_request=None
                            continue
                        if len(data)==20 and data[2]==0x83 and data[12] in (display.PARCEL,display.MIRROR):
                            typ,code,seq,value=struct.unpack_from('<BBHI',data,12)
                            dp=self.display_pending
                            if typ==display.PARCEL and dp and seq==dp['seq'] and value==dp['serial']:
                                self.display_status.update(state='synced' if code==0 else 'error',error=None if code==0 else f'板端拒绝同步：{code}');self.display_pending=None
                            elif typ==display.MIRROR and code:self.mirror_request=None
                            continue
                        if len(data)>2 and data[2]==board_log.REPLY:
                            late=board_log.decode(data)
                            if late['boot']!=self.boot:raise ValueError('Late diagnostic reply from another boot')
                            continue # no task/heartbeat state from a diagnostic page
                        if len(data)==20 and data[2]==0x83 and data[12]==board_log.QUERY:continue
                        if current_op and not op_notified:record(model_trace,'rx',data)
                        d=t.decode(data);last_rx=now
                        if d['kind'] in (0x82,0x86):
                            if d['kind']==0x86 and d.get('engine_abi')!=4:raise ValueError('Current deployment requires engine ABI4; old INFO is read-only history')
                            if d['kind']==0x86 and self.release_id is not None and d.get('release_tag')!=self.release_id[:32]:
                                raise ValueError('INFO App/source/XSA release mismatch; no takeover or fallback')
                            if d['boot_id']!=self.boot:raise ValueError('板卡启动身份改变，禁止继续旧会话')
                            if d['kind']==0x82 and d['session']!=self.session:raise ValueError('STATUS session mismatch')
                            if d['task'] and (d.get('session')!=self.session or d['task'] not in self.known_tasks):raise ValueError('未知活动任务；不接管')
                        consumed=False
                        for q in (current_op,hello):
                            if q and not q.complete and q.received(d):consumed=True;break
                        if d['kind']==0x86 and (consumed or j and j.recovering):
                            self.channel_info=copy.deepcopy(d);self.registry=copy.deepcopy(d['entries'])
                        if d['kind']==0x84 and pings.get(d['ping_seq'])==d['t1']:
                            have_pong=True;self.terminal_resume_pending=False
                        if d['kind']==0x82:channel_status=d
                        if self.channel_info and have_pong and channel_status:self.channel_ready=True
                        if consumed and d['kind'] in (0x83,0x86):continue
                        if j:
                            # Model ACKs/INFO belong to their own journal. The
                            # immutable task journal does not gain fake actions.
                            if d['kind']==0x83 and d['acked_type']>=0x10:continue
                            if d['kind']==0x86 and not j.recovering:continue
                            record(trace,'rx',data);j.rx_pkts+=1;j.rx_bytes+=len(data);d=a.received(data)
                            if not d:continue
                            if d.get('task_preflight_error'):
                                j.command=None;j.preflight_rejected=True;j.fail('SD输入预检失败；未开始DMA任务，可修复输入后显式重试')
                                notified=True;idle_end=now+300;update(True);j.callbacks[1]('error:'+j.error);continue
                            if d['kind']==0x82:
                                j.last_status=a.last_status;repair.observe(now,a)
                                if j.recovering and a.info:recovery_status=True
                                if j.state in ('running','paused'):j.state='paused' if a.state==2 else 'running'
                            if d['new_cells']:
                                import numpy as np
                                cells=d['new_cells'];j.callbacks[0](np.array([[c['y'],c['x']] for c in cells]),np.array([c['class_id']+1 for c in cells],dtype=np.uint8),np.array([c['confidence'] for c in cells]))
                                if j.callbacks[2]:j.callbacks[2]({**j.snapshot(False),'chunk':cells})
                            c=j.command
                            if c and d['kind']==0x83 and d['acked_type']==c['kind'] and d['acked_seq'] in c['sequences']:
                                if c['kind']==1:
                                    for seq in c['sequences']:a.commands.pop(seq,None)
                                    j.command=None
                                elif c['state']=='waiting':c.update(state='applying',deadline=now+IO_TIMEOUT)
                            if j.probe_result:
                                # Shared strict replay logic validates request
                                # identity, logits and optional same-model CLASS.
                                from board_history import apply_probe_reply
                                apply_probe_reply(j.probe_result,d,a)
                                p=j.probe_result
                                if p['state']=='done' and not p.get('saved'):
                                    p['saved']=True;j.probes.append(copy.deepcopy(p))
                                    if j.state in ('done','stopped'):terminal_evidence(j)
                                    update(j.state in ('done','stopped'))
        except Exception as exc:
            self.healthy=False
            if current_op and not current_op.complete:current_op.fail(str(exc),fatal=True);model_update()
            if j:
                if j.probe_result:
                    import board_attention
                    board_attention.clear(j.probe_result);j.probe_result.update(state='error',error=str(exc))
                j.integrity_error=j.integrity_error or isinstance(exc,ValueError)
                if j.recovering and j.recoveries:j.recoveries[-1].update(state='error',error=str(exc))
                if j.state not in ('done','stopped'):j.fail(str(exc));j.callbacks[1]('error:'+str(exc))
                else:j.error=str(exc)
        finally:
            with self.lock:
                self.channel_ready=False
                if self.evidence_request:
                    self.evidence_request.board_log_state='error';self.evidence_request.board_log_error='原连接已关闭，证据回读未完成'
                    if self.evidence_request.board_log_event:self.evidence_request.board_log_event.set()
                    self.evidence_request=None
                if current_op and not current_op.complete:current_op.fail('本地模型观察结束；板卡实际状态未确认');model_update()
                for operation in pending_model_records:
                    operation.board_log=dict(state='error',error='Original owner closed before deferred board-log read',evidence=None)
                    model_update(operation)
                if j:
                    j.channel_open=False;j.recovering=False
                    if j.probe_result and j.probe_result['state'] in ('queued','running'):
                        import board_attention
                        board_attention.clear(j.probe_result);j.probe_result.update(state='error',error='Channel closed before complete attention/LOGITS/identity')
                    if j.state in ('running','paused'):j.fail('本地采集结束，板卡任务状态未确认');j.callbacks[1]('error:'+str(j.error))
                    update(True)
                t.save_json(self.channel_out/'summary.json',dict(boot_id=self.boot,session=self.session,next_sequence=self.sequence,
                    known_tasks=sorted(self.known_tasks),registry=self.registry,healthy=self.healthy,closed=True,latest_task=self.latest_task))
            for f in (trace,model_trace,channel):
                if f:f.close()
