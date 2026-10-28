"""Correlate private App phase timings with raw UART and task identity.

This is NOT an internal PS/PL profiler. The step bucket retains the published
PS-prep + driver/engine-wait + service scope; nested service is never added twice.
No clock/temperature/performance value is manufactured when receipts are absent.
"""
import hashlib
import re
import struct
import board_models

PHASES=('setup','step','probe','results','display','rows','pump','model','control')
LABELS=('输入/模型准备与任务初始化','任务步（含PS准备/引擎等待）','运行中探查与恢复模型',
        '已提交结果/CRC登记','DP更新','前台结果分片/补传','前台网络与定时器','模型命令轮询','行边界控制检查')
SCOPE='APP_FOREGROUND_NONOVERLAP_PHASES; STEP_INCLUDES_PS_PREP_ENGINE_WAIT_CACHE_SERVICE; NOT_INTERNAL_PS_PL_SPLIT_OR_PURE_PL'
U64=(1<<64)-1

def unavailable(reason):
    return dict(available=False,reason=reason,pure_pl_available=False,internal_ps_pl_split_available=False,scope=SCOPE)

def _number(text):
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,19})',text):raise ValueError('Invalid UART timing integer')
    n=int(text)
    if n>U64:raise ValueError('UART timing overflow')
    return n

def parse_phases(text,session,task,compute_us=None):
    text='\n'.join(line.strip('\r') for line in text.split('\n'))
    prefix=rf'session={session:08x} task={task}'
    clocks=re.findall(rf'^S2C TASK_CLOCK {prefix} (.*)$',text,re.M|re.I)
    rows=re.findall(rf'^S2C TASK_PHASE {prefix} (.*)$',text,re.M|re.I)
    if not clocks and not rows:return unavailable('没有该任务的完整板端分项计时记录；不以接收用时回填')
    if len(clocks)!=1:raise ValueError('Missing/duplicate TASK_CLOCK receipt')
    clock=re.fullmatch(r'elapsed_us=(\d+) accounted_us=(\d+) other_us=(\d+) valid=([01])',clocks[0])
    if not clock:raise ValueError('Invalid TASK_CLOCK format')
    elapsed,accounted,other,valid=map(_number,clock.groups())
    if not valid:return unavailable('板端计时器报告无效；不显示部分累计值为完整测量')
    phases={}
    for row in rows:
        match=re.fullmatch(r'part=([a-z_]+) calls=(\d+) us=(\d+)',row)
        if not match or match[1] not in (*PHASES,'wait_service'):raise ValueError('Unknown TASK_PHASE receipt')
        name=match[1]
        if name in phases:raise ValueError('Duplicate TASK_PHASE receipt')
        calls,us=map(_number,match.groups()[1:])
        if not calls and us:raise ValueError('Timing value without calls')
        phases[name]=dict(part=name,calls=calls,us=us)
    if set(phases)!={*PHASES,'wait_service'}:raise ValueError('Incomplete phase timing receipt')
    if sum(phases[p]['us'] for p in PHASES)!=accounted or accounted+other!=elapsed or accounted>U64:
        raise ValueError('Phase timing sum mismatch')
    nested=phases['wait_service']
    if nested['us']>sum(phases[p]['us'] for p in ('setup','step','probe','model','pump')):
        raise ValueError('Nested wait service exceeds parent phases')
    if compute_us is not None and phases['step']['us']!=compute_us:raise ValueError('Step phase differs from compute_us')
    return dict(available=True,elapsed_us=elapsed,accounted_us=accounted,other_us=other,
        phases=[dict(phases[p],label=label) for p,label in zip(PHASES,LABELS)],wait_service=nested,
        pure_pl_available=False,internal_ps_pl_split_available=False,scope=SCOPE,
        notes=['分项按私有App墙钟统计，包含测量代码开销；不是纯PL或内部PS数值时间。',
               '等待服务是setup/step/probe等分项内部的子集，不与分项相加。',
               '其余时间包括未埋点调度、日志、暂停/空闲；不能全部称为PS或全部称为空闲。',
               '终态之后的PROBE/补传不属于已冻结的任务时间；LOAD_W/SD在setup，不混入计算px/s。'])

