"""Bounded actual board records over the owned UDP socket, never synthetic UART.

GET/import remain passive. Only an explicit discovery/task/evidence operation
calls fetch. Artifacts are rebuilt from raw request/reply pages before use.
"""
from datetime import datetime
import hashlib,json,re,socket,struct,time,zlib
from pathlib import Path

HEADER=struct.Struct('<HBBHHI')
QUERY=0x14;REPLY=0x88;PAGE=1372;BOOT_BYTES=4096;TASK_BYTES=65536

def _uint(value,bits):
    if type(value) is not int or not 0<=value<1<<bits:raise ValueError('Board-log integer range')
    return value

def request(boot,session,task,offset,size,seq):
    for n in (boot,session,offset,size):_uint(n,32)
    _uint(task,16);_uint(seq,16)
    if task and not session or session and not boot or offset and not size:raise ValueError('Board-log query identity/range')
    return HEADER.pack(0x4548,QUERY,1,task,seq,0)+struct.pack('<4I',boot,session,offset,size)

def _query(raw):
    if len(raw)!=28:raise ValueError('Board-log query length')
    magic,kind,ver,task,seq,_=HEADER.unpack_from(raw)
    boot,session,offset,size=struct.unpack_from('<4I',raw,12)
    if (magic,kind,ver)!=(0x4548,QUERY,1):raise ValueError('Board-log query header')
    request(boot,session,task,offset,size,seq)
    return dict(boot=boot,session=session,task=task,offset=offset,size=size,seq=seq)

def decode(raw):
    if not 40<=len(raw)<=1412:raise ValueError('Board-log reply length')
    magic,kind,version,task,seq,stamp=HEADER.unpack_from(raw)
    boot,session,req,fmt,flags,offset,size,crc,count,res=struct.unpack_from('<IIHBBIIIHH',raw,12)
    if (magic,kind,version,fmt)!=(0x4548,REPLY,1,1) or res or flags not in (0,1):raise ValueError('Board-log reply header/reserved')
    if not boot or task and not session or size>(TASK_BYTES if session else BOOT_BYTES):raise ValueError('Board-log reply identity/capacity')
    if offset>size or count!=min(PAGE,size-offset) or len(raw)!=40+count:raise ValueError('Board-log reply page bounds')
    return dict(kind=kind,task=task,seq=seq,t_us=stamp,boot=boot,session=session,request_seq=req,
                overflow=bool(flags),offset=offset,size=size,crc=crc,data=raw[40:])

class _Replay:
    def __init__(self,boot,session,task,sequence=0):
        request(boot,session,task,0,0,sequence)
        self.boot=boot;self.streams=[(0,0)]+([(session,task)] if session else [])
        self.index=0;self.seq=sequence;self.pending=None;self.answered={};self.results={}
        self.data=bytearray();self.size=None;self.crc=None
    @property
    def complete(self):return self.index==len(self.streams)
    def next(self):
        if self.complete:raise ValueError('Board-log transfer already complete')
        session,task=self.streams[self.index]
        return request(self.boot,session,task,len(self.data),self.size or 0,self.seq)
    def sent(self,raw):
        q=_query(raw)
        if self.pending is not None:
            if q!=self.pending:raise ValueError('Changed in-flight board-log query')
            return
        if self.complete or raw!=self.next():raise ValueError('Unrequested/reordered board-log page')
        self.pending=q
    def received(self,raw):
        if len(raw)<3 or raw[2]!=REPLY:
            if len(raw)==20 and raw[2]==0x83 and raw[12]==QUERY and self.pending and struct.unpack_from('<H',raw,14)[0]==self.pending['seq']:
                raise ValueError('Board rejected log read, code='+str(raw[13]))
            return False
        d=decode(raw)
        if d['overflow']:raise ValueError('Board log overflowed/truncated; no complete evidence')
        if self.boot and d['boot']!=self.boot:raise ValueError('Board-log boot identity changed')
        if self.pending is None or d['request_seq']!=self.pending['seq']:
            old=self.answered.get(d['request_seq'])
            if old:
                # A retried first-page query may see a later append-only prefix.
                q,prior=old
                same=all(d[k]==prior[k] for k in ('boot','session','task','offset'))
                growing=not q['size'] and d['size']>=prior['size'] and d['data'].startswith(prior['data'])
                if not same or not growing and any(d[k]!=prior[k] for k in ('size','crc','data')):
                    raise ValueError('Conflicting duplicate board-log page')
            return False
        q=self.pending
        if (d['session'],d['task'],d['offset'])!=(q['session'],q['task'],q['offset']):raise ValueError('Board-log page/request identity mismatch')
        if self.size is None:self.size,self.crc=d['size'],d['crc']
        if (d['size'],d['crc'])!=(self.size,self.crc) or q['size'] and q['size']!=d['size']:raise ValueError('Board-log snapshot changed')
        self.boot=d['boot'];self.data.extend(d['data']);self.answered[q['seq']]=(q,d)
        self.pending=None;self.seq=(self.seq+1)&65535
        if len(self.data)==self.size:
            if zlib.crc32(self.data)!=self.crc:raise ValueError('Board-log snapshot CRC mismatch')
            self.results[self.streams[self.index]]=bytes(self.data);self.index+=1
            self.data=bytearray();self.size=self.crc=None
        return True
    def value(self):
        if not self.complete:raise ValueError('Incomplete board-log packet trace')
        boot=self.results[(0,0)];stream=self.results[self.streams[-1]] if len(self.streams)>1 else b''
        model=bool(self.streams[-1][0] and not self.streams[-1][1])
        return dict(boot=self.boot,boot_log=boot,task_log=b'' if model else stream,model_log=stream if model else b'',board_log=boot+stream,next_sequence=self.seq)

