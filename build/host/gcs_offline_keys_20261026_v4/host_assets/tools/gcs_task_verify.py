"""Read-only lifecycle artifact verifier, independent of Job/Audit state.

Reconcile task-scoped UART, recorded v1 packets, every raw CLASS word/mask,
compute timing and the exported JSON. No devices, model inference or servers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'gcs'))
import board_task as wire
from board_release import READY_APPS,APP_ID,uart_build,expected_build


def one(pattern,text,label):
    found=re.findall(pattern,text,re.M|re.I)
    if len(found)!=1:raise ValueError(f'{label}: expected one receipt, got {len(found)}')
    return found[0]


def verify(directory, uart=None, exported=None,elf_audit=None,network_log=None):
    directory=Path(directory)
    meta=json.loads((directory/'session.json').read_text(encoding='utf-8-sig'))
    if meta.get('scope') not in ('TASK_LIFECYCLE','MODEL_TASK_LIFECYCLE') or tuple(meta.get('target',()))!=wire.wire.TARGET:
        raise ValueError('Not a lifecycle journal at the board endpoint')
    boot,session,task=(meta[k] for k in ('boot_id','session','task'))
    if any(type(v) is not int for v in (boot,session,task)) or not 0<boot<2**32 or not 0<session<2**32 or not 0<task<65536:
        raise ValueError('Invalid task identity')
    modern=meta['scope']=='MODEL_TASK_LIFECYCLE'
    identity=wire.models.task_identity(meta['identity']) if modern else dict(scene='longkou',model='v2',wcrc=f'{wire.wire.WCRC:08x}',shape=[550,400],classes=9,kind=1)
    scene=wire.models.SCENES.index(identity['scene']);model_crc=int(identity['wcrc'],16);image_h,image_w=identity['shape'];ncls=identity['classes']
    rect=wire.rect_for(dict(kind='region',scene=identity['scene'],rect=meta['rect']))
    y,x,h,w=rect;total=h*w
    start_body=struct.pack('<BBBB4HII',0 if total==image_h*image_w else 1,scene,0,0,y,x,h,w,model_crc,session)
    commands={};words={};statuses=[];start_seq=None;acked=False;info_confirmed=False
    recovery=False;recovery_count=0;controls=[];requests={};replies={};pings={};pongs={}
    attention_requests={};attention_fragments={}
    recovery_resolved=True;info_line=None;control_acks={}
    with (directory/'packets.jsonl').open(encoding='utf-8') as stream:
        for line_no,line in enumerate(stream,1):
            if not line.endswith('\n'):raise ValueError('Truncated packet journal')
            record=json.loads(line)
            if record['direction']=='event':
                if record.get('event')!='recovery_begin':raise ValueError('Unknown journal event')
                recovery=True;recovery_count+=1;recovery_resolved=False;info_line=None;continue
            if tuple(record.get('peer',()))!=wire.wire.TARGET:raise ValueError('Journal peer mismatch')
            raw=bytes.fromhex(record['hex'])
            if len(raw)<12:raise ValueError('Truncated packet header')
            magic,kind,version,tid,seq,stamp=wire.wire.HEADER.unpack_from(raw)
            if magic!=0x4548 or version!=1:raise ValueError('Packet header')
            if record['direction']=='tx':
                if kind==5:
                    if raw[12:]!=struct.pack('<I',session):raise ValueError('PING session mismatch')
                    pings.setdefault((seq,stamp),line_no)
                elif kind==7:
                    if len(raw)!=12:raise ValueError('INFO request size')
                else:
                    if tid!=task:raise ValueError('TX task mismatch')
                    if kind==1:
                        if recovery_count:raise ValueError('START during/after recovery of the same task')
                        if raw[12:]!=start_body:raise ValueError('START ROI/model mismatch')
                        if start_seq is None:start_seq=seq
                    elif kind in (2,3,4):
                        if len(raw)!=12:raise ValueError('Control length')
                        if not recovery_resolved:raise ValueError('Control during unconfirmed recovery')
                        controls.append((kind,seq,line_no))
                    elif kind==6:
                        if len(raw)<20:raise ValueError('ROWREQ length')
                        n,pad=struct.unpack_from('<HH',raw,12)
                        if not 0<n<=349 or pad or len(raw)!=16+4*n:raise ValueError('ROWREQ shape')
                        for off in range(16,len(raw),4):
                            ry,nrows=struct.unpack_from('<HH',raw,off)
                            if not nrows or ry>=image_h or ry+nrows>image_h:raise ValueError('ROWREQ range')
                    elif kind==9:
                        if len(raw)!=24:raise ValueError('PROBE shape')
                        sc,pad,ry,rx,res,crc=struct.unpack_from('<BBHHHI',raw,12)
                        spec=wire.models.scene_spec(sc)
                        if pad&~1 or res or not crc or ry>=spec['shape'][0] or rx>=spec['shape'][1]:raise ValueError('PROBE identity')
                        if seq in attention_requests and attention_requests[seq]!=bool(pad&1):raise ValueError('PROBE attention flag changed on retry')
                        attention_requests[seq]=bool(pad&1)
                        if seq in requests and (requests[seq][:2]!= (ry,rx) or requests[seq][3:]!=(sc,crc,spec['classes'],stamp)):raise ValueError('Conflicting PROBE request')
                        requests.setdefault(seq,(ry,rx,line_no,sc,crc,spec['classes'],stamp))
                    else:raise ValueError('Unknown task TX')
                commands[seq]=kind
                continue
            if record['direction']!='rx':raise ValueError('Unknown journal direction')
            d=wire.decode(raw)
            if kind==0x86:
                if not recovery or 7 not in commands.values():raise ValueError('Unsolicited INFO')
                if (d['boot_id'],d['session'],d['task'],d['scene'],d['wcrc'],d['rect'])!=(boot,session,task,scene,model_crc,rect):
                    raise ValueError('Recovery identity mismatch')
                info_confirmed=True;info_line=line_no
            elif kind==0x84:
                key=(d['ping_seq'],d['t1'])
                if key in pings:pongs[key]=line_no
            elif kind==0x82:
                if (d['boot_id'],d['session'])!=(boot,session):raise ValueError('STATUS identity mismatch')
                if tid!=task:continue
                if d['wcrc']!=model_crc:raise ValueError('STATUS model identity mismatch')
                clock_reanchor=recovery and not recovery_resolved
                if clock_reanchor and not (info_line and any(at>info_line and pongs.get(key,0)>at for key,at in pings.items())):continue
                if d['total']!=total or not 0<=d['done']<=total or d['front_row']!=y+d['done']//w or d['state'] not in (0,1,2,3):
                    raise ValueError('STATUS task frontier mismatch')
                if d['state'] in (0,2,3) and d['done']%w:raise ValueError('Unsafe terminal/control boundary')
                if d['state']==3 and d['done']!=total:raise ValueError('Incomplete DONE')
                if not clock_reanchor and statuses and ((stamp-statuses[-1]['t_us'])&0xffffffff)>=0x80000000:continue
                if statuses and d['done']<statuses[-1]['done']:continue
                if statuses and statuses[-1]['state'] in (0,3) and (d['state'],d['done'])!=(statuses[-1]['state'],statuses[-1]['done']):
                    raise ValueError('Terminal task state changed')
                d['_line']=line_no;statuses.append(d)
            elif tid!=task:continue
            elif kind==0x83:
                if d['code'] and (commands.get(d['acked_seq'])==d['acked_type'] or d['acked_type']==1 and d['acked_seq']==start_seq):
                    raise ValueError('Board rejected command/fault ACK')
                if d['acked_type']==1 and commands.get(d['acked_seq'])==1 and not d['code']:acked=True
                if d['acked_type'] in (2,3,4) and commands.get(d['acked_seq'])==d['acked_type']:
                    control_acks.setdefault((d['acked_type'],d['acked_seq']),[]).append((line_no,d['value']))
            elif kind==0x81:
                if start_seq is None:raise ValueError('ROW without recorded START')
                if not y<=d['row']<y+h or not x<=d['col']<d['col']+len(d['words'])<=x+w:raise ValueError('ROW outside ROI')
                for i,word in enumerate(d['words']):
                    if (word&255)>=ncls:raise ValueError('CLASS differs from scene classes')
                    key=(d['row'],d['col']+i)
                    if key in words and words[key]!=word:raise ValueError('Conflicting duplicate CLASS')
                    words[key]=word
            elif kind==0x85:
                req=d['req_seq']
                if req not in requests or (d['row'],d['col'])!=requests[req][:2] or (d['scene'],d['wcrc'],len(d['logits_q16']))!=requests[req][3:6]:
                    raise ValueError('Unmatched PROBE result')
                if req in replies and (replies[req]['logits_q16'],replies[req]['class_word'])!=(d['logits_q16'],d['class_word']):raise ValueError('Conflicting logits')
                replies[req]=d
            elif kind==0x87:
                req=d['req_seq']
                if req not in requests or not attention_requests.get(req):raise ValueError('Unrequested ATTENTION')
                request=requests[req]
                if (d['boot_id'],d['session'],d['row'],d['col'],d['scene'],d['wcrc'],d['ncls'])!=(boot,session,*request[:2],*request[3:6]):
                    raise ValueError('ATTENTION raw identity differs from request')
                item=attention_fragments.setdefault(req,dict(crc=d['crc32'],parts={}))
                if item['crc']!=d['crc32']:raise ValueError('Conflicting ATTENTION tensor identity')
                part=d['fragment']
                if part in item['parts'] and item['parts'][part]!=d['words']:raise ValueError('Conflicting ATTENTION fragment')
                item['parts'][part]=list(d['words'])
            if recovery and not recovery_resolved and info_line:
                have_pong=any(at>info_line and pongs.get(key,0)>at for key,at in pings.items())
                have_status=bool(statuses and statuses[-1]['_line']>info_line)
                recovery_resolved=have_pong and have_status
    if not recovery_resolved:raise ValueError('Unconfirmed recovery INFO/PING/STATUS handshake')
    if not (acked or info_confirmed) or not statuses or statuses[-1]['state'] not in (0,3):
        raise ValueError('Task acceptance or terminal STATUS missing')
    final=statuses[-1];count=final['done']
    expected=[(y+i//w,x+i%w) for i in range(count)]
    if set(words)!=set(expected):raise ValueError('Terminal coverage missing or outside committed prefix')
    raw_words=struct.pack(f'<{count}I',*(words[k] for k in expected))
    crc=zlib.crc32(raw_words)
    if network_log is not None:
        import board_log
        network_records=board_log.audit(network_log,boot,session,task)
        if uart is not None and Path(uart).read_bytes()!=network_records['board_log']:raise ValueError('Snapshot differs from Ethernet board records')
        text=network_records['board_log'].decode('ascii')
        if elf_audit is None:elf_audit=Path(network_log)/'elf_audit.json'
        board_log.parse_boot(network_records['boot_log'],expected_build(elf_audit))
    else:
        if uart is None:raise ValueError('Verified Ethernet board log or legacy UART artifact required')
        text=Path(uart).read_text(encoding='utf-8-sig')
    text='\n'.join(line.strip('\r') for line in text.split('\n'))
    if re.search(r'^S2C (?:STOP|HALTED|PROBE HALTED)',text,re.M):raise ValueError('UART fault/stop receipt')
    ready=one(r'^S2C READY boot_id=([0-9a-f]{8}) registry=(?:[0-9]|[1-3][0-9]|4[0-8]) scan_ok=[01] scenes=3 roi=any banks=1 UDP=5010 app='+READY_APPS+'$' if modern else
              r'^S2C READY boot_id=([0-9a-f]{8}) wcrc=27231983 roi=any scan=400x550 UDP=5010 app=task_lifecycle_r1$',text,'READY')
    if int(ready,16)!=boot:raise ValueError('UART boot mismatch')
    release_build=None
    if 'app='+APP_ID in text.lower():
        if not re.search(r'^S2C READY .* app='+APP_ID+'$',text,re.M|re.I):raise ValueError('Mixed current BUILD and old READY')
        audit=Path(elf_audit) if elf_audit else directory/'elf_audit.json'
        if not audit.is_file():audit=Path(uart).parent/'elf_audit.json'
        release_build=uart_build(text,expected_build(audit))
    prefix=rf'session={session:08x} task={task}'
    model_fields=rf' scene={scene} model={re.escape(identity["model"])} wcrc={model_crc:08x}' if modern else ''
    class_field=rf' classes={ncls}' if modern else ''
    begin=one(rf'^S2C TASK_BEGIN {prefix}{model_fields} x=(\d+) y=(\d+) w=(\d+) h=(\d+){class_field}$',text,'TASK_BEGIN')
    if tuple(map(int,begin))!=(x,y,w,h):raise ValueError('UART ROI mismatch')
    terminal='TASK_DONE' if final['state']==3 else 'TASK_STOP'
    n,us,uart_crc=one(rf'^S2C {terminal} {prefix} completed=(\d+) compute_us=(\d+) crc32=([0-9a-f]{{8}})$',text,terminal)
    if (int(n),int(uart_crc,16))!=(count,crc):raise ValueError('UART count/CLASS CRC mismatch')
    compute_us=int(us)
    if count:
        if compute_us<=0 or final['ms_per_px'] is None or struct.pack('<f',compute_us/1000/count)!=struct.pack('<f',final['ms_per_px']):
            raise ValueError('UART/STATUS compute timing mismatch')
    elif compute_us or final['ms_per_px'] is not None:raise ValueError('Timing without committed pixels')
    browser=bytearray(image_h*image_w*5);cells=[];counts=[0]*ncls
    for (ry,rx),word in sorted(words.items()):
        pos=ry*image_w+rx;struct.pack_into('<I',browser,4*pos,word);browser[image_h*image_w*4+pos]=1
        counts[word&255]+=1
        cells.append(dict(x=rx,y=ry,class_word=f'{word:08X}',class_id=word&255,confidence_q16=word>>16,confidence=(word>>16)/65536))
    saved=json.loads(Path(exported or directory/'summary.json').read_text(encoding='utf-8-sig'))
    if saved.get('integrity_error'):raise ValueError('Export has an integrity failure')
    required=dict(boot_id=f'{boot:08x}',session=f'{session:08x}',task=task,start_seq=start_seq,scene=identity['scene'],model=identity['model'],wcrc=identity['wcrc'],
                  roi=dict(x=x,y=y,width=w,height=h),status='done' if final['state']==3 else 'stopped',error=None,
                  received_pixels=count,total=total,class_counts=counts,cells=cells)
    for key,value in required.items():
        if saved.get(key)!=value:raise ValueError('Export/journal mismatch: '+key)
    control_rows=re.findall(rf'^S2C CONTROL {prefix} type=(\d+) seq=(\d+) completed=(\d+)$',text,re.M|re.I)
    control_checks=[]
    for kind,seq,n in control_rows:
        kind,seq,n=map(int,(kind,seq,n));tx=next((at for k,s,at in controls if (k,s)==(kind,seq)),None)
        if tx is None or not 0<=n<=total or n%w:raise ValueError('UART CONTROL request/boundary mismatch')
        confirmed=any(at>tx and front==y+n//w for at,front in control_acks.get((kind,seq),[]))
        state_seen=any(s['_line']>tx and s['state'] in ({2:0,3:2,4:1}[kind],3) and s['done']>=n for s in statuses)
        control_checks.append(dict(type=kind,seq=seq,completed=n,ack=confirmed,status=state_seen,passed=confirmed and state_seen))
    groups=[]
    for kind,seq,at in controls:
        if not groups or groups[-1]['type']!=kind:groups.append(dict(type=kind,sequences=[]))
        if seq not in groups[-1]['sequences']:groups[-1]['sequences'].append(seq)
    for group in groups:
        group['passed']=any(c['type']==group['type'] and c['seq'] in group['sequences'] and c['passed'] for c in control_checks)
    probe_checks=[]
    attention_checks=[]
    for seq,(ry,rx,line_no,probe_scene,probe_crc,probe_ncls,probe_stamp) in requests.items():
        d=replies.get(seq);checks=dict(logits=d is not None,uart=False,handshake=False,class_word=False)
        if d:
            probe_fields=rf' scene={probe_scene} wcrc={probe_crc:08x} ncls={probe_ncls}' if modern else ''
            rows=re.findall(rf'^S2C PROBE {prefix} seq={seq}{probe_fields} x=(\d+) y=(\d+) class_word=([0-9a-f]{{8}})$',text,re.M|re.I)
            logits=re.findall(rf'^S2C LOGIT {prefix} seq={seq} class=(\d+) q16=(-?\d+)$',text,re.M|re.I)
            checks['uart']=len(rows)==1 and (int(rows[0][0]),int(rows[0][1]),int(rows[0][2],16))==(rx,ry,int(d['class_word'],16)) and sorted((int(k),int(v)) for k,v in logits)==list(enumerate(d['logits_q16']))
            same_model=(probe_scene,probe_crc)==(scene,model_crc)
            checks['class_word']=not same_model or (ry,rx) not in words or words[ry,rx]==int(d['class_word'],16)
            key=((seq-1)&65535,probe_stamp)
            checks['handshake']=key in pongs and key in pings and pongs[key]>pings[key] and any(s['_line']>pings[key] for s in statuses)
        if attention_requests.get(seq):
            item=attention_fragments.get(seq,{});parts=item.get('parts',{});complete=set(parts)=={0,1};uart_attention=False;values=[]
            if complete:
                values=parts[0]+parts[1];raw=struct.pack('<432I',*values)
                if zlib.crc32(raw)!=item['crc']:raise ValueError('ATTENTION full CRC mismatch')
                if any(not (1<<24)-64<=sum(values[i:i+6])<=(1<<24)+64 for i in range(0,432,6)):raise ValueError('ATTENTION Q0.24 row invalid')
                receipts=re.findall(rf'^S2C ATTN {prefix} seq={seq} layers=12 n=6 frac=24 crc32=([0-9a-f]{{8}})$',text,re.M|re.I)
                layers=re.findall(rf'^S2C ATTN_LAYER {prefix} seq={seq} layer=(\d+) crc32=([0-9a-f]{{8}})$',text,re.M|re.I)
                expected_layers=[(l,zlib.crc32(raw[l*144:(l+1)*144])) for l in range(12)]
                uart_attention=len(receipts)==1 and int(receipts[0],16)==item['crc'] and sorted((int(l),int(c,16)) for l,c in layers)==expected_layers
            checks.update(attention_complete=complete,uart_attention=uart_attention)
            attention_checks.append(dict(seq=seq,row=ry,col=rx,scene=probe_scene,wcrc=f'{probe_crc:08x}',complete=complete,
                uart_layers=uart_attention,crc32=f'{item["crc"]:08x}' if item else None,shape=[12,6,6],q24=values,
                passed=complete and uart_attention and all(checks.values())))
        probe_checks.append(dict(seq=seq,row=ry,col=rx,scene=probe_scene,wcrc=f'{probe_crc:08x}',
                                 same_task_model=(probe_scene,probe_crc)==(scene,model_crc),checks=checks,passed=all(checks.values())))
    s3=re.findall(rf'^S2C S3 scope=task {prefix} wait_calls=(\d+) wait_rx=(\d+) max_gap_us=(\d+) max_service_us=(\d+)$',text,re.M|re.I)
    s3_ok=len(s3)==1 and int(s3[0][0])>=int(s3[0][1])>0 and int(s3[0][2])<1000000 and int(s3[0][3])<1000000
    import board_timing
    phase_timing=board_timing.parse_phases(text,session,task,compute_us) if modern else board_timing.unavailable('Legacy task has no phase timing contract')
    phase_timing['identity']=dict(identity,boot_id=f'{boot:08x}',session=f'{session:08x}',task=task)
    if phase_timing['available']:
        calls=next(p['calls'] for p in phase_timing['phases'] if p['part']=='step')
        if calls!=(count//w)*((w+3)//4):raise ValueError('Step timing call count differs from completed row batches')
        import board_engine_timing
        detail=board_engine_timing.parse(text,session,task,count,compute_us,(count//w)*((w+3)//4))
        phase_timing.update(internal_timing=detail,internal_ps_pl_split_available=bool(detail['available']),pure_pl_available=bool(detail['available'] and count))
    result=dict(boot_id=f'{boot:08x}',session=f'{session:08x}',task=task,rect=rect,status=required['status'],identity=identity,phase_timing=phase_timing,release_build=release_build,
                attention=dict(passed=bool(attention_checks) and all(c['passed'] for c in attention_checks),requests=attention_checks,scope='Raw PL ABI4 + UART whole and per-layer CRC; no PC recalculation'),
                received_pixels=count,total=total,crc32=f'{crc:08x}',browser_words_sha256=hashlib.sha256(browser).hexdigest(),
                compute_us=compute_us,timing_scope=wire.TIMING_SCOPE,data_acceptance=True,batch_acceptance=False,
                checks=dict(uart_task_identity=True,uart_udp_crc=True,committed_coverage=True,compute_timing=True,export_exact=True),
                s3=dict(passed=s3_ok,scope='TASK_PUMP_INCLUDING_SETUP_PROBE_AND_WAIT_SERVICE'),probe=dict(passed=bool(probe_checks) and all(p['passed'] for p in probe_checks),points=probe_checks),
                controls_requested=len(controls),recovery_attempts=recovery_count,
                controls=dict(passed=all(g['passed'] for g in groups) if groups else None,groups=groups,uart_receipts=control_checks),
                scope='TASK_ARTIFACTS_ONLY_NOT_FULL_RELEASE_ACCEPTANCE',
                not_covered=['DP visual','all lifecycle/fault cases','model upload/switch','all required attention coordinates/fault cases','SD standalone boot','full first release'])
    if network_log is not None:
        result=board_log.labels(result)
        result.update(log_transport='ethernet',board_log_artifact=str(Path(network_log).resolve()),
            board_log_packets_sha256=hashlib.sha256((Path(network_log)/'packets.jsonl').read_bytes()).hexdigest())
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    source=p.add_mutually_exclusive_group(required=True);source.add_argument('--uart',type=Path);source.add_argument('--network-log',type=Path)
    p.add_argument('--export',type=Path);p.add_argument('--elf-audit',type=Path);p.add_argument('--out',type=Path);args=p.parse_args()
    result=verify(args.directory,args.uart,args.export,args.elf_audit,network_log=args.network_log)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.out:args.out.write_text(text,encoding='utf-8')
    print(text)


if __name__=='__main__':main()