def from_snapshot(snapshot,text):
    if not snapshot.get('model_lifecycle'):return unavailable('旧版任务没有此分项计时契约')
    identity=board_models.task_identity(snapshot)
    if snapshot.get('status') not in ('done','stopped') or snapshot.get('error') or snapshot.get('integrity_error'):
        return unavailable('任务尚未健康结束；不把部分分项显示为完整测量')
    boot,session,task=int(snapshot['boot_id'],16),int(snapshot['session'],16),snapshot['task']
    normalized='\n'.join(line.strip('\r') for line in text.split('\n'))
    from board_release import READY_APPS,APP_ID,uart_build
    ready=re.findall(r'^S2C READY boot_id=([0-9a-f]{8}) registry=(?:[0-9]|[1-3][0-9]|4[0-8]) scan_ok=[01] scenes=3 roi=any banks=1 UDP=5010 app='+READY_APPS+'$',normalized,re.M|re.I)
    if 'app='+APP_ID in normalized.lower():
        if not re.search(r'^S2C READY .* app='+APP_ID+'$',normalized,re.M|re.I):raise ValueError('Mixed current BUILD and old READY')
        uart_build(normalized)
    if len(ready)!=1 or int(ready[0],16)!=boot:raise ValueError('Timing UART boot identity mismatch')
    roi=snapshot['roi'];scene=board_models.SCENES.index(identity['scene'])
    begin=(rf'^S2C TASK_BEGIN session={session:08x} task={task} scene={scene} model={re.escape(identity["model"])} wcrc={identity["wcrc"]}'
           rf' x={roi["x"]} y={roi["y"]} w={roi["width"]} h={roi["height"]} classes={identity["classes"]}$')
    if len(re.findall(begin,normalized,re.M|re.I))!=1:raise ValueError('Timing task/model identity mismatch')
    terminal='DONE' if snapshot['status']=='done' else 'STOP'
    ends=re.findall(rf'^S2C TASK_{terminal} session={session:08x} task={task} completed=(\d+) compute_us=(\d+) crc32=([0-9a-f]{{8}})$',normalized,re.M|re.I)
    if len(ends)!=1:raise ValueError('Timing task terminal receipt missing/duplicate')
    count,compute=map(_number,ends[0][:2])
    if count!=snapshot['received_pixels']:raise ValueError('Timing committed pixel count mismatch')
    if count:
        ms=(snapshot.get('performance') or {}).get('ms_per_pixel')
        if ms is None or struct.pack('<f',ms)!=struct.pack('<f',compute/1000/count):raise ValueError('Timing UART/STATUS compute mismatch')
    elif compute:raise ValueError('Compute timing without committed pixels')
    result=parse_phases(normalized,session,task,compute)
    if result['available']:
        calls=next(p['calls'] for p in result['phases'] if p['part']=='step')
        expected_calls=(count//roi['width'])*((roi['width']+3)//4)
        if count%roi['width'] or calls!=expected_calls:raise ValueError('Step call count differs from completed row batches')
        import board_engine_timing
        detail=board_engine_timing.parse(normalized,session,task,count,compute,expected_calls)
        result['internal_timing']=detail
        result['internal_ps_pl_split_available']=bool(detail['available'])
        result['pure_pl_available']=bool(detail['available'] and count)
    result.update(identity={**identity,**{k:snapshot[k] for k in ('boot_id','session','task')}},source='BOARD_UART_PRIVATE_APP_CLOCK',
                  uart_text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
    return result

def from_network(snapshot,directory):
    """Same numerical checks, backed by replayed Ethernet pages rather than UART."""
    import board_log
    from pathlib import Path
    from board_release import expected_build
    boot,session,task=int(snapshot['boot_id'],16),int(snapshot['session'],16),snapshot['task']
    data=board_log.audit(directory,boot,session,task)
    board_log.parse_boot(data['boot_log'],expected_build(Path(directory)/'elf_audit.json'))
    try:result=from_snapshot(snapshot,data['board_log'].decode('ascii'))
    except ValueError as exc:raise ValueError(str(exc).replace('UART','board log')) from exc
    result=board_log.labels(result)
    result.update(transport='ethernet',board_log_evidence=str(Path(directory).resolve()),
        board_log_packets_sha256=hashlib.sha256((Path(directory)/'packets.jsonl').read_bytes()).hexdigest())
    return result
