"""Raw PL ABI4 attention transport. No model, logits conversion or inference."""
import struct,zlib
import board_models as models
HEADER=struct.Struct('<HBBHHI')
META=struct.Struct('<HBBHHIIIIHBBHHBBBB')
WORDS=432;FRAGMENT_WORDS=216

def decode(data):
    if len(data)!=912:raise ValueError('ATTENTION fragment length')
    magic,kind,ver,task,seq,stamp=HEADER.unpack_from(data)
    if (magic,kind,ver)!=(0x4548,0x87,1):raise ValueError('ATTENTION header')
    req,scene,ncls,row,col,wcrc,boot,session,crc,total,index,parts,offset,count,layers,n,frac,pad=META.unpack_from(data,12)
    spec=models.scene_spec(scene)
    if not boot or not session or not task or not wcrc or ncls!=spec['classes'] or row>=spec['shape'][0] or col>=spec['shape'][1]:
        raise ValueError('ATTENTION identity/shape')
    if (total,parts,count,layers,n,frac,pad)!=(432,2,216,12,6,24,0) or index not in (0,1) or offset!=index*216:
        raise ValueError('ATTENTION layout/offset')
    words=list(struct.unpack_from('<216I',data,48))
    if any(w>1<<24 for w in words):raise ValueError('ATTENTION not Q0.24')
    return dict(kind=kind,task=task,seq=seq,t_us=stamp,req_seq=req,scene=scene,ncls=ncls,row=row,col=col,
        wcrc=wcrc,boot_id=boot,session=session,crc32=crc,fragment=index,words=words)

def accept(probe,d,audit):
    if not probe.get('attention_requested'):raise ValueError('Unrequested attention reply')
    identity=probe.get('identity',audit.identity)
    expected=(audit.boot,audit.session,audit.task,probe['req_seq'],models.SCENES.index(identity['scene']),
              identity['classes'],probe['row'],probe['col'],int(identity['wcrc'],16))
    actual=tuple(d[k] for k in ('boot_id','session','task','req_seq','scene','ncls','row','col','wcrc'))
    if actual!=expected:raise ValueError('ATTENTION boot/session/task/request/model/coordinate mismatch')
    previous=probe.get('_attention_crc')
    if previous is not None and previous!=d['crc32']:raise ValueError('ATTENTION conflicting tensor CRC')
    probe['_attention_crc']=d['crc32'];parts=probe.setdefault('_attention_fragments',{});key=str(d['fragment'])
    if key in parts and parts[key]!=d['words']:raise ValueError('ATTENTION conflicting duplicate fragment')
    parts[key]=list(d['words'])
    if len(parts)!=2:return
    words=parts['0']+parts['1'];raw=struct.pack('<432I',*words)
    if zlib.crc32(raw)!=d['crc32']:raise ValueError('ATTENTION whole tensor CRC mismatch')
    if any(not (1<<24)-64<=sum(words[i:i+6])<=(1<<24)+64 for i in range(0,432,6)):
        raise ValueError('ATTENTION malformed softmax row')
    probe.update(attention_q24=words,attention_shape=[12,6,6],attention_crc32=f'{d["crc32"]:08x}',
                 attention_source='PL ABI4 Q0.24; exact softmax matrix used by CTX; no PC recomputation')

def clear(probe):
    for key in ('attention_q24','attention_shape','attention_crc32','_attention_fragments','_attention_crc'):
        probe.pop(key,None)
    probe['attention_source']='unavailable: incomplete/failed, no stale tensor'