def stream_files(session,task):
    return (('boot_log.bin','boot_log'),('model_log.bin','model_log') if session and not task else ('task_log.bin','task_log'),('board_log.txt','board_log'))

def fetch(sock,target,out,boot=0,session=0,task=0,timeout=3,sequence=0,on_packet=None,expected_build=None,cancelled=None):
    """Synchronous bounded read only while no task/control/probe is in flight.

    Caller owns sock; no bind, PING, START, model operation, UART or reset here.
    Diagnostic sequences are separate from the task/heartbeat command sequence.
    """
    if not 0<timeout<=15:raise ValueError('Bounded board-log timeout required')
    target=tuple(target);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    replay=_Replay(boot,session,task,sequence);previous=sock.gettimeout()
    meta=dict(schema='gcs-board-log-v1',result='FAIL',transport='ETHERNET_BOARD_RECORDS',target=list(target),
              requested_boot=boot,session=session,task=task,sequence=sequence,started=datetime.now().astimezone().isoformat())
    deadline=time.monotonic()+timeout
    try:
        with (out/'packets.jsonl').open('x',encoding='utf-8') as trace:
            def record(direction,raw,peer):
                trace.write(json.dumps(dict(direction=direction,peer=list(peer),monotonic_ns=time.perf_counter_ns(),hex=raw.hex()))+'\n');trace.flush()
                if on_packet:on_packet(direction,raw)
            while not replay.complete:
                raw=replay.next();replay.sent(raw);attempts=0;next_send=0
                while time.monotonic()<deadline:
                    if cancelled and cancelled():raise InterruptedError('Board-log read cancelled; original owner closing')
                    now=time.monotonic()
                    if now>=next_send and attempts<3:
                        record('tx',raw,target)
                        if sock.sendto(raw,target)!=len(raw):raise OSError('Short board-log UDP write')
                        attempts+=1;next_send=now+.25
                    sock.settimeout(min(.1,max(.001,deadline-time.monotonic())))
                    try:reply,peer=sock.recvfrom(2048)
                    except socket.timeout:continue
                    if tuple(peer)!=target:continue
                    record('rx',reply,peer)
                    if replay.received(reply):break
                else:raise TimeoutError('Board-log read timeout; no fallback or task sent')
                if replay.pending is not None:raise TimeoutError('Board-log page missing')
        value=replay.value()
        if expected_build is not None:parse_boot(value['boot_log'],expected_build)
        for name,key in stream_files(session,task):
            (out/name).write_bytes(value[key])
        meta.update(result='PASS',boot=value['boot'],next_sequence=value['next_sequence'],
            sha256={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name,_ in stream_files(session,task)})
        return dict(meta,evidence=str(out.resolve()))
    except Exception as exc:meta['error']=str(exc);raise
    finally:
        sock.settimeout(previous);meta['ended']=datetime.now().astimezone().isoformat()
        (out/'receipt.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')

def audit(directory,expected_boot=None,expected_session=None,expected_task=None):
    """Rebuild pages from raw traffic; cached text/receipt alone is not proof."""
    directory=Path(directory);meta=json.loads((directory/'receipt.json').read_text(encoding='utf-8'))
    # The production endpoint is fixed; importing here avoids a decode cycle.
    import board_task
    target=tuple(board_task.wire.TARGET)
    if meta.get('schema')!='gcs-board-log-v1' or meta.get('result')!='PASS' or meta.get('transport')!='ETHERNET_BOARD_RECORDS' or tuple(meta.get('target',()))!=target:
        raise ValueError('Not a complete board-log artifact at the fixed board endpoint')
    replay=_Replay(meta['requested_boot'],meta['session'],meta['task'],meta['sequence'])
    with (directory/'packets.jsonl').open(encoding='utf-8') as trace:
        for line in trace:
            if not line.endswith('\n'):raise ValueError('Truncated board-log trace')
            row=json.loads(line);raw=bytes.fromhex(row['hex'])
            if tuple(row.get('peer',()))!=target:raise ValueError('Board-log trace peer mismatch')
            if row['direction']=='tx':replay.sent(raw)
            elif row['direction']=='rx':replay.received(raw)
            else:raise ValueError('Unknown board-log trace direction')
    value=replay.value()
    if value['boot']!=meta['boot'] or value['next_sequence']!=meta['next_sequence']:raise ValueError('Board-log receipt identity/sequence changed')
    for expected,actual in ((expected_boot,value['boot']),(expected_session,meta['session']),(expected_task,meta['task'])):
        if expected is not None and expected!=actual:raise ValueError('Board-log artifact belongs to another boot/session/task')
    for name,key in stream_files(meta['session'],meta['task']):
        raw=(directory/name).read_bytes()
        if raw!=value[key] or hashlib.sha256(raw).hexdigest()!=meta['sha256'][name]:raise ValueError('Board-log text differs from raw packet replay')
    return dict(value,session=meta['session'],task=meta['task'],evidence=str(directory.resolve()),transport=meta['transport'])

