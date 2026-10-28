"""Bounded v1 model transaction; caller owns the one board socket and journal.

No network, files, training or inference here. Local bytes, INFO registration,
per-kind WCOMMIT persistence and WACT activation are distinct facts.
"""
import copy
import struct
import zlib
import hashlib
import board_models as m

MODEL_TYPES=(7,m.WBEGIN,m.WCHUNK,m.WCOMMIT,m.WACT)
# Host observation limits, not measured device latency or driver poll limits.
IO_TIMEOUT=180.0

class Transfer:
    def __init__(self,boot,session,action,candidate=None,parts=None,activate=False,task=0):
        if action not in ('query','upload','activate'):raise ValueError('Unknown model action')
        self.boot,self.session,self.action=boot,session,action
        self.task=task
        self.candidate=copy.deepcopy(candidate);self.parts=parts
        self.want_activate=activate or action=='activate'
        self.state='queued';self.error=None;self.fatal=False;self.complete=False
        self.entries=[];self.registered=False;self.persisted=[None,None];self.activated=None
        self.receipts=[];self.outstanding=None;self.kind=0;self.offset=0;self.corrections=0
        self.phase='query';self.query_count=0;self.started=None
        if action!='query':
            m.candidate_identity(candidate)
            if len(candidate['parts'])!=2 or [p['kind'] for p in candidate['parts']]!=[0,1]:raise ValueError('Model parts identity')
            if action=='upload':
                if not isinstance(parts,(list,tuple)) or len(parts)!=2:raise ValueError('Missing verified model bytes')
                m.validate_pair(candidate['scene'],*parts)
                for expected,raw in zip(candidate['parts'],parts):
                    if (len(raw),f'{zlib.crc32(raw):08x}',hashlib.sha256(raw).hexdigest())!=(expected['bytes'],expected['crc32'],expected['sha256']):
                        raise ValueError('Upload bytes changed after candidate verification')
        self.scene=m.scene_spec(candidate['scene'])['id'] if candidate else None

    def fail(self,reason,fatal=False):
        self.error=str(reason);self.fatal=fatal;self.state='error';self.complete=True
        self.activated=False if not self.outstanding or self.outstanding['kind']!=m.WACT else None

    def snapshot(self):
        return dict(action=self.action,state=self.state,error=self.error,phase=self.phase,kind=self.kind,task=self.task,
                    scene=self.candidate['scene'] if self.candidate else None,
                    tag=self.candidate['tag'] if self.candidate else None,
                    version=self.candidate.get('version',self.candidate['tag']) if self.candidate else None,
                    wcrc=self.candidate['wcrc'] if self.candidate else None,
                    candidate=copy.deepcopy(self.candidate),entries=copy.deepcopy(self.entries),
                    done=sum(len(p) for p in self.parts[:self.kind])+self.offset if self.parts else 0,
                    total=sum(len(p) for p in self.parts) if self.parts else 0,
                    registered=self.registered,persisted=all(v is True for v in self.persisted) if self.action=='upload' else None,
                    persisted_parts=self.persisted[:],activated=self.activated,receipts=copy.deepcopy(self.receipts),
                    ok=self.complete and self.state=='done',source='board',boot_id=f'{self.boot:08x}',session=f'{self.session:08x}',
                    scope='REAL_V1_RECEIPTS_REQUIRED_NOT_LOCAL_CANDIDATE_OR_BOARD_TASK_ACCEPTANCE')

    def _request(self):
        if self.phase in ('query','verify'):return 7,b''
        part=self.candidate['parts'][self.kind];crc=int(part['crc32'],16)
        if self.phase=='begin':return m.WBEGIN,m.BEGIN.pack(self.scene,self.kind,0,part['bytes'],crc,self.candidate['tag'].encode('ascii'))
        if self.phase=='chunk':
            raw=self.parts[self.kind];data=raw[self.offset:self.offset+m.CHUNK_BYTES]
            return m.WCHUNK,m.CHUNK.pack(self.scene,self.kind,0,self.offset,len(raw),crc)+data
        if self.phase=='commit':return m.WCOMMIT,struct.pack('<I',crc)
        if self.phase=='activate':return m.WACT,m.ACT.pack(self.scene,0,0,int(self.candidate['wcrc'],16))
        raise ValueError('Invalid upload phase')

    def _have_part(self,kind):
        p=self.candidate['parts'][kind]
        matches=[e for e in self.entries if e['scene']==self.scene and e['kind']==kind and e['wcrc']==p['crc32']]
        return len(matches)==1 and matches[0]['tag']==self.candidate['tag'] and matches[0]['bytes']==p['bytes']

    def tick(self,now,send,idle=True):
        """send(kind,body,seq=None) -> actual global seq; retries reuse that seq."""
        if self.complete:return
        if self.started is None:self.started=now;self.state='running'
        if self.phase=='await_idle' or (self.phase=='activate' and not idle):
            if not idle:self.state='waiting_task_end';self.started=now;return
            self.state='running'
            if self.phase=='await_idle':self.phase='commit'
        if now-self.started>900:self.fail('模型事务超出15分钟观察上限；未假定提交或激活成功');return
        q=self.outstanding
        if q:
            if now>=q['deadline']:
                self.fail('模型回执超时；提交/激活状态未确认，不自动开始任务');return
            if now>=q['next'] and q['attempts']<4:
                send(q['kind'],q['body'],seq=q['seq']);q['attempts']+=1;q['next']=now+q['interval']
            return
        kind,body=self._request();interval=1. if kind in (m.WCOMMIT,m.WACT) else .3
        seq=send(kind,body)
        self.outstanding=dict(kind=kind,body=body,seq=seq,attempts=1,next=now+interval,interval=interval,
                              deadline=now+(IO_TIMEOUT if kind in (m.WCOMMIT,m.WACT) else 1.2),offset=self.offset)

    def received(self,d):
        q=self.outstanding
        if self.complete or not q:return False
        if q['kind']==7 and d['kind']==0x86:
            if d['boot_id']!=self.boot:raise ValueError('Model query boot mismatch')
            if d['task'] and d['session']!=self.session:raise ValueError('Model query belongs to another session/task')
            self.entries=copy.deepcopy(d['entries']);self.outstanding=None
            self.receipts.append(dict(type='INFO_R',boot_id=d['boot_id'],session=d['session'],task=d['task'],entries=copy.deepcopy(self.entries)))
            if self.candidate:self.registered=m.registered(self.candidate,self.entries)
            if self.action=='query':self.state='done';self.complete=True
            elif self.phase=='verify':
                if not self.registered:self.fail('提交后INFO未登记精确配套包；不激活');return True
                if self.want_activate:self.phase='activate'
                else:self.state='done';self.complete=True
            elif self.action=='activate':
                if not self.registered:self.fail('配套模型包未在板卡精确登记');return True
                self.phase='activate'
            else:
                # Do not WBEGIN an already-registered companion and destroy an
                # engine package's partial single staging buffer on resume.
                self.phase='commit' if self._have_part(0) else 'begin'
                if self.phase=='commit':self.offset=self.candidate['parts'][0]['bytes']
            return True
        if d['kind']!=0x83 or d['acked_type']!=q['kind'] or d['acked_seq']!=q['seq']:return False
        if d['task']!=self.task:raise ValueError('Model ACK task mismatch')
        code,value=d['code'],d['value']
        self.receipts.append(dict(type=q['kind'],seq=q['seq'],kind=self.kind,code=code,value=value))
        if code==2 and q['kind']==m.WCHUNK:
            if value>len(self.parts[self.kind]) or self.corrections>=8:raise ValueError('Unbounded/invalid upload offset repair')
            self.corrections+=1;self.offset=value;self.phase='commit' if value==len(self.parts[self.kind]) else 'chunk';self.outstanding=None;return True
        if code:
            if code==4 and q['kind']==m.WCOMMIT:
                if value:raise ValueError('Failed SD commit cannot claim persisted')
                self.persisted[self.kind]=False
            self.fail(f'板卡模型命令{q["kind"]:02x}失败 code={code} value={value}；不自动激活/开始任务',
                      fatal=code==6 and value!=((-203)&0xffffffff))
            return True
        if q['kind']==m.WBEGIN:
            if value>len(self.parts[self.kind]):raise ValueError('WBEGIN offset beyond verified bytes')
            self.offset=value;self.phase='commit' if value==len(self.parts[self.kind]) else 'chunk'
        elif q['kind']==m.WCHUNK:
            expected=q['offset']+len(q['body'])-m.CHUNK.size
            if value!=expected:raise ValueError('WCHUNK acknowledged bytes mismatch')
            self.offset=value;self.phase='commit' if value==len(self.parts[self.kind]) else 'chunk'
        elif q['kind']==m.WCOMMIT:
            if value&~1:raise ValueError('WCOMMIT reserved value')
            self.persisted[self.kind]=bool(value&1)
            if not value:self.phase='await_idle';self.state='waiting_task_end';self.outstanding=None;return True
            if self.kind==0:
                self.kind=1;self.offset=0;self.phase='commit' if self._have_part(1) else 'begin'
                if self.phase=='commit':self.offset=self.candidate['parts'][1]['bytes']
            else:self.phase='verify'
        elif q['kind']==m.WACT:
            if value:raise ValueError('Single-bank next-task activation must not advertise a live row split')
            self.activated=True;self.complete=True;self.state='done'
        elif q['kind']==7:raise ValueError('INFO must return INFO_R, not success ACK')
        self.outstanding=None;return True
