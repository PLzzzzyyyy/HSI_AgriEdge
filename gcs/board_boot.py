"""Explicit SD-startup discovery via INFO only. Import/GET stays passive.

INFO does not claim a task peer. This socket is closed before the sole model/
task owner starts; no PING/START/RESUME, UART, reset or inference here.
"""
from datetime import datetime
from pathlib import Path
import json,os,re,socket,time
import board_task as task
import board_log

def connect(root,target,confirmed,method,expected,build_receipt=None):
    """Explicit JTAG or SD operator-started App discovery, without UART.

    Full BUILD + SD reservation + READY come from actual CRC-checked board
    records. INFO reconciles the live idle registry. Neither proves power cycle.
    """
    if confirmed is not True:raise ValueError('Confirm that you started the App and it has no task')
    if method not in ('jtag','sd'):raise ValueError('Declare JTAG or SD startup truthfully')
    if tuple(target)!=task.wire.TARGET:raise ValueError('Unexpected board endpoint')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    out=root/datetime.now().strftime('network_start_%Y%m%d_%H%M%S_%f');out.mkdir()
    result=dict(result='FAIL',scope='EXPLICIT_ETHERNET_STARTUP_NOT_COLD_BOOT_PROOF',operator_boot_method=method,
        target=list(target),uart_opened=False,task_started=False,independent_cold_start_verified=False,evidence=str(out.resolve()))
    try:
        if build_receipt is not None:(out/'elf_audit.json').write_bytes(Path(build_receipt).read_bytes())
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.bind(('',0));sock.settimeout(.2)
            board_log.fetch(sock,target,out/'board_log',expected_build=expected)
            replay=board_log.audit(out/'board_log')
            startup=board_log.parse_boot(replay['boot_log'],expected)
            if startup['boot_id']!=replay['boot']:raise ValueError('Packet/record boot identity mismatch')
            boot=startup['boot_id']
            if boot in (*task.legacy.OLD_BOOTS,0xbb6bd8e3):raise ValueError('Old boot cannot be reused')
            result.update(boot_id=f'{boot:08x}',release_id=expected['release_id'],startup=startup,
                          board_log_evidence=str((out/'board_log').resolve()))
            if startup['state']!='ready':
                result.update(result='STARTUP_ERROR' if startup['state']=='error' else 'STARTUP_PENDING',ready=False)
                return result
            with (out/'info_packets.jsonl').open('x',encoding='utf-8') as trace:
                def record(direction,raw,peer):
                    trace.write(json.dumps(dict(direction=direction,peer=list(peer),monotonic_ns=time.perf_counter_ns(),hex=raw.hex()))+'\n');trace.flush()
                raw=task.wire.packet(7,0,0,0,b'');deadline=time.monotonic()+3;next_send=0.;attempts=0
                while time.monotonic()<deadline:
                    if time.monotonic()>=next_send and attempts<3:
                        record('tx',raw,target)
                        if sock.sendto(raw,target)!=len(raw):raise OSError('Short INFO send')
                        attempts+=1;next_send=time.monotonic()+.8
                    try:data,peer=sock.recvfrom(2048)
                    except socket.timeout:continue
                    if tuple(peer)!=tuple(target):continue
                    record('rx',data,peer)
                    if len(data)>2 and data[2]==board_log.REPLY:continue # late read-only page, not an INFO
                    info=task.decode(data)
                    if info['kind']!=0x86 or info.get('engine_abi')!=4 or info.get('release_tag')!=expected['release_id'][:32]:
                        raise ValueError('Current ABI4 reviewed-release INFO required')
                    terminal=info.get('terminal_owned',False)
                    if terminal and info['state'] not in (0,3):
                        raise ValueError('终端任务正在运行，请等待完成或长按按键切景后再连接')
                    if info['boot_id']!=boot or (not terminal and any(info[k] for k in ('task','session','state','front_row'))):
                        raise ValueError('Board is not the observed fresh idle boot; do not take over a task')
                    if len(info['entries'])!=startup['registry_count']:raise ValueError('READY/INFO registry count differs')
                    result.update(result='NETWORK_IDENTITY_READY',ready=True,info=info,terminal_reconnect=terminal,identity_source='BOARD_ETHERNET_FULL_BUILD_AND_SD_JOURNAL')
                    return result
                raise TimeoutError('No matching live idle INFO after board-log READY')
    except Exception as exc:result['error']=str(exc);raise
    finally:(out/'discovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def discover(root,target,confirmed,release_id=None):
    if confirmed is not True:raise ValueError('Confirm user SD startup and idle board before INFO discovery')
    if tuple(target)!=task.wire.TARGET:raise ValueError('Unexpected board endpoint')
    if not isinstance(release_id,str) or not re.fullmatch('[0-9a-f]{64}',release_id):raise ValueError('Reviewed release identity required before INFO discovery')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    out=root/datetime.now().strftime('sd_discovery_%Y%m%d_%H%M%S_%f');out.mkdir()
    result=dict(scope='EXPLICIT_INFO_ONLY_NOT_COLD_BOOT_PROOF',result='FAIL',target=list(target),uart_opened=False,task_started=False)
    try:
        with (out/'packets.jsonl').open('x',encoding='utf-8') as trace,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            def record(direction,raw,peer):
                trace.write(json.dumps(dict(direction=direction,monotonic_ns=time.perf_counter_ns(),peer=list(peer),hex=raw.hex()))+'\n');trace.flush();os.fsync(trace.fileno())
            sock.bind(('',0));sock.settimeout(.2);deadline=time.monotonic()+3;next_send=0;attempts=0
            raw=task.wire.packet(7,0,0,0,b'')
            while time.monotonic()<deadline:
                if time.monotonic()>=next_send and attempts<3:
                    record('tx',raw,target)
                    if sock.sendto(raw,target)!=len(raw):raise OSError('Short INFO send')
                    attempts+=1;next_send=time.monotonic()+.8
                try:data,peer=sock.recvfrom(2048)
                except socket.timeout:continue
                record('rx',data,peer)
                if tuple(peer)!=tuple(target):continue
                d=task.decode(data)
                if d['kind']!=0x86 or d.get('engine_abi')!=4:raise ValueError('Require current ABI4 INFO, not old App/fault ACK')
                if d['release_tag']!=release_id[:32]:raise ValueError('INFO belongs to another App/source/XSA release')
                if d['task'] or d['session'] or d['state'] or d['front_row']:raise ValueError('Board is not a fresh idle startup; explicit task recovery required')
                boot=d['boot_id']
                if not boot or boot in (*task.legacy.OLD_BOOTS,0xbb6bd8e3):raise ValueError('Old/invalid boot cannot be reused')
                result.update(result='INFO_IDENTITY_OBSERVED',identity_source='ABI4_SD_JOURNAL_APP_INFO',boot_id=f'{boot:08x}',info=d,
                    evidence=str(out.resolve()),release_id=release_id,independent_cold_start_verified=False)
                return result
            raise TimeoutError('No valid new ABI4 INFO; no fallback or task sent')
    except Exception as exc:
        result['error']=str(exc);raise
    finally:(out/'discovery.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
