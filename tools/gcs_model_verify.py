"""Independent v1 model receipt audit, not a deployment or SD-reboot test.

Rebuilds from raw TX/RX and saved package bytes; never trusts summary success.
No socket, serial, model inference, training or hardware access.
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
import board_task as t
import board_models as m
import board_log

def verify(directory,uart=None,*,network_log=None,elf_audit=None):
    directory=Path(directory);meta=json.loads((directory/'session.json').read_text(encoding='utf-8'))
    if meta.get('scope')!='MODEL_TRANSACTION' or tuple(meta.get('target',()))!=t.wire.TARGET:raise ValueError('Not a board model transaction')
    boot,session=meta['boot_id'],meta['session'];action=meta['action'];candidate=meta.get('candidate')
    if type(boot) is not int or type(session) is not int or not 0<boot<2**32 or not 0<session<2**32 or action not in ('query','upload','activate'):
        raise ValueError('Invalid model transaction identity')
    network_required=bool(meta.get('network_startup'))
    if uart is not None and (network_log is not None or network_required):raise ValueError('Ethernet model audit cannot fall back to UART')
    if network_log is None and uart is None:network_log=board_log.latest(directory,boot,session,0)
    parts=[];scene=None
    if action!='query':
        identity=m.candidate_identity(candidate);scene=m.SCENES.index(identity['scene'])
        descriptors=candidate['parts']
        if [p['kind'] for p in descriptors]!=[0,1]:raise ValueError('Companion/engine descriptors missing')
        if action=='upload':
            for kind,part in enumerate(descriptors):
                raw=(directory/f'kind{kind}.bin').read_bytes()
                if (len(raw),f'{zlib.crc32(raw):08x}',hashlib.sha256(raw).hexdigest())!=(part['bytes'],part['crc32'],part['sha256']):
                    raise ValueError('Saved package SHA/CRC/size mismatch')
                parts.append(raw)
            m.validate_pair(candidate['scene'],*parts)
    requests={};commit=[None,None];activation=None;info=None;last_info_request=None;errors=[];acks=[];ranges=[set(),set()];infos=[]
    for number,line in enumerate((directory/'packets.jsonl').read_text(encoding='utf-8').splitlines(keepends=True),1):
        if not line.endswith('\n'):raise ValueError('Truncated model journal')
        rec=json.loads(line)
        if tuple(rec.get('peer',()))!=t.wire.TARGET:raise ValueError('Model peer mismatch')
        raw=bytes.fromhex(rec['hex'])
        if len(raw)<12:raise ValueError('Truncated model packet')
        magic,kind,version,task,seq,stamp=t.wire.HEADER.unpack_from(raw)
        if magic!=0x4548 or version!=1:raise ValueError('Model packet header')
        if rec['direction']=='tx':
            if kind==5:
                if raw[12:]!=struct.pack('<I',session):raise ValueError('Model PING session mismatch')
            elif kind==7:
                if len(raw)!=12:raise ValueError('INFO length')
                last_info_request=number
            elif kind in (m.WBEGIN,m.WCHUNK,m.WCOMMIT,m.WACT):
                if not candidate:raise ValueError('Mutation inside read-only query')
                if kind==m.WBEGIN:
                    if len(raw)!=40:raise ValueError('WBEGIN size')
                    sc,k,pad,total,crc,tag=m.BEGIN.unpack_from(raw,12)
                    if k>1 or sc!=scene or pad or m.decode_tag(tag)!=candidate['tag'] or (total,f'{crc:08x}')!=(descriptors[k]['bytes'],descriptors[k]['crc32']):
                        raise ValueError('WBEGIN identity mismatch')
                    role=k
                elif kind==m.WCHUNK:
                    if not 28<len(raw)<=1412 or not parts:raise ValueError('WCHUNK length / unavailable local bytes')
                    sc,k,pad,off,total,crc=m.CHUNK.unpack_from(raw,12)
                    if k>1 or sc!=scene or pad or (total,f'{crc:08x}')!=(descriptors[k]['bytes'],descriptors[k]['crc32']) or off+len(raw)-28>total or raw[28:]!=parts[k][off:off+len(raw)-28]:
                        raise ValueError('WCHUNK bytes/identity mismatch')
                    role=k;ranges[k].add((off,off+len(raw)-28))
                elif kind==m.WCOMMIT:
                    if len(raw)!=16:raise ValueError('WCOMMIT size')
                    crc=struct.unpack_from('<I',raw,12)[0];matches=[k for k,p in enumerate(descriptors) if p['crc32']==f'{crc:08x}']
                    if len(matches)!=1:raise ValueError('Unknown/ambiguous WCOMMIT CRC')
                    role=matches[0]
                else:
                    if len(raw)!=20:raise ValueError('WACT size')
                    sc,when,pad,crc=m.ACT.unpack_from(raw,12)
                    if (sc,when,pad,f'{crc:08x}')!=(scene,0,0,candidate['wcrc']):raise ValueError('Unsafe/incorrect activation')
                    role=1
                previous=requests.get(seq)
                if previous and previous['body']!=raw[12:]:
                    # Global seq may wrap during long deferred persistence.
                    # A newly transmitted command becomes the only ACK owner.
                    requests.pop(seq)
                requests[seq]=dict(type=kind,body=raw[12:],role=role,task=task,line=number,crc=crc)
            continue
        if rec['direction']!='rx':raise ValueError('Unknown model journal direction')
        d=t.decode(raw)
        if kind in (0x82,0x86):
            if d['boot_id']!=boot or kind==0x82 and d['session']!=session or d['task'] and d['session']!=session:
                raise ValueError('Model boot/session mismatch')
        if kind==0x86:
            if last_info_request is None:raise ValueError('Unsolicited model INFO')
            info=d;infos.append(d)
        if kind!=0x83 or d['acked_type'] not in (m.WBEGIN,m.WCHUNK,m.WCOMMIT,m.WACT):continue
        request=requests.get(d['acked_seq'])
        if not request or request['type']!=d['acked_type'] or request['task']!=d['task']:raise ValueError('Unmatched model ACK')
        code,value=d['code'],d['value'];typ=request['type'];role=request['role']
        if code>9:raise ValueError('Unknown model ACK code')
        receipt=dict(type=typ,seq=d['acked_seq'],crc=request['crc'],code=code,value=value,kind=role)
        acks.append(receipt)
        if code:
            if code==2 and typ==m.WCHUNK and value<=descriptors[role]['bytes']:continue
            errors.append(receipt);continue
        if typ==m.WBEGIN and value>descriptors[role]['bytes']:raise ValueError('WBEGIN offset exceeds bytes')
        if typ==m.WCHUNK and value!=struct.unpack_from('<I',request['body'],4)[0]+len(request['body'])-16:raise ValueError('WCHUNK ACK count mismatch')
        if typ==m.WCOMMIT:
            if value&~1:raise ValueError('Commit reserved bits')
            commit[role]=receipt
        if typ==m.WACT:
            if value:raise ValueError('Single-bank activation cannot claim a live row split')
            activation=receipt
    registered=bool(info and candidate and m.registered(candidate,info['entries']))
    persisted=all(r is not None and r['value']==1 for r in commit)
    want_activation=action=='activate' or meta.get('activate') is True
    packet_ok=not errors and info is not None and (action=='query' or registered and (action!='upload' or persisted) and (not want_activation or activation is not None))
    uart_ok=None;build=None;text=None
    from board_release import READY_APPS,APP_ID,uart_build,expected_build
    if network_log is not None:
        replay=board_log.audit(network_log,boot,session,0)
        build=expected_build(elf_audit or Path(network_log)/'elf_audit.json')
        startup=board_log.parse_boot(replay['boot_log'],build)
        if startup['state']!='ready' or startup['boot_id']!=boot:raise ValueError('No healthy model-session startup records')
        if meta.get('release_id')!=build['release_id']:raise ValueError('Model transaction release differs from board records / ELF')
        if any(d.get('engine_abi')!=4 or d.get('release_tag')!=build['release_id'][:32] for d in infos):
            raise ValueError('Model INFO differs from board-record release')
        text=replay['board_log'].decode('ascii')
    elif uart is not None:
        text=Path(uart).read_text(encoding='utf-8-sig')
    if text is not None:
        text='\n'.join(line.strip('\r') for line in text.split('\n'))
        ready=re.findall(r'^S2C READY boot_id=([0-9a-f]{8}) registry=(?:[0-9]|[1-3][0-9]|4[0-8]) scan_ok=[01] scenes=3 roi=any banks=1 UDP=5010 app='+READY_APPS+'$',text,re.M|re.I)
        if 'app='+APP_ID in text.lower():
            if not re.search(r'^S2C READY .* app='+APP_ID+'$',text,re.M|re.I):raise ValueError('Mixed current BUILD and old READY')
            uart_build(text,build or expected_build(elf_audit or Path(uart).parent/'elf_audit.json'))
        uart_ok=len(ready)==1 and int(ready[0],16)==boot and not re.search(r'^S2C (STOP|HALTED)',text,re.M)
        needed=[r for r in commit if r and r['value']==1]+([activation] if activation else [])
        for r in needed:
            rows=re.findall(rf'^S2C MODELCMD session={session:08x} type={r["type"]} seq={r["seq"]} code={r["code"]} value={r["value"]:08x} crc={r["crc"]:08x} active_scene=(-?\d+) active_crc=([0-9a-f]{{8}}) sd_rc=(-?\d+)$',text,re.M|re.I)
            uart_ok=bool(uart_ok and rows and all(int(rc)==0 for _,_,rc in rows))
            if r['type']==m.WACT:uart_ok=uart_ok and any(int(sc)==scene and crc.lower()==candidate['wcrc'] for sc,crc,_ in rows)
    result=dict(boot_id=f'{boot:08x}',session=f'{session:08x}',action=action,scene=candidate['scene'] if candidate else None,
        model=candidate['tag'] if candidate else None,wcrc=candidate['wcrc'] if candidate else None,registered=registered,
        persisted_parts=[bool(r and r['value']==1) for r in commit] if action=='upload' else None,
        activated=activation is not None,packet_checks_passed=packet_ok,uart_confirmed=uart_ok,
        data_acceptance=packet_ok and uart_ok is True,acks=acks,errors=errors,transmitted_ranges=[sorted(s) for s in ranges],
        scope='MODEL_TX_RX_PACKAGE_AND_OPTIONAL_UART_CORRELATION_ONLY_NOT_SD_REBOOT_TASK_OR_RELEASE_ACCEPTANCE',
        not_covered=['SD files after power cycle','new model numeric task result','DP visual','12-layer attention','independent boot','full first release'])
    if network_log is not None or network_required:
        result=board_log.labels(result)
        result.update(log_transport='ethernet',board_log_artifact=str(Path(network_log).resolve()) if network_log else None,
            scope='MODEL_TX_RX_PACKAGE_ETHERNET_RECORDS_ELF_ONLY_NOT_SD_REBOOT_TASK_OR_RELEASE_ACCEPTANCE',release_build=build)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    source=p.add_mutually_exclusive_group()
    source.add_argument('--network-log',type=Path,help='CRC-replayed Ethernet model-session pages; defaults to newest saved read')
    source.add_argument('--legacy-uart','--uart',dest='uart',type=Path,help='Explicit offline historical UART audit only')
    p.add_argument('--elf-audit',type=Path);p.add_argument('--out',type=Path)
    args=p.parse_args();result=verify(args.directory,args.uart,network_log=args.network_log,elf_audit=args.elf_audit);text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.out:args.out.write_text(text+'\n',encoding='utf-8')
    print(text)

if __name__=='__main__':main()
