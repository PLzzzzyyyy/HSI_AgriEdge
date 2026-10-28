"""Read-only Ethernet board records + user-copied journal correlation. Does not operate media.

A correlated file set is NOT evidence that the human really removed debugger,
changed boot mode or power-cycled. Those F3 observations stay separately pending.
"""
from pathlib import Path
import argparse,hashlib,json,re,struct,sys,zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'gcs'))
from board_release import APP_ID,uart_build,expected_build
import board_log
def sha(b):return hashlib.sha256(b).hexdigest()
def record(raw,slot):
    if len(raw)!=64:raise ValueError('Boot record size')
    w=struct.unpack('<16I',raw)
    if (w[0],w[1],w[5],w[8])!=(0x34444942,1,slot,4) or not w[2] or not (w[6]|w[7]) or any(w[9:14]):raise ValueError('Boot record format')
    if w[2]+w[3]>=2**32 or w[4]!=w[2]+w[3] or w[14]!=zlib.crc32(raw[:56]) or w[15]!=(w[14]^0xffffffff):raise ValueError('Boot record integrity')
    return dict(base=w[2],generation=w[3],boot=w[4],nonce=f'{w[7]:08x}{w[6]:08x}',sha256=sha(raw))
def uart_identity(raw):
    text='\n'.join(x.strip('\r') for x in raw.decode('ascii',errors='strict').split('\n'))
    rows=re.findall(r'^S2C IDENTITY source=sd-journal boot_id=([0-9a-f]{8}) generation=([1-9][0-9]*) nonce=([0-9a-f]{16}) abi=4$',text,re.M|re.I)
    ready=re.findall(r'^S2C READY boot_id=([0-9a-f]{8}) registry=(?:[0-9]|[1-3][0-9]|4[0-8]) scan_ok=[01] scenes=3 roi=any banks=1 UDP=5010 app='+APP_ID+'$',text,re.M|re.I)
    if len(rows)!=1 or len(ready)!=1 or ready[0].lower()!=rows[0][0].lower() or 'S2B BOOT_ID:' in text or re.search(r'^S2C (STOP|HALTED)',text,re.M):raise ValueError('SD identity/READY/old prompt/failure gate')
    boot,gen,nonce=rows[0]
    if not int(boot,16) or not int(nonce,16) or not 0<int(gen)<2**32:raise ValueError('Boot fields out of range')
    return dict(boot=int(boot,16),generation=int(gen),nonce=nonce.lower(),uart_sha256=sha(raw),build=uart_build(text))
def network_identity(directory,elf_audit=None):
    directory=Path(directory)
    records=directory/'board_log' if (directory/'board_log').is_dir() else directory
    audit=Path(elf_audit) if elf_audit else directory/'elf_audit.json'
    replay=board_log.audit(records,expected_session=0,expected_task=0)
    startup=board_log.parse_boot(replay['boot_log'],expected_build(audit))
    if startup['state']!='ready' or startup['boot_id']!=replay['boot']:raise ValueError('Board records have no matching healthy READY')
    return dict(boot=replay['boot'],generation=startup['generation'],nonce=startup['nonce'],build=startup['build'],
        transport='ethernet',board_log_sha256=sha(replay['boot_log']),packets_sha256=sha((records/'packets.jsonl').read_bytes()))

def verify(uart=None,journals=None,previous=None,*,network_log=None,previous_network_log=None,elf_audit=None):
    if journals is None:raise ValueError('User-copied journal directory required')
    if network_log is not None:
        if uart is not None or previous is not None:raise ValueError('Ethernet audit never mixes or falls back to UART')
        identity=network_identity(network_log,elf_audit)
        previous_identity=network_identity(previous_network_log) if previous_network_log else None
    else:
        if uart is None or previous_network_log is not None:raise ValueError('Ethernet records or explicit legacy UART files required')
        identity=uart_identity(Path(uart).read_bytes())
        previous_identity=uart_identity(Path(previous).read_bytes()) if previous else None
    pair=[record((Path(journals)/f'jrn{i}.bin').read_bytes(),i) for i in (0,1)]
    if pair[0]['base']!=pair[1]['base'] or pair[0]['nonce']!=pair[1]['nonce'] or abs(pair[0]['generation']-pair[1]['generation'])!=1:raise ValueError('Mixed/torn/nonconsecutive boot journal')
    latest=max(pair,key=lambda r:r['generation'])
    if any(identity[k]!=latest[k] for k in ('boot','generation','nonce')):raise ValueError('Copied SD reservation does not match recorded boot')
    if previous_identity is not None:
        d=identity['generation']-previous_identity['generation']
        if d<=0 or identity['nonce']!=previous_identity['nonce'] or identity['boot']-previous_identity['boot']!=d:raise ValueError('Reused/rewound/mixed boot identity')
    return dict(result='FILE_CORRELATION_PASS',scope='READ_ONLY_USER_PROVIDED_FILES_NOT_PHYSICAL_COLD_BOOT_PROOF',identity=identity,journals=pair,
        previous=previous_identity,independent_cold_start_acceptance=False,
        pending=['User observes SD boot mode, no debugger download, no UART input, real power cycle and DP/READY/task entry'])
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--network-log',type=Path,help='Saved Ethernet startup directory or board-log pages (normal path)')
    source.add_argument('--legacy-uart','--uart',dest='uart',type=Path,help='Explicit offline historical UART replay only')
    previous=p.add_mutually_exclusive_group()
    previous.add_argument('--previous-network-log',type=Path)
    previous.add_argument('--previous-uart',type=Path,help='Legacy-only previous capture')
    p.add_argument('--elf-audit',type=Path);p.add_argument('--journals',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()) or out.exists():raise ValueError('New build/host receipt required')
    r=verify(a.uart,a.journals,a.previous_uart,network_log=a.network_log,previous_network_log=a.previous_network_log,elf_audit=a.elf_audit)
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,indent=2))
