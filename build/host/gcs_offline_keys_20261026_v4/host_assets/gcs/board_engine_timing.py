"""Verify recorded PS subphases and real ABI4 counter, not elapsed-time proxies."""
import re
PARTS=('validate','extract','normalize','embed','cache_prepare','submit','wait','cache_complete')
LABELS=('PS validation','PS window extraction','PS patch normalization','PS embedding/quantization',
        'Driver cache preparation','Driver register/start submission','Engine wait (includes service)','Driver cache completion')
U64=(1<<64)-1
def number(text):
    if not re.fullmatch(r'0|[1-9][0-9]{0,19}',text) or int(text)>U64:raise ValueError('Invalid internal timing integer')
    return int(text)
def parse(text,session,task,pixels,step_us,batches):
    prefix=rf'session={session:08x} task={task}'
    rows=re.findall(rf'^S2C TASK_DETAIL {prefix} (.*)$',text,re.M|re.I)
    engines=re.findall(rf'^S2C TASK_ENGINE {prefix} (.*)$',text,re.M|re.I)
    if not rows and not engines:return dict(available=False,reason='No PS/driver/RTL timing receipts; not measured')
    if len(engines)!=1:raise ValueError('Missing/duplicate hardware counter record')
    m=re.fullmatch(r'pixels=(\d+) calls=(\d+) cycles=(\d+) hz=(\d+) valid=([01])',engines[0])
    if not m:raise ValueError('Invalid TASK_ENGINE layout')
    count,calls,cycles,hz,valid=map(number,m.groups())
    if not valid:return dict(available=False,reason='Board reported invalid internal timing')
    if count!=pixels or calls!=batches or hz!=199998000:raise ValueError('Engine pixels/calls/frequency mismatch')
    if (calls and not calls<=cycles<calls*0xffffffff) or (not calls and cycles):raise ValueError('Invalid/overflow/missing PL counter')
    parts={}
    for row in rows:
        m=re.fullmatch(r'part=([a-z_]+) calls=(\d+) us=(\d+)',row)
        if not m or m[1] not in (*PARTS,'wait_service') or m[1] in parts:raise ValueError('Invalid/duplicate internal phase')
        n,us=map(number,m.groups()[1:])
        if not n and us:raise ValueError('Internal duration without calls')
        parts[m[1]]=dict(part=m[1],calls=n,us=us)
    if set(parts)!={*PARTS,'wait_service'}:raise ValueError('Incomplete internal phases')
    for key in ('extract','normalize','embed'):
        if parts[key]['calls']!=count:raise ValueError('Numeric calls differ from committed pixels')
    for key in ('cache_prepare','wait','cache_complete'):
        if parts[key]['calls']!=calls:raise ValueError('Driver calls differ from completed batches')
    if parts['submit']['calls']!=calls*2:raise ValueError('Register + start submission boundaries missing')
    if count and parts['validate']['calls']<2*count+calls:raise ValueError('Numeric validation scope missing')
    subtotal=sum(parts[k]['us'] for k in PARTS)
    if subtotal>step_us or parts['wait_service']['us']>parts['wait']['us']:raise ValueError('Overlapping/excess internal timing')
    pl_us=cycles*1000000/hz
    if pl_us>parts['submit']['us']+parts['wait']['us']+2:raise ValueError('PL counter exceeds enclosing PS invocation interval')
    return dict(available=True,source='BOARD_UART_PS_DRIVER_AND_RTL_COUNTER',scope='TASK_STEP_ONLY; LOAD_W/SD/PROBE/pause/foreground excluded',
        phases=[dict(parts[k],label=label) for k,label in zip(PARTS,LABELS)],wait_service=parts['wait_service'],
        accounted_us=subtotal,other_step_us=step_us-subtotal,
        engine=dict(cycles=cycles,hz=hz,calls=calls,pixels=count,us=pl_us,
            ms_per_pixel=pl_us/1000/count if count else None,cycles_per_pixel=cycles/count if count else None,
            scope='PL accepted ap_start to ap_done, includes PL AXI/memory stalls, excludes PS; batch average per pixel',
            frequency_source='PS configured ref 33333000 * RPLL48 /2 /4, driver checks live CRL settings; nominal 200MHz, not oscillator measurement'),
        notes=['Wait service is a subset of wait. Do not add it twice.',
               'PL cycles run inside submit/wait; do not add PL us to PS wall-clock phases.',
               'Other step time is uninstrumented bookkeeping/measurement overhead, not pure idle or PL.'])
