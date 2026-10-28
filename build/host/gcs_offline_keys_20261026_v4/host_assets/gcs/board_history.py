"""Passive task-journal recovery. Never opens a socket, UART or model.

Snapshots are presentation caches, not evidence: CLASS words and protocol
state are rebuilt by strictly replaying the retained TX/RX journal.
"""
import json
import math
import struct
from datetime import datetime
from pathlib import Path
import board_task as task
import board_power


def apply_probe_reply(p,d,audit):
    """One live/replayed PROBE identity; never substitutes another task model."""
    if p['state'] not in ('running','done'):return
    identity=p.get('identity',audit.identity);scene=task.models.SCENES.index(identity['scene']);crc=int(identity['wcrc'],16)
    if d['kind']==0x85 and d['req_seq']==p['req_seq']:
        if (d['scene'],d['row'],d['col'],d['wcrc'])!=(scene,p['row'],p['col'],crc):raise ValueError('PROBE identity mismatch')
        result={k:d[k] for k in ('class_word','class_id','confidence_q16','logits_q16')}
        if p.get('result') and p['result']!=result or p['state']=='done' and any(p[k]!=v for k,v in result.items()):
            raise ValueError('conflicting repeated LOGITS')
        if identity==audit.identity:
            old=audit.rows.get(p['row'],[None]*audit.scene_width)[p['col']]
            if old is not None and old!=int(d['class_word'],16):raise ValueError('PROBE differs from task CLASS')
        p['result']=result
    if d['kind']==0x87 and d['req_seq']==p['req_seq']:
        import board_attention
        try:board_attention.accept(p,d,audit)
        except ValueError:
            board_attention.clear(p);p.update(state='error',error='Attention integrity failure');raise
    if p['state']!='running':return
    if d['kind']==0x84 and d['ping_seq']==p['ping_seq'] and d['t1']==p.get('stamp'):p['have_pong']=True
    if d['kind']==0x82 and d['task']==audit.task:p['have_status']=True
    if p.get('result') and p['have_pong'] and p['have_status'] and (not p.get('attention_requested') or 'attention_q24' in p):
        q=p['result']['logits_q16'];e=[math.exp((v-max(q))/65536) for v in q]
        p.update(p['result'],state='done',probabilities=[v/sum(e) for v in e],
                 probability_source='CPU softmax of board logits',attention_source=p.get('attention_source','not returned'))


class ProbeReplay:
    """Rebuild only recorded requests/replies; summary JSON cannot invent probes."""
    def __init__(self):
        self.requests={};self.pings={};self.items=[]

    def add(self, direction, data, d, audit):
        kind,seq=data[2],task.wire.HEADER.unpack_from(data)[4]
        if direction=='tx':
            if kind==5:self.pings[seq]=task.wire.HEADER.unpack_from(data)[5]
            if kind==9 and seq not in self.requests:
                scene,flags,row,col,_,crc=struct.unpack_from('<BBHHHI',data,12)
                spec=task.models.scene_spec(scene)
                # Only tag-less wire identity for a different model is proved
                # by this request. Do not borrow the current task's model tag.
                identity=audit.identity if (scene,crc)==(audit.scene_id,audit.crc) else dict(scene=spec['scene'],model=None,wcrc=f'{crc:08x}',shape=spec['shape'],classes=spec['classes'],kind=1)
                p=dict(state='running',row=row,col=col,req_seq=seq,ping_seq=(seq-1)&65535,
                       have_pong=False,have_status=False,error=None,restored_from='PACKET_JOURNAL',identity=identity,
                       stamp=self.pings.get((seq-1)&65535),attention_requested=bool(flags&1))
                self.requests[seq]=p;self.items.append(p)
            return
        if d is None:return
        for p in self.requests.values():
            apply_probe_reply(p,d,audit)


