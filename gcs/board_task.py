"""Lifecycle v1 candidate, separate from immutable one-shot evidence readers.

No socket on import/selection/restore. Only an explicit START opens the first
peer; subsequent tasks use that same live session. No driver or wire extension.
"""
import math
import os
import copy
import struct
import json
import csv
import io
import secrets
import socket
import threading
import time
from pathlib import Path
from datetime import datetime
import board_roi as legacy
import board_probe
import board_models as models

wire = legacy.wire
TIMING_SCOPE = ('BOARD_TASK_STEP_PS_PREP_AND_ENGINE_WAIT_INCLUDING_WAIT_SERVICE; '
                'EXCLUDES_LOAD_W_PROBE_DP_FOREGROUND_TX_PAUSE_IDLE; NOT_PURE_PL')


def csv_text(snapshot):
    if not snapshot.get('model_lifecycle'):return legacy.csv_text(snapshot)
    m=models.task_identity(snapshot);out=io.StringIO(newline='')
    fields=['boot_id','session','task','scene','model','wcrc','image_height','image_width','classes',
            'x','y','class_word','class_id','confidence_q16','confidence']
    writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
    identity={k:snapshot[k] for k in ('boot_id','session','task','scene','model','wcrc')}
    identity.update(image_height=m['shape'][0],image_width=m['shape'][1],classes=m['classes'])
    for cell in snapshot['cells']:writer.writerow({**identity,**cell})
    return out.getvalue()


