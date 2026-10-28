"""Read-only post-scene PROBE UART/UDP cross-check; never executes inference."""
import json
import re
import struct
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gcs'))
import board_probe as probe


def verify(run_dir,uart_text):
    path=run_dir/'interaction.json'
    if not path.exists():return dict(passed=False,reason='No recorded probe session',points=[])
    saved=json.loads(path.read_text(encoding='utf-8-sig'))
    info=json.loads((run_dir/'session.json').read_text(encoding='utf-8-sig'))
    if (saved.get('boot_id'),saved.get('session'),saved.get('task'))!=(f'{info["boot_id"]:08x}',f'{info["session"]:08x}',info['task']):
        return dict(passed=False,reason='Probe session identity mismatch',points=[])
    points=saved.get('history',[])+([saved['probe']] if saved.get('probe') else [])
    if not points:return dict(passed=False,reason='No explicit probe completed yet',points=[])
    requests={};replies={};pings={};pongs={};statuses=[]
    with (run_dir/'packets.jsonl').open(encoding='utf-8-sig') as f:
        for line in f:
            packet=json.loads(line)
            if packet.get('phase')!='interaction' or tuple(packet['peer'])!=probe.wire.TARGET:continue
            raw=bytes.fromhex(packet['hex']);t=packet['monotonic_ns']
            if packet['direction']=='tx':
                magic,kind,version,task,seq,stamp=probe.wire.HEADER.unpack_from(raw)
                if (magic,version,task)!=(0x4548,1,info['task']):raise ValueError('Probe TX header/identity')
                if kind==5 and len(raw)==16:
                    if struct.unpack_from('<I',raw,12)[0]!=info['session']:raise ValueError('Probe PING session')
                    pings[seq]=(stamp,t)
                elif kind==9 and len(raw)==24:
                    if seq in requests and requests[seq][0]!=raw:raise ValueError('Conflicting PROBE retry')
                    requests.setdefault(seq,(raw,t))
                else:raise ValueError('Unexpected interaction command')
            elif packet['direction']=='rx':
                decoded=probe.decode(raw)
                if decoded['kind']==0x85:replies.setdefault(decoded['req_seq'],[]).append((decoded,t))
                elif decoded['kind']==0x84:pongs.setdefault(decoded['ping_seq'],[]).append((decoded,t))
                elif decoded['kind']==0x82:statuses.append((decoded,t))
    checked=[]
    for point in points:
        seq=point.get('req_seq');row=point['row'];col=point['col']
        checks=dict(success=point.get('state')=='done',request=False,logits=False,uart_class=False,uart_logits=False,handshake=False)
        if seq in requests:
            raw,t=requests[seq]
            checks['request']=raw[12:]==struct.pack('<BBHHHI',0,0,row,col,0,probe.wire.WCRC)
            receipts=[d for d,at in replies.get(seq,[]) if at>=t]
            checks['logits']=bool(receipts) and all((d['task'],d['row'],d['col'],d['wcrc'],d['class_word'],d['logits_q16'])==(
                info['task'],row,col,probe.wire.WCRC,point.get('class_word'),point.get('logits_q16')) for d in receipts)
            ping=pings.get((seq-1)&65535)
            checks['handshake']=bool(ping) and any(d['task']==info['task'] and d['t1']==ping[0] and at>=ping[1]
                for d,at in pongs.get((seq-1)&65535,[])) and any(at>=ping[1] and
                (d['boot_id'],d['session'],d['task'],d['wcrc'],d['state'])==(info['boot_id'],info['session'],info['task'],probe.wire.WCRC,3)
                for d,at in statuses)
        class_lines=re.findall(r'^S2C PROBE session=([0-9a-f]{8}) task=(\d+) seq='+str(seq)+r' x=(\d+) y=(\d+) class_word=([0-9a-f]{8})\r?$',uart_text,re.M|re.I)
        checks['uart_class']=len(class_lines)==1 and (int(class_lines[0][0],16),int(class_lines[0][1]),int(class_lines[0][2]),int(class_lines[0][3]),class_lines[0][4].upper())==(
            info['session'],info['task'],col,row,point.get('class_word'))
        logit_lines=re.findall(r'^S2C LOGIT seq='+str(seq)+r' class=(\d+) q16=(-?\d+)\r?$',uart_text,re.M)
        checks['uart_logits']=len(logit_lines)==9 and sorted((int(c),int(q)) for c,q in logit_lines)==list(enumerate(point.get('logits_q16',[])))
        checked.append(dict(row=row,col=col,req_seq=seq,checks=checks,passed=all(checks.values())))
    return dict(passed=all(p['passed'] for p in checked),points=checked,scope='RECORDED_PROBES_UART_UDP_ONLY')