def parse_boot(raw,expected):
    """Full release/source/XSA + SD reservation; no physical cold-boot claim."""
    from board_release import uart_build,APP_ID
    text=raw.decode('ascii');text='\n'.join(s.strip('\r') for s in text.split('\n'))
    build=uart_build(text,expected)
    matches=re.findall(r'^S2C IDENTITY source=sd-journal boot_id=([0-9a-f]{8}) generation=([1-9][0-9]{0,9}) nonce=([0-9a-f]{16}) abi=4$',text,re.M|re.I)
    if len(matches)!=1:raise ValueError('Missing/duplicate board-log SD identity')
    boot,generation,nonce=int(matches[0][0],16),int(matches[0][1]),int(matches[0][2],16)
    if not 0<generation<boot<2**32 or not nonce:raise ValueError('Invalid board-log SD reservation')
    result=dict(build=build,boot_id=boot,generation=generation,nonce=f'{nonce:016x}',state='starting',
                registry_count=None,scan_ok=None,independent_cold_start_verified=False,transport='ethernet')
    stops=re.findall(r'^S2C (?:STOP|HALTED)(.*)$',text,re.M)
    if stops:result.update(state='error',error=stops[-1].strip());return result
    scans=re.findall(r'^S2C boot_id=([0-9a-f]{8}) MODEL_SCAN int16; no inference yet$',text,re.M|re.I)
    if scans:
        if len(scans)!=1 or int(scans[0],16)!=boot:raise ValueError('Board-log scan boot mismatch')
        result['state']='scanning_models'
    progress=re.findall(r'^S2C STARTUP phase=model_scan bytes=(\d+) directories=(\d+) registered=(\d+) rejected=(\d+)$',text,re.M)
    if progress:result['scan_progress']=dict(zip(('bytes','directories','registered','rejected'),map(int,progress[-1])))
    if 'S2C STARTUP phase=display_initialization' in text:result['state']='initializing_display'
    dp=re.findall(r'^S2C DP init_rc=(-?\d+) 1920x1080; picture requires user check; no SD assets$',text,re.M)
    if len(dp)>1:raise ValueError('Duplicate board-log DP startup')
    if dp:result['dp_rc']=int(dp[0])
    ready=re.findall(r'^S2C READY boot_id=([0-9a-f]{8}) registry=(\d{1,2}) scan_ok=([01]) scenes=3 roi=any banks=1 UDP=5010 app='+APP_ID+'$',text,re.M|re.I)
    if len(ready)>1:raise ValueError('Duplicate board-log READY')
    if ready:
        found,count,scan=ready[0]
        if int(found,16)!=boot or int(count)>48:raise ValueError('Board-log READY identity mismatch')
        scans_done=re.findall(r'^S2C MODEL_SCAN complete=([01]) entries=(\d+) rejected=(\d+) rc=(-?\d+) cleanup=(-?\d+) reject_rc=(-?\d+) reject_code=(\d+)$',text,re.M)
        if len(scans_done)!=1 or len(dp)!=1:raise ValueError('READY without full scan/display startup receipts')
        done,entries,rejected,rc,cleanup,reject_rc,reject_code=map(int,scans_done[0])
        if done!=int(scan) or entries!=int(count) or done and (rc or cleanup):raise ValueError('Contradictory model scan/READY')
        result['scan_receipt']=dict(complete=bool(done),entries=entries,rejected=rejected,rc=rc,cleanup=cleanup,reject_rc=reject_rc,reject_code=reject_code)
        result.update(state='ready',registry_count=int(count),scan_ok=bool(int(scan)))
        if not result['scan_ok']:result.update(state='error',error='Board model scan failed; inspect actual scan receipt')
    return result

def labels(value):
    """Label the actual transport after parsing shared board-record syntax."""
    if isinstance(value,dict):return {(k.replace('uart','board_log') if isinstance(k,str) else k):labels(v) for k,v in value.items()}
    if isinstance(value,list):return [labels(v) for v in value]
    if isinstance(value,str):return value.replace('UART','ETHERNET_BOARD_LOG')
    return value

def latest(directory,boot,session,task):
    candidates=sorted((Path(directory)/'board_logs').glob('read_*'))
    if not candidates:return None
    selected=candidates[-1]
    if not selected.is_dir():raise ValueError('Invalid board-log artifact directory')
    audit(selected,boot,session,task) # never fall back over a newer failed read
    return str(selected.resolve())
