"""Private full-scene subset. Shares verified S2c header/ACK/PONG/STATUS codecs.
No new UDP fields. START mode0 and split ROW use the existing protocol.md layout.
"""
import struct
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import s2c_roi_client as wire
WIDTH,HEIGHT,ROW_MAX=400,550,348
TOTAL=WIDTH*HEIGHT


def start_packet(task,seq,stamp,session):
    return wire.packet(1,task,seq,stamp,struct.pack('<BBBBHHHHII',0,0,0,0,0,0,HEIGHT,WIDTH,wire.WCRC,session))


def decode(data):
    if len(data)<12 or data[2]!=0x81:return wire.decode(data)
    magic,kind,ver,task,seq,stamp=wire.HEADER.unpack_from(data)
    if magic!=0x4548 or ver!=1 or len(data)<20:raise ValueError('ROW header/version')
    y,col,n,flags=struct.unpack_from('<4H',data,12)
    if flags or y>=HEIGHT or not 1<=n<=ROW_MAX or col>=WIDTH or col+n>WIDTH or len(data)!=20+4*n:
        raise ValueError('ROW length/coordinate/flags')
    words=struct.unpack_from(f'<{n}I',data,20)
    if any(w&0xff00 or (w&255)>8 for w in words):raise ValueError('invalid CLASS word')
    return dict(kind=kind,task=task,seq=seq,t_us=stamp,row=y,col=col,words=words)


class Audit(wire.Audit):
    def __init__(self,boot,session,task):
        super().__init__(boot,session,task)
        self.count=0
        self.reported_done=0
        self.counts=[0]*9

    def sent(self,data):
        if len(data)>=12 and data[2]==1:
            if self.start_seq is not None:raise ValueError('second START forbidden')
            if not(self.ready and self.have_pong):raise ValueError('START before identity handshake')
            _,_,_,_,seq,stamp=wire.HEADER.unpack_from(data)
            if data!=start_packet(self.task,seq,stamp,self.session):raise ValueError('unexpected full START')
            self.start_seq=seq
        else:super().sent(data)

    def received(self,data):
        d=decode(data);d['new_cells']=[]
        if d['kind']==0x84:
            if self.pings.get(d['ping_seq'])!=d['t1']:raise ValueError('PONG correlation')
            self.have_pong=True
        elif d['kind']==0x83:
            if self.start_seq is None or (d['task'],d['acked_type'],d['acked_seq'])!=(self.task,1,self.start_seq):
                raise ValueError('ACK correlation mismatch')
            if d['code'] or d['value']:raise ValueError(f"board ACK failure: code={d['code']} value={d['value']:08x}")
            self.ack=True
        elif d['kind']==0x82:
            self.statuses+=1
            if (d['boot_id'],d['session'],d['wcrc'])!=(self.boot,self.session,wire.WCRC):raise ValueError('boot/session/model mismatch')
            if any(d[k] for k in ('tx_fail','tx_retx','rx_bad','rx_gap','rx_dup')):raise ValueError('nonzero error/gap/retry counter')
            if self.start_seq is None:
                if (d['task'],d['state'],d['done'],d['total'],d['front_row'])!=(0,0,0,0,0):raise ValueError('not fresh idle')
                self.ready=True
            elif d['task']==self.task:
                if d['state'] not in (1,3) or d['total']!=TOTAL or not 0<=d['done']<=TOTAL or d['front_row']!=d['done']//WIDTH:
                    raise ValueError('inconsistent full progress')
                self.reported_done=max(self.reported_done,d['done'])
                if d['state']==3:
                    if (d['done'],d['front_row'])!=(TOTAL,HEIGHT):raise ValueError('inconsistent DONE')
                    self.final={k:v for k,v in d.items() if k!='new_cells'}
            elif d['task']!=0:raise ValueError('unexpected STATUS task')
        else:
            if self.start_seq is None or d['task']!=self.task:raise ValueError('unexpected ROW task')
            row=self.rows.setdefault(d['row'],[None]*WIDTH)
            # Validate the ENTIRE segment before committing any new values.
            if any(row[d['col']+i] is not None and row[d['col']+i]!=w for i,w in enumerate(d['words'])):
                raise ValueError('conflicting duplicate ROW')
            repeated=False
            for i,w in enumerate(d['words']):
                x=d['col']+i
                if row[x] is None:
                    row[x]=w;self.count+=1;self.counts[w&255]+=1
                    d['new_cells'].append(dict(x=x,y=d['row'],class_word=f'{w:08X}',class_id=w&255,confidence_q16=w>>16,confidence=(w>>16)/65536))
                else:repeated=True
            if repeated:self.duplicates+=1
        return d

    def complete(self):return self.ack and self.final is not None and self.count==TOTAL