def save_json(path, value):
    """Atomic snapshots; the append-only packet journal remains authoritative."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class RepairSchedule:
    """v1 section 2.6: repair only frontiers observed >=0.5 s ago."""
    def __init__(self):
        self.frontiers = []
        self.next_check = 0.
        self.requested = {}

    def observe(self, now, audit):
        frontier = audit.y + audit.reported_done // audit.width
        if not self.frontiers or frontier != self.frontiers[-1][1]:
            self.frontiers.append((now, frontier))

    def due(self, now, audit, immediate=False):
        if not immediate and now < self.next_check:
            return []
        self.next_check = now+1.
        if immediate:
            frontier = audit.y+audit.reported_done//audit.width
        else:
            old = [front for at,front in self.frontiers if now-at >= .5]
            frontier = max(old, default=audit.y)
            self.frontiers = [(at,front) for at,front in self.frontiers if front>=frontier]
        rows = [y for y in audit.missing_rows() if y < frontier and
                (immediate or now-self.requested.get(y, -math.inf) >= .5)]
        for y in rows:self.requested[y] = now
        return rows


def row_request(rows):
    if not rows or any(type(row) is not int or not 0<=row<1217 for row in rows):raise ValueError('ROWREQ row range')
    ranges = []
    for row in sorted(set(rows)):
        if ranges and row == ranges[-1][0]+ranges[-1][1]:ranges[-1][1] += 1
        else:ranges.append([row, 1])
    if len(ranges)>349:
        # HanChuan can have 609 alternating missing rows. Sending several
        # ROWREQs immediately would replace the board's single repair queue.
        # Bridge only the smallest produced-row gaps instead; duplicate ROWs
        # are checked word-for-word, and every missing row stays represented.
        gaps=sorted(range(len(ranges)-1),key=lambda i:(ranges[i+1][0]-sum(ranges[i]),i))
        bridge=set(gaps[:len(ranges)-349]);merged=[]
        for i,(row,count) in enumerate(ranges):
            if i and i-1 in bridge:merged[-1][1]=row+count-merged[-1][0]
            else:merged.append([row,count])
        ranges=merged
    return struct.pack('<HH', len(ranges), 0)+b''.join(struct.pack('<HH', *r) for r in ranges)


def rect_for(cmd):
    spec=models.scene_spec(cmd.get('scene'));height,width=spec['shape']
    r = [0, 0, height, width] if cmd.get('kind') == 'scan' else cmd.get('rect')
    if cmd.get('kind') not in ('scan', 'region') or not isinstance(r, (list, tuple)) or len(r) != 4:
        raise ValueError('请选择整景或矩形区域')
    if any(type(v) is not int for v in r):raise ValueError('区域坐标必须为整数')
    y, x, h, w = r
    if not (0 <= x < width and 0 <= y < height and 0 < w <= width-x and 0 < h <= height-y):
        raise ValueError('区域超出图像范围')
    return list(r)


def decode(data):
    if len(data)>=12 and data[2]==0x87:
        import board_attention
        return board_attention.decode(data)
    if len(data)>=12 and data[2]==0x86:
        magic, kind, ver, task, seq, stamp = wire.HEADER.unpack_from(data)
        if magic!=0x4548 or ver!=1 or len(data)<44:raise ValueError('INFO header')
        boot, protocol, engine, bits, count = struct.unpack_from('<IBBBB', data, 12)
        session, current, mode, scene, y, x, h, width, crc, front, state, pad = struct.unpack_from('<IHBB4HIHBB', data, 20)
        if protocol!=1 or engine not in (3,4) or bits!=16 or count>48 or len(data)!=44+28*count+(16 if engine==4 else 0) or pad not in (0,1) or (pad and engine!=4) or current!=task:
            raise ValueError('INFO version/shape')
        if current:
            spec=models.scene_spec(scene)
            rect_for(dict(kind='region',scene=spec['scene'],rect=[y,x,h,width]))
            if mode not in (0,1) or not crc or not y<=front<=y+h or state not in (0,1,2,3):
                raise ValueError('INFO task/ROI')
            if mode==0 and [y,x,h,width]!=[0,0,*spec['shape']]:raise ValueError('INFO full scene')
        elif any((mode,scene,y,x,h,width,crc,front,state)):raise ValueError('INFO idle descriptor')
        entries=[];tags=set();crcs=set()
        for off in range(44,44+28*count,28):
            sc,k,res,size,wcrc,tag=struct.unpack_from('<BBHII16s',data,off)
            if res or sc>2 or k>1 or size!=(models.ENGINE_BYTES if k else sum(n for _,n in models.part_files(sc))) or not wcrc:
                raise ValueError('INFO registry entry')
            tag=models.decode_tag(tag)
            if (sc,k,tag) in tags or (sc,k,wcrc) in crcs:raise ValueError('Ambiguous INFO model registry')
            tags.add((sc,k,tag));crcs.add((sc,k,wcrc))
            entries.append(dict(scene=sc,kind=k,bytes=size,wcrc=f'{wcrc:08x}',tag=tag))
        return dict(kind=kind,task=task,seq=seq,t_us=stamp,boot_id=boot,session=session,mode=mode,scene=scene,
                    rect=[y,x,h,width],wcrc=crc,front_row=front,state=state,entries=entries,engine_abi=engine,
                    release_tag=data[-16:].hex() if engine==4 else None,terminal_owned=bool(pad))
    if len(data)>=12 and data[2]==0x82:
        if len(data)!=92:raise ValueError('STATUS length')
        ms=struct.unpack_from('<f',data,20)[0]
        if not math.isnan(ms) and (not math.isfinite(ms) or ms<=0):raise ValueError('invalid compute timing')
        # Reuse strict header/reserved/identity decoding without weakening the
        # historical one-shot oracle. Normalize only a copy of this known field.
        copy=bytearray(data);struct.pack_into('<f',copy,20,float('nan'))
        d=wire.decode(copy)
        if not math.isnan(ms) and not d['done']:raise ValueError('timing without committed pixels')
        d['ms_per_px']=None if math.isnan(ms) else ms
        return d
    if len(data)>=12 and data[2]==0x85:
        magic,kind,ver,task,seq,stamp=wire.HEADER.unpack_from(data)
        if magic!=0x4548 or ver!=1 or len(data)<28:raise ValueError('LOGITS header/version')
        req,scene,ncls,row,col,crc,word=struct.unpack_from('<HBBHHII',data,12)
        spec=models.scene_spec(scene)
        if ncls!=spec['classes'] or len(data)!=28+ncls*4 or row>=spec['shape'][0] or col>=spec['shape'][1] or not crc or word&0xff00 or word&255>=ncls:
            raise ValueError('LOGITS scene/shape/CLASS')
        logits=list(struct.unpack_from(f'<{ncls}i',data,28))
        if logits[word&255]!=max(logits):raise ValueError('CLASS/logits argmax mismatch')
        return dict(kind=kind,task=task,seq=seq,t_us=stamp,req_seq=req,scene=scene,ncls=ncls,row=row,col=col,wcrc=crc,
                    class_word=f'{word:08X}',class_id=word&255,confidence_q16=word>>16,logits_q16=logits)
    if len(data) < 12 or data[2] != 0x81:return board_probe.decode(data)
    magic, kind, ver, task, seq, stamp = wire.HEADER.unpack_from(data)
    if magic != 0x4548 or ver != 1 or len(data) < 20:raise ValueError('ROW header')
    row, col, n, flags = struct.unpack_from('<4H', data, 12)
    if flags & ~1 or row >= 1217 or not 0 < n <= 348 or col+n > 475 or len(data) != 20+4*n:
        raise ValueError('ROW shape/flags')
    words = struct.unpack_from(f'<{n}I', data, 20)
    if any(w & 0xff00 or (w & 255) >=22 for w in words):raise ValueError('CLASS invalid')
    return dict(kind=kind, task=task, seq=seq, t_us=stamp, row=row, col=col, words=words, flags=flags)


class Audit(wire.Audit):
    def __init__(self, boot, session, task, rect, fresh=True,identity=None):
        super().__init__(boot, session, task)
        self.model_lifecycle=identity is not None
        self.identity=models.task_identity(identity or dict(scene='longkou',model='v2',wcrc=f'{wire.WCRC:08x}',shape=[550,400],classes=9,kind=1))
        self.scene=self.identity['scene'];self.scene_id=models.SCENES.index(self.scene);self.crc=int(self.identity['wcrc'],16)
        self.scene_height,self.scene_width=self.identity['shape'];self.classes=self.identity['classes']
        rect_for(dict(kind='region',scene=self.scene,rect=rect))
        self.y, self.x, self.height, self.width = rect
        self.total = self.width*self.height
        self.count = self.reported_done = 0
        self.max_received = -1
        self.counts = [0]*self.classes
        self.state = 1
        self.fresh = fresh
        self.ready = self.have_pong = not fresh
        self.commands = {}
        self.last_status = None
        self.info = None
        self.info_sequences = set()
        self.accepted_via_info = False
        self.preflight_error=None
        self.recovery_clock=False

    def begin_recovery(self):
        if self.start_seq is None:raise ValueError('No recorded START to recover; no implicit task')
        self.info = None
        self.info_sequences.clear()
        self.commands.clear()
        self.pings.clear()
        self.have_pong = False
        self.recovery_clock=True

    def start_body(self):
        return struct.pack('<BBBBHHHHII', 0 if self.total == self.scene_height*self.scene_width else 1, self.scene_id, 0, 0,
                           self.y, self.x, self.height, self.width, self.crc, self.session)

    def sent(self, data):
        if len(data)<12:raise ValueError('short TX header')
        magic, kind, ver, task, seq, stamp = wire.HEADER.unpack_from(data)
        if magic != 0x4548 or ver != 1:raise ValueError('TX header')
        if kind == 7:
            if len(data)!=12:raise ValueError('INFO length')
            self.info_sequences.add(seq)
            return
        if kind == 5:
            if data[12:] != struct.pack('<I', self.session):raise ValueError('PING session')
            self.pings[seq] = stamp
            if len(self.pings) > 128:self.pings.pop(next(iter(self.pings)))
            return
        if task != self.task:raise ValueError('TX task')
        if kind == 1:
            if not self.ready or not self.have_pong or data[12:] != self.start_body():raise ValueError('START gate/shape')
            if self.start_seq is None:self.start_seq = seq
        elif kind in (2,3,4):
            if len(data)!=12:raise ValueError('TX control size')
        elif kind==6:
            if len(data)<20:raise ValueError('ROWREQ size')
            n,pad=struct.unpack_from('<HH',data,12)
            if pad or not 0<n<=349 or len(data)!=16+4*n:raise ValueError('ROWREQ shape')
            for off in range(16,len(data),4):
                row,count=struct.unpack_from('<HH',data,off)
                if not count or row>=self.scene_height or count>self.scene_height-row:raise ValueError('ROWREQ range')
        elif kind==9:
            if len(data)!=24:raise ValueError('PROBE size')
            sc,pad,ry,rx,res,crc=struct.unpack_from('<BBHHHI',data,12)
            spec=models.scene_spec(sc)
            if pad&~1 or res or ry>=spec['shape'][0] or rx>=spec['shape'][1] or not crc:raise ValueError('PROBE identity')
        else:raise ValueError('TX command')
        self.commands[seq] = kind
        if len(self.commands) > 256:self.commands.pop(next(iter(self.commands)))

    def received(self, data):
        d = decode(data);d['new_cells'] = []
        if d['kind']==0x86:
            if not self.info_sequences:return None
            if (d['boot_id'],d['session'],d['task'],d['scene'],d['wcrc'],d['rect']) != (self.boot,self.session,self.task,self.scene_id,self.crc,[self.y,self.x,self.height,self.width]):
                raise ValueError('INFO boot/session/task/model/ROI mismatch; no rebind')
            if d['front_row'] < self.y+self.reported_done//self.width:raise ValueError('INFO frontier regressed')
            self.info=d.copy();self.accepted_via_info=True
            return d
        if d['kind']==0x83 and d['acked_type']==7 and d['acked_seq'] in self.info_sequences:
            raise ValueError(f"INFO rejected code={d['code']}; fault not cleared")
        if d['kind'] == 0x84:
            if self.pings.get(d['ping_seq']) == d['t1']:self.have_pong = True
            return d
        if d['kind'] == 0x82:
            if (d['boot_id'], d['session']) != (self.boot, self.session):
                raise ValueError('boot/session/model mismatch')
            if self.start_seq is None:
                if self.fresh and (d['task'], d['state'], d['done'], d['total']) != (0, 0, 0, 0):
                    raise ValueError('not fresh idle')
                self.ready = True
                return d
        if d['task'] != self.task:return None  # delayed older task cannot contaminate this one
        if d['kind']==0x82 and d['wcrc']!=self.crc:raise ValueError('boot/session/model mismatch')
        if d['kind'] == 0x83:
            # App runtime failures use the original START sequence even after
            # its successful ACK. Do not discard a fatal DMA/compute receipt
            # together with late control retries from completed commands.
            if d['code']==6 and d['acked_type']==1 and d['acked_seq']==self.start_seq:
                # Private model App returns TT_M3A_SD_IO only before LOAD_W/
                # task DMA; no result can be claimed. Other code6 stays fatal.
                if self.model_lifecycle and d['value']==((-203)&0xffffffff):
                    self.preflight_error=-203;d['task_preflight_error']=-203;return d
                raise ValueError(f"board runtime failure value={d['value']}")
            if self.commands.get(d['acked_seq']) != d['acked_type']:return None
            if d['code']:raise ValueError(f"board ACK code={d['code']} value={d['value']}")
            if d['acked_type'] == 1:self.ack = True
        elif d['kind'] == 0x82:
            if self.recovery_clock and (not self.info or not self.have_pong):return None
            if d['state'] not in (0, 1, 2, 3) or d['total'] != self.total or not 0 <= d['done'] <= self.total or d['front_row'] != self.y+d['done']//self.width:
                raise ValueError('task progress/ROI mismatch')
            if d['state'] == 3 and d['done'] != self.total:raise ValueError('incomplete DONE')
            if d['state'] in (0, 2) and d['done'] % self.width:raise ValueError('control not at row boundary')
            if d['done'] < self.reported_done:return None
            if not self.recovery_clock and self.last_status and ((d['t_us']-self.last_status['t_us'])&0xffffffff)>=0x80000000:return None
            if self.final and (d['state'],d['done'])!=(self.final['state'],self.final['done']):
                raise ValueError('terminal task state changed without a new task')
            if d['state'] in (0,3) and self.max_received>=d['done']:raise ValueError('received words beyond terminal frontier')
            self.reported_done, self.state, self.last_status = d['done'], d['state'], d.copy()
            self.recovery_clock=False
            if d['state'] in (0, 3):self.final = d.copy()
        elif d['kind'] == 0x81:
            if self.start_seq is None:raise ValueError('ROW before START')
            y, x, words = d['row'], d['col'], d['words']
            if not self.y <= y < self.y+self.height or not self.x <= x < x+len(words) <= self.x+self.width:
                raise ValueError('ROW outside task ROI')
            last=(y-self.y)*self.width+x-self.x+len(words)-1
            if self.final and last>=self.final['done']:raise ValueError('ROW beyond terminal frontier')
            if any((w&255)>=self.classes for w in words):raise ValueError('CLASS differs from task classes')
            row = self.rows.setdefault(y, [None]*self.scene_width)
            if any(row[x+i] is not None and row[x+i] != w for i,w in enumerate(words)):
                raise ValueError('conflicting duplicate ROW')
            for i,w in enumerate(words):
                if row[x+i] is None:
                    row[x+i] = w;self.count += 1;self.counts[w & 255] += 1
                    d['new_cells'].append(dict(x=x+i,y=y,class_word=f'{w:08X}',class_id=w&255,confidence_q16=w>>16,confidence=(w>>16)/65536))
                else:self.duplicates += 1
            self.max_received=max(self.max_received,last)
        return d

    def missing_rows(self):
        return [y for y in range(self.y,self.y+self.reported_done//self.width)
                if any(w is None for w in self.rows.get(y,[None]*self.scene_width)[self.x:self.x+self.width])]

    def complete(self):return (self.ack or self.accepted_via_info) and self.final is not None and self.count == self.final['done']


class Job(legacy.Job):
    def __init__(self, boot, session, task, rect, fresh,identity=None):
        super().__init__(boot, session, task, True)
        self.audit = Audit(boot, session, task, rect, fresh,identity)
        self.command = None
        self.probe_result = None
        self.channel_open = True
        self.lock = threading.RLock()
        self.integrity_error = False
        self.recovering = False
        self.recoveries = []
        self.probes = []
        self.used_probe_sequences=set()
        self.host_run = None
        self.power_estimate = None
        self.board_log_evidence=None;self.board_log_state='unavailable';self.board_log_error=None;self.board_log_event=None

    def snapshot(self, include_cells=True):
        with self.lock:return self._snapshot(include_cells)

    def _snapshot(self, include_cells):
        s = super().snapshot(include_cells);a = self.audit
        s['power_estimate']=copy.deepcopy(self.power_estimate)
        s.update(a.identity,model_lifecycle=a.model_lifecycle)
        s['board_log']=dict(state=self.board_log_state,evidence=self.board_log_evidence,error=self.board_log_error,transport='ethernet',
                           required=bool((self.host_run or {}).get('network_startup')))
        if a.model_lifecycle:s['model_candidate']=copy.deepcopy(getattr(self,'candidate',None))
        s['preflight_rejected']=bool(getattr(self,'preflight_rejected',False) or a.preflight_error)
        ms=(a.last_status or {}).get('ms_per_px')
        s.update(roi=dict(x=a.x,y=a.y,width=a.width,height=a.height),total=a.total,
                 full_scene=a.total==a.scene_height*a.scene_width,task_lifecycle=True,command=copy.deepcopy(self.command),
                 interaction=dict(state='open' if self.channel_open else 'closed',reason=None if self.channel_open else '原任务连接已结束',probe=copy.deepcopy(self.probe_result)),
                 scope='LIFECYCLE_V1_CANDIDATE_NOT_BOARD_ACCEPTANCE')
        s.update(accepted_via_info=a.accepted_via_info,info=copy.deepcopy(a.info),
                 recoveries=copy.deepcopy(self.recoveries),probes=copy.deepcopy(self.probes),
                 integrity_error=self.integrity_error,recovering=self.recovering)
        if ms is not None:
            s['performance']=dict(ms_per_pixel=ms,pixels_per_second=1000/ms,
                computed_pixels=a.last_status['done'],source='BOARD_STATUS',scope=TIMING_SCOPE,
                cumulative_seconds_from_wire=ms*a.last_status['done']/1000)
        return s


class BoardSource(legacy.BoardSource):
    def __init__(self, root=None):
        super().__init__(root)
        self.lock = threading.RLock()
        self.session = None
        self.pending = None
        self.sequence = 0
        self.next_task = 1
        self.healthy = True

    def authorize(self, text, confirmed):
        if str(text).lower() == 'bb6bd8e3':raise ValueError('该历史启动已结束，不能重用')
        super().authorize(text, confirmed)
        with self.lock:
            self.job=self.pending=None;self.session=None;self.next_task=1;self.sequence=0;self.healthy=True
        return self.describe()

    def validate(self, cmd):
        rect_for(cmd)
        if self.boot is None or not self.healthy:raise ValueError('请先连接板卡并等待新启动就绪')
        if self.job and self.job.state not in ('done','stopped'):raise ValueError('请先停止或等待当前任务完成')
        if self.job and (not self.worker or not self.worker.is_alive()):raise ValueError('原连接已关闭；需显式恢复或新启动')
        if self.pending or (self.job and self.job.command):raise ValueError('上一条命令尚未确认')
        if self.job and self.job.probe_result and self.job.probe_result['state'] in ('queued','running'):raise ValueError('单点探查尚未结束')
        if not self.job and (self.root/'boots'/f'{self.boot:08x}.json').exists():raise ValueError('旧启动已使用，不能自动重发任务')
        if self.next_task > 65535:raise ValueError('本会话任务号已用尽，请重新启动')

    def describe(self):
        s = super().describe()
        s.update(label='板卡 · LongKou/v2',task_lifecycle=True,
                 authorized=bool(self.boot and self.healthy and (not s['used'] or (s['active'] and self.job and self.job.state in ('done','stopped')))),
                 capabilities=dict(roi=True,controls=True,probe=True,rowreq=True,models=False))
        return s

    def start(self, run, on_chunk, on_done, pace_rows=0, on_update=None):
        with self.lock:
            self.validate(dict(kind=run.kind,scene=run.scene,version=run.version,rect=run.rect))
            fresh = self.session is None
            if fresh:
                (self.root/'boots').mkdir(parents=True,exist_ok=True)
                with (self.root/'boots'/f'{self.boot:08x}.json').open('x',encoding='utf-8') as f:
                    json.dump(dict(boot_id=f'{self.boot:08x}',claimed=legacy.now(),run=run.id,lifecycle=True),f)
                self.session = secrets.randbits(32) or 1
            j = Job(self.boot,self.session,self.next_task,rect_for(dict(kind=run.kind,scene=run.scene,version=run.version,rect=run.rect)),fresh)
            j.lock = self.lock
            self.next_task += 1
            j.out = self.root/datetime.now().strftime('task_%Y%m%d_%H%M%S_%f');j.out.mkdir()
            j.host_run = dict(id=run.id,kind=run.kind,scene=run.scene,version=run.version,
                              rect=run.rect,t0=getattr(run,'t0',time.time()),uart_evidence=getattr(run,'uart_evidence',None))
            run.board_job = j
            run.lock=self.lock
            j.callbacks = (on_chunk,on_done,on_update)
            self.pending = j
            if fresh:
                self.cancel.clear()
                self.worker = threading.Thread(target=self._work,name='gcs-task-session',daemon=False);self.worker.start()

    def recover(self, job, confirmed, callbacks):
        """Explicit INFO -> same-session PING -> STATUS/ROWREQ; never START."""
        with self.lock:
            if confirmed is not True:raise ValueError('请明确确认恢复此任务；不会自动开始或继续计算')
            if self.worker and self.worker.is_alive():raise ValueError('已有连接，不能重复恢复')
            if job.audit.boot in legacy.OLD_BOOTS or job.audit.boot==0xbb6bd8e3:raise ValueError('旧启动禁止重用')
            if job.integrity_error:raise ValueError('原始证据完整性失败；禁止恢复掩盖故障')
            job.audit.begin_recovery()
            job.command=None;job.probe_result=None;job.callbacks=callbacks;job.lock=self.lock
            job.recovering=True;job.channel_open=True
            self.boot=job.audit.boot;self.session=job.audit.session
            self.sequence=getattr(job,'next_sequence',self.sequence)
            self.next_task=job.audit.task+1
            self.healthy=True;self.pending=job;self.cancel.clear()
            self.worker=threading.Thread(target=self._work,name='gcs-task-recovery',daemon=False)
            self.worker.start()
        return job.snapshot(False)

    def _request(self, kind):
        with self.lock:
            j = self.job
            if not self.healthy or not j or j.state not in ('running','paused') or j.command or self.pending:
                raise ValueError('当前任务不可控制或有命令待确认')
            if j.probe_result and j.probe_result['state'] in ('queued','running'):raise ValueError('单点探查尚未结束')
            j.command = dict(kind=kind,state='queued',sequences=[],attempts=0)
            return j.command.copy()

    def pause(self):return self._request(3)
    def resume(self):return self._request(4)
    def stop(self):return self._request(2)

    def probe(self, job, row, col):
        with self.lock:
            if job is not self.job or not self.healthy or not self.worker or not self.worker.is_alive() or job.command:
                raise ValueError('当前连接不可探查')
            if type(row) is not int or type(col) is not int or not 0 <= row < 550 or not 0 <= col < 400:raise ValueError('探查坐标越界')
            if job.probe_result and job.probe_result['state'] in ('queued','running'):raise ValueError('已有探查请求')
            job.probe_result = dict(state='queued',row=row,col=col,error=None)
            return job.probe_result.copy()

    def close(self):
        if self.job and self.job.state not in ('done','stopped','error'):raise ValueError('请先停止当前任务')
        self.shutdown()

    def _work(self):
        # All network I/O, command sequencing and received words have one owner.
        j = None;trace = None;end = time.monotonic()+2700
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.bind(('',0));sock.settimeout(.03)
                def send(kind,body=b'',task=None,seq=None,stamp=None):
                    if seq is None:seq=self.sequence;self.sequence=(seq+1)&65535
                    if stamp is None:stamp=(time.perf_counter_ns()//1000)&0xffffffff
                    data=wire.packet(kind,j.audit.task if task is None else task,seq,stamp,body)
                    j.audit.sent(data);record('tx',data)
                    if sock.sendto(data,self.addr)!=len(data):raise OSError('short UDP send')
                    j.tx_pkts+=1;j.tx_bytes+=len(data)
                    j.next_sequence=self.sequence
                    return seq
                def record(direction,data):
                    trace.write(json.dumps(dict(direction=direction,peer=self.addr,monotonic_ns=time.perf_counter_ns(),hex=data.hex()))+'\n');trace.flush()
                def update(final=False):
                    snap=j.snapshot(include_cells=final or j.state in ('done','stopped','error'))
                    save_json(j.out/'summary.json',snap)
                    if final:(j.out/'results.csv').write_text(legacy.csv_text(snap),encoding='utf-8-sig')
                    if j.callbacks[2]:j.callbacks[2](j.snapshot(False))
                while not self.cancel.is_set() and time.monotonic()<end:
                    with self.lock:
                        if self.pending:
                            if j:j.channel_open=False;update(True)
                            if trace:trace.close()
                            j=self.job=self.pending;self.pending=None
                            trace=(j.out/'packets.jsonl').open('a' if j.recovering else 'x',encoding='utf-8')
                            if j.recovering:
                                trace.write(json.dumps(dict(direction='event',event='recovery_begin',at=legacy.now()))+'\n');trace.flush()
                                j.recoveries.append(dict(started=legacy.now(),previous_error=j.error,state='querying'))
                            else:
                                save_json(j.out/'session.json',dict(boot_id=j.audit.boot,session=j.audit.session,task=j.audit.task,rect=[j.audit.y,j.audit.x,j.audit.height,j.audit.width],host_run=j.host_run,target=self.addr,scope='TASK_LIFECYCLE',source_sha256=wire.sha(Path(__file__))))
                            last_rx=next_ping=next_update=0.;start_at=time.monotonic();last_rx=start_at
                            retries=0;repair_at=0.;notified=False;idle_end=None
                            repair=RepairSchedule();info_tries=0;info_next=0.;recovery_status=False;repair_now=False
                        if j is None:continue
                        t=time.monotonic();a=j.audit
                        if j.probe_result and j.probe_result['state']=='queued':last_rx=t
                        active=j.recovering or j.state in ('running','paused') or j.command or (j.probe_result and j.probe_result['state'] in ('queued','running'))
                        if active and t-last_rx>30:raise TimeoutError('30秒未收到板卡回执；任务状态未确认')
                        if j.recovering:
                            if t-start_at>5:raise TimeoutError('恢复身份/连接握手超时；未发START或RESUME')
                            if not a.info and t>=info_next and info_tries<4:
                                send(7,task=0);info_tries+=1;info_next=t+.3
                            if a.info and a.have_pong and recovery_status:
                                j.recovering=False;j.error=None
                                j.recoveries[-1].update(state='reconciled',ended=legacy.now(),info=a.info)
                                j.state='paused' if a.state==2 else 'running'
                                repair_now=True
                        if active and (not j.recovering or a.info) and t>=next_ping:
                            send(5,struct.pack('<I',a.session),0 if a.start_seq is None and a.fresh else a.task);next_ping=t+.25
                        if not j.recovering and a.start_seq is None and a.ready and a.have_pong:
                            j.command=dict(kind=1,state='queued',sequences=[],attempts=0)
                        c=j.command
                        if c:
                            if c['state']=='queued':c.update(state='waiting',deadline=t+1.2,next=t)
                            if c['state']=='waiting' and t>=c['next'] and c['attempts']<4:
                                c['sequences'].append(send(c['kind'],a.start_body() if c['kind']==1 else b''));c['attempts']+=1;c['next']=t+.3
                            if t>=c['deadline']:raise TimeoutError('指令超时，板卡未确认；未自动切换任务')
                        if a.start_seq is None and t-start_at>5:raise TimeoutError('启动身份握手超时；未发送任务')
                        p=j.probe_result
                        if p and p['state']=='queued':
                            stamp=(time.perf_counter_ns()//1000)&0xffffffff
                            p.update(state='running',ping_seq=send(5,struct.pack('<I',a.session),stamp=stamp),stamp=stamp,
                                     req_seq=send(9,struct.pack('<BBHHHI',0,0,p['row'],p['col'],0,wire.WCRC),stamp=stamp),
                                     deadline=t+5,next=t+1,attempts=1,have_pong=False,have_status=False)
                        elif p and p['state']=='running' and t>=p['next'] and p['attempts']<3:
                            send(9,struct.pack('<BBHHHI',0,0,p['row'],p['col'],0,wire.WCRC),seq=p['req_seq'],stamp=p['stamp'])
                            p.update(attempts=p['attempts']+1,next=t+1)
                        if p and p['state']=='running' and t>=p['deadline']:
                            p.update(state='error',error='单点探查超时');self.healthy=False
                        if not j.recovering and a.final and not a.complete() and t>=repair_at:
                            rows=repair.due(t,a,immediate=True)
                            if rows:
                                if retries>=5:raise TimeoutError(f'补传后仍缺少 {a.final["done"]-a.count} 像素')
                                send(6,row_request(rows));retries+=1;repair_at=t+.6
                        elif not j.recovering and not a.final:
                            rows=repair.due(t,a,immediate=repair_now)
                            if rows:send(6,row_request(rows))
                        repair_now=False
                        c=j.command
                        if c and c['state']=='applying' and a.last_status and a.state in ({2:0,3:2,4:1}[c['kind']],3):
                            for seq in c['sequences']:a.commands.pop(seq,None)
                            j.command=None
                        if not j.recovering and a.complete() and not j.command and not notified:
                            j.state='done' if a.final['state']==3 else 'stopped';j.ended=j.ended or legacy.now();notified=True;idle_end=t+300
                            update(True);j.callbacks[1](j.state)
                        if idle_end and t>=idle_end:break
                        if active and t>=next_update:update();next_update=t+.5
                    try:data,peer=sock.recvfrom(2048)
                    except socket.timeout:continue
                    if peer!=self.addr:continue
                    with self.lock:
                        record('rx',data);j.rx_pkts+=1;j.rx_bytes+=len(data);last_rx=time.monotonic()
                        d=a.received(data)
                        if not d:continue
                        if d['kind']==0x82:
                            j.last_status=a.last_status
                            repair.observe(time.monotonic(),a)
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
                            elif c['state']=='waiting':c.update(state='applying',deadline=time.monotonic()+5)
                        p=j.probe_result
                        if p and p['state']=='running':
                            if d['kind']==0x84 and d['ping_seq']==p['ping_seq'] and d['t1']==p['stamp']:p['have_pong']=True
                            if d['kind']==0x82 and d['task']==a.task:p['have_status']=True
                        if p and p['state']=='done' and d['kind']==0x85 and d['req_seq']==p['req_seq']:
                            if (d['row'],d['col'],d['wcrc'])!=(p['row'],p['col'],wire.WCRC) or any(d[k]!=p[k] for k in ('class_word','logits_q16')):
                                raise ValueError('conflicting repeated LOGITS')
                        if p and p['state']=='running' and d['kind']==0x85 and d['req_seq']==p['req_seq']:
                            if (d['row'],d['col'],d['wcrc'])!=(p['row'],p['col'],wire.WCRC):raise ValueError('PROBE identity mismatch')
                            old=a.rows.get(p['row'],[None]*400)[p['col']]
                            if old is not None and int(d['class_word'],16)!=old:raise ValueError('PROBE differs from task result')
                            result={k:d[k] for k in ('class_word','class_id','confidence_q16','logits_q16')}
                            if p.get('result') and p['result']!=result:raise ValueError('conflicting LOGITS')
                            p['result']=result
                        if p and p['state']=='running' and p.get('result') and p['have_pong'] and p['have_status']:
                            q=p['result']['logits_q16'];e=[math.exp((v-max(q))/65536) for v in q]
                            p.update(p['result'],state='done',probabilities=[v/sum(e) for v in e],probability_source='CPU softmax of board logits',attention_source='not returned')
                            j.probes.append(copy.deepcopy(p))
                            update(j.state in ('done','stopped'))
        except Exception as exc:
            self.healthy=False
            if j:
                j.integrity_error=j.integrity_error or isinstance(exc,ValueError)
                if j.recovering and j.recoveries:j.recoveries[-1].update(state='error',error=str(exc))
                if j.state not in ('done','stopped'):
                    j.fail(str(exc));j.callbacks[1]('error:'+str(exc))
                else:
                    j.error=str(exc)  # preserve completed evidence, but never hide a later integrity error
                    if j.probe_result:j.probe_result.update(state='error',error=str(exc))
        finally:
            if trace:trace.close()
            if j:
                with self.lock:
                    j.channel_open=False
                    j.recovering=False
                    if j.state in ('running','paused'):j.fail('本地采集结束；板卡任务状态未确认');j.callbacks[1]('error:'+str(j.error))
                    save_json(j.out/'summary.json',j.snapshot())
                    if j.callbacks[2]:j.callbacks[2](j.snapshot(False))