def load_job(directory):
    directory = Path(directory)
    meta = json.loads((directory/'session.json').read_text(encoding='utf-8'))
    if meta.get('scope') not in ('TASK_LIFECYCLE','MODEL_TASK_LIFECYCLE') or tuple(meta.get('target',()))!=task.wire.TARGET:
        raise ValueError('Not a lifecycle journal at the board endpoint')
    identity=task.models.task_identity(meta['identity']) if meta['scope']=='MODEL_TASK_LIFECYCLE' else None
    scene=identity['scene'] if identity else 'longkou'
    rect = task.rect_for(dict(kind='region',scene=scene,rect=meta['rect']))
    boot, session, tid = (meta[k] for k in ('boot_id','session','task'))
    if any(type(v) is not int for v in (boot,session,tid)) or not 0<boot<2**32 or not 0<session<2**32 or not 0<tid<65536:
        raise ValueError('Invalid journal identity')
    job = task.Job(boot,session,tid,rect,meta.get('fresh',tid==1),identity)
    job.out=directory;job.channel_open=False;job.host_run=meta.get('host_run')
    if identity is not None:job.candidate=meta.get('candidate')
    host=job.host_run
    if host is not None:
        if not isinstance(host,dict) or host.get('scene')!=scene or not isinstance(host.get('version'),str) or host.get('kind') not in ('scan','region'):
            raise ValueError('Invalid history host-run metadata')
        if identity is None and host.get('version')!='v2':raise ValueError('Legacy history model mismatch')
        if identity is not None:
            candidate=meta.get('candidate')
            if candidate and (task.models.candidate_identity(candidate)!=identity or candidate.get('version',candidate['tag'])!=host['version']):raise ValueError('History candidate identity mismatch')
        if host['kind']=='scan' and rect!=[0,0,*job.audit.identity['shape']] or host['kind']=='region' and host.get('rect')!=rect:
            raise ValueError('History host-run/packet ROI mismatch')
        if type(host.get('t0')) not in (int,float) or not math.isfinite(host['t0']):raise ValueError('Invalid history time')
    snapshot={}
    if (directory/'summary.json').exists():
        snapshot=json.loads((directory/'summary.json').read_text(encoding='utf-8'))
        if (snapshot.get('boot_id'),snapshot.get('session'),snapshot.get('task')) != (f'{boot:08x}',f'{session:08x}',tid):
            raise ValueError('Snapshot/journal identity mismatch')
    a=job.audit;probes=ProbeReplay();recovery=None
    with (directory/'packets.jsonl').open(encoding='utf-8') as f:
        for line_no,line in enumerate(f,1):
            try:
                if not line.endswith('\n'):raise ValueError('Truncated packet journal')
                record=json.loads(line)
                if record['direction']=='event':
                    if record.get('event')!='recovery_begin':raise ValueError('Unknown journal event')
                    a.begin_recovery()
                    recovery=dict(state='incomplete',restored_from='PACKET_JOURNAL',info=None,have_pong=False,have_status=False)
                    job.recoveries.append(recovery)
                    continue
                if tuple(record.get('peer',()))!=task.wire.TARGET:raise ValueError('Journal peer mismatch')
                data=bytes.fromhex(record['hex'])
                if record['direction']=='tx':
                    a.sent(data);job.tx_pkts+=1;job.tx_bytes+=len(data)
                    job.next_sequence=(task.wire.HEADER.unpack_from(data)[4]+1)&65535
                    probes.add('tx',data,None,a)
                elif record['direction']=='rx':
                    if len(data)>2 and data[2]==board_power.MESSAGE:
                        board_power.accept_job(job,board_power.decode(data,boot,session));continue
                    d=a.received(data);job.rx_pkts+=1;job.rx_bytes+=len(data)
                    probes.add('rx',data,d,a)
                    if recovery is not None and d:
                        if d['kind']==0x86:recovery['info']=a.info
                        if recovery['info'] and d['kind']==0x84 and a.have_pong:recovery['have_pong']=True
                        if recovery['info'] and d['kind']==0x82 and d['task']==a.task:recovery['have_status']=True
                        if recovery['info'] and recovery['have_pong'] and recovery['have_status']:recovery['state']='reconciled'
                else:raise ValueError('Unknown packet direction')
            except (ValueError,KeyError,TypeError,struct.error) as exc:
                job.integrity_error=True;job.error=f'Journal line {line_no}: {exc}'
                break  # preserve only the verified prefix, never skip a bad packet
    job.last_status=a.last_status
    job.started=snapshot.get('started',job.started);job.ended=snapshot.get('ended')
    for text in (job.started,job.ended):
        if text is not None:datetime.fromisoformat(text)
    for p in probes.items:
        if p['state']=='running':p.update(state='error',error='历史日志未包含完整PROBE与连接回执')
    job.probes=probes.items
    job.probe_result=job.probes[-1] if job.probes else None
    job.integrity_error=job.integrity_error or bool(snapshot.get('integrity_error'))
    job.error=job.error or snapshot.get('error')
    if not job.integrity_error and a.complete():
        job.state='done' if a.final['state']==3 else 'stopped'
    else:
        job.state='error'
        job.error=job.error or '服务重启或采集未完成；只加载已核对像素，需显式恢复'
    try:
        import board_log
        evidence=board_log.latest(directory,boot,session,tid)
        if evidence:job.board_log_evidence=evidence;job.board_log_state='ready'
    except (OSError,ValueError,KeyError,TypeError) as exc:
        job.board_log_state='error';job.board_log_error=str(exc)
    return job


def load_all(root):
    jobs, errors = [], []
    for directory in sorted(Path(root).glob('task_*')):
        if not directory.is_dir():continue
        try:jobs.append(load_job(directory))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append(dict(path=str(directory),error=str(exc)))
    return jobs, errors
