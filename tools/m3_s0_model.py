"""S0 analytical event model, NOT HLS/RTL or board simulation; stdlib only."""
from dataclasses import dataclass, field
from collections import defaultdict
import argparse
import heapq
import json
import math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'report/m3_s0/inputs.json'

@dataclass
class Event:
    name: str
    duration: int
    deps: tuple = ()
    resources: dict = field(default_factory=dict)
    acquire: str = ''
    release: str = ''
    owner: str = ''

def schedule(events, capacities, slots=None):
    """FIFO-ready nonpreemptive list schedule; leases last until consumption."""
    slots = slots or {}
    by_name = {e.name: e for e in events}
    if len(by_name) != len(events):
        raise ValueError('duplicate event')
    followers, pending = defaultdict(list), {}
    for e in events:
        if e.duration < 0 or len(set(e.deps)) != len(e.deps):
            raise ValueError(e.name)
        for r, q in e.resources.items():
            if q < 0 or q > capacities.get(r, 0):
                raise ValueError((e.name, r, q))
        for d in e.deps:
            if d not in by_name:
                raise ValueError(('missing dependency', d))
            followers[d].append(e.name)
        pending[e.name] = len(e.deps)
    ready = [e.name for e in events if not e.deps]
    running, held = [], defaultdict(set)
    used, busy, times = defaultdict(int), defaultdict(int), {}
    ready_at = {name: 0 for name in ready}
    now = sequence = 0
    while ready or running:
        for name in ready[:]:
            e = by_name[name]
            if any(used[r]+q > capacities[r] for r,q in e.resources.items()):
                continue
            if e.acquire and len(held[e.acquire]) >= slots[e.acquire]:
                continue
            if e.release and e.owner not in held[e.release]:
                raise RuntimeError(('release without producer', name))
            if e.acquire:
                held[e.acquire].add(e.owner)
            for r,q in e.resources.items():
                used[r] += q
                busy[r] += q*e.duration
            times[name] = (now, now+e.duration)
            heapq.heappush(running, (now+e.duration, sequence, name))
            sequence += 1
            ready.remove(name)
        if not running:
            raise RuntimeError(('resource/lease deadlock', ready))
        now = running[0][0]
        finished = []
        while running and running[0][0] == now:
            _,_,name = heapq.heappop(running)
            e = by_name[name]
            for r,q in e.resources.items():
                used[r] -= q
            if e.release:
                held[e.release].remove(e.owner)
            finished.append(name)
        for name in finished:
            for f in followers[name]:
                pending[f] -= 1
                if pending[f] == 0:
                    ready.append(f)
                    ready_at[f] = now
    if len(times) != len(events) or any(held.values()):
        raise RuntimeError('dependency cycle or leaked buffer')
    return dict(cycles=now, times=times,
                utilization={r:v/(now*capacities[r]) for r,v in sorted(busy.items())},
                waiting={n:times[n][0]-ready_at[n] for n in times})

def bram18(depth, width):
    """RAMB18 true-dual-port aspect ratios; parity bits included."""
    return min(math.ceil(depth/d)*math.ceil(width/w)
               for d,w in [(16384,1),(8192,2),(4096,4),(2048,9),(1024,18)])

def projection_cycles(lanes):
    # Existing HLS: m1/m2 378+7; m3 7*54 + 54 drain + 11.
    # Six tokens: first fill + five II + outer control. Reproduces 3437 at K7.
    # At K14, ceil(7/2) groups and the last 54-cycle drain DO NOT halve.
    m1 = m2 = math.ceil(378/lanes)+7
    m3 = math.ceil(7/lanes)*54+54+11
    return m1+m2+m3+2+5*(max(m1,m2,m3)+1)+2

def memory_budget(width, p, layout='depth', ob_slots=1):
    if width not in (8,16) or p not in (1,2,3) or layout not in ('private','depth','uram_x'):
        raise ValueError('width/P/layout')
    bits = 18 if width == 16 else 8
    rows = []
    for name,banks,depth,contexts in [('x',24,662,p),('xn',24,662,p),('q',24,662,p),
                                    ('kv',24,662,p),('xb',42,378,p),('ob',42,432,ob_slots)]:
        private = layout == 'private' or name == 'ob'
        count = banks*contexts*bram18(depth,bits) if private else banks*bram18(depth*contexts,bits)
        uram = 0
        if layout == 'uram_x' and name in ('x','xn'):
            # Proposed four lanes in <=72 bits/token; partial-write handling is a gate.
            uram = 6*math.ceil(contexts*depth/4096)
            count = 0
        rows.append(dict(name=name,logical_bits=banks*depth*contexts*bits,banks=banks,
                         depth=depth,contexts=contexts,bits=bits,bram18=count,uram=uram))
    b = 23.5 + sum(r['bram18']/2 for r in rows)
    u = 20 + sum(r['uram'] for r in rows)
    return dict(bram36=b,uram=u,fixed_bram36=23.5,rows=rows,
                capacity_only_feasible=b<=144 and u<=64,
                note='No additional PIPO/arbiter reserve; ports/timing/inference unverified')

def make_events(p=1,n=16,width=16,layout='depth',pipeline=True,projection_rate=1.,
                attention_rate=1.,copy_fraction=1.,opaque_policy='barrier',
                opaque_projection_fraction=0.,ob_slots=1,layers=12):
    if p not in (1,2,3) or n<1 or width not in (8,16):
        raise ValueError('P/n/width')
    if opaque_policy not in ('barrier','projection','independent'):
        raise ValueError('opaque policy')
    if min(projection_rate,attention_rate)<=0 or not 0<=copy_fraction<=1:
        raise ValueError('rate/fraction')
    if not 0<=opaque_projection_fraction<=1 or not 1<=layers<=12:
        raise ValueError('residual/layers')
    cost = json.loads(INPUT.read_text(encoding='utf-8'))['model_cycles']
    caps = {r:1 for r in ('projection','norm_stats','scores','ctx','aux','residual','copy','axi','opaque')}
    caps['gate'] = 100
    if not pipeline:
        caps['serial'] = 1
    events = []
    def add(k,name,duration,deps,units=(),memories=None,acquire='',release='',owner='',opaque=False):
        resources = {r:1 for r in units}
        resources['gate'] = 100 if opaque and opaque_policy=='barrier' else 1
        if not pipeline:
            resources['serial'] = 1
        for mem,ports in (memories or {}).items():
            suffix = str(k%p) if layout=='private' and mem!='ob' else 'shared'
            key = f'ram:{mem}:{suffix}'
            caps[key] = 2
            resources[key] = ports
        events.append(Event(name,int(duration),tuple(deps),resources,acquire,release,owner))
    for k in range(n):
        prev = (f'{k-p}:store',) if k>=p else ()
        if not pipeline and k:
            prev = (f'{k-1}:store',)
        add(k,f'{k}:load',cost['load'],prev,('axi',),{'x':1})
        prev = (f'{k}:load',)
        for l in range(layers):
            a = f'{k}:{l}:'
            add(k,a+'stats1',cost['stats'],prev,('norm_stats',))
            add(k,a+'norm1',cost['norm'],(a+'stats1',),('norm_stats',),{'x':1,'xn':1,'xb':1})
            last = a+'norm1'
            for job,dst in [('q','q'),('k','kv'),('v','kv')]:
                owner = a+job
                deps = [last]
                if job=='v' and not pipeline:
                    deps.append(a+'softmax')
                add(k,a+job+'proj',projection_cycles(projection_rate),deps,
                    ('projection',),{'xb':math.ceil(projection_rate),'ob':math.ceil(projection_rate)},acquire='ob',owner=owner)
                cd = [a+job+'proj']
                if job=='v':
                    cd.append(a+'scores')  # K/V alias: no overwrite before last K read.
                cp = math.ceil((cost['copy']-2)*copy_fraction)+2 if copy_fraction else 0
                add(k,a+job+'copy',cp,cd,('copy',),
                    {'ob':math.ceil(1/copy_fraction) if copy_fraction else 1,dst:1},release='ob',owner=owner)
                last = a+job+'copy'
                if job=='k':
                    add(k,a+'scores',6*math.ceil(2646/(4*attention_rate))+8,(last,),('scores',),{'q':math.ceil(attention_rate),'kv':math.ceil(attention_rate)})
                    add(k,a+'softmax',cost['softmax'],(a+'scores',),('aux',))
            add(k,a+'ctx',6*(6*math.ceil(441/(4*attention_rate))+1)+13,(last,a+'softmax'),('ctx',),{'kv':math.ceil(attention_rate),'xn':math.ceil(attention_rate),'x':math.ceil(attention_rate)})
            add(k,a+'stats2',cost['stats'],(a+'ctx',),('norm_stats',))
            add(k,a+'norm2',cost['norm'],(a+'stats2',),('norm_stats',),{'x':1,'xn':1,'xb':1})
            add(k,a+'mproj',projection_cycles(projection_rate),(a+'norm2',),
                ('projection',),{'xb':math.ceil(projection_rate),'ob':math.ceil(projection_rate)},acquire='ob',owner=a+'m')
            add(k,a+'res2',cost['res2'],(a+'mproj',),('residual',),{'ob':1,'xn':1,'x':1},release='ob',owner=a+'m')
            opaque = math.ceil(cost['opaque_layer']*(1-opaque_projection_fraction+opaque_projection_fraction/projection_rate))
            unit = 'projection' if opaque_policy=='projection' else 'opaque'
            add(k,a+'opaque',opaque,(a+'res2',),(unit,),opaque=True)
            prev = (a+'opaque',)
        add(k,f'{k}:head',cost['head'],prev,('aux',),{'x':1})
        add(k,f'{k}:opaque_io',cost['opaque_io'],(f'{k}:head',),('axi',),opaque=True)
        deps = [f'{k}:opaque_io'] + ([f'{k-1}:store'] if k else [])
        add(k,f'{k}:store',cost['store'],deps,('axi',))
    return events,caps,{'ob':ob_slots}

def run_case(**kwargs):
    args = dict(p=1,n=16,width=16,layout='depth',pipeline=True,projection_rate=1.,
                attention_rate=1.,copy_fraction=1.,opaque_policy='barrier',
                opaque_projection_fraction=0.,ob_slots=1,layers=12)
    args.update(kwargs)
    events,caps,slots = make_events(**args)
    out = schedule(events,caps,slots)
    n,p = args['n'],args['p']
    done = [out['times'][f'{k}:store'][1] for k in range(n)]
    start = [out['times'][f'{k}:load'][0] for k in range(n)]
    lo,hi = max(p,n//4),n-p
    ii = (done[hi-1]-done[lo-1])/(hi-lo) if hi>lo else None
    return dict(parameters=args,cycles=out['cycles'],cycles_with_command=out['cycles']+4,
                finite_ms=(out['cycles']+4)/200000.,ms_per_patch=(out['cycles']+4)/200000./n,
                first_completion_cycles=done[0],mean_latency_cycles=sum(b-a for a,b in zip(start,done))/n,
                max_latency_cycles=max(b-a for a,b in zip(start,done)),tail_ii_cycles=ii,
                resource_lower_bound_ii=max(sum(e.duration*e.resources.get(r,0) for e in events)/(n*c) for r,c in caps.items()),
                fill_drain_cycles=out['cycles']-n*ii if ii else None,
                utilization=out['utilization'],resource_wait_cycles=sum(out['waiting'].values()),
                opaque_fraction=(12*15425+3767)/663158.,
                memory=memory_budget(args['width'],p,args['layout'],args['ob_slots']),
                implementation_eligible=args['copy_fraction']>0 and memory_budget(args['width'],p,args['layout'],args['ob_slots'])['capacity_only_feasible'],
                scope='Analytical scenario only; calibration is not stage validation')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/host/m3_s0_20261007')
    a = parser.parse_args()
    variants = [dict(name='serial16',width=16,pipeline=False),
                dict(name='copy2_only',width=16,pipeline=False,copy_fraction=.5),
                dict(name='int8_r2_only',width=8,pipeline=False,projection_rate=2.),
                dict(name='pipe16',width=16),
                dict(name='pipe8_same_lanes',width=8),dict(name='copy2_16',width=16,copy_fraction=.5),
                dict(name='int8_r1.5',width=8,projection_rate=1.5),dict(name='int8_r2',width=8,projection_rate=2.),
                dict(name='int8_r2_attn2',width=8,projection_rate=2.,attention_rate=2.),
                dict(name='combo8',width=8,projection_rate=2.,attention_rate=2.,copy_fraction=.5),
                dict(name='copy_zero_bound',width=16,copy_fraction=0)]
    cases = []
    for v in variants:
        cfg = {k:val for k,val in v.items() if k!='name'}
        for p in (1,2,3):
            if not cfg.get('pipeline',True) and p!=1:
                continue
            for n in (1,16,64):
                for policy in ('barrier','projection','independent'):
                    if not cfg.get('pipeline',True) and policy!='barrier':
                        continue
                    r = run_case(p=p,n=n,opaque_policy=policy,**cfg)
                    r['name'] = v['name']
                    cases.append(r)
    memory = [dict(width=w,p=p,layout=l,**memory_budget(w,p,l))
              for w in (16,8) for p in (1,2,3) for l in ('private','depth','uram_x')]
    stress = [run_case(p=2,n=64,width=8,layout=l,ob_slots=s,projection_rate=2.,attention_rate=2.,
                      copy_fraction=.5,opaque_projection_fraction=f)
              for l in ('private','depth','uram_x') for s in (1,2) for f in (0.,1.)]
    a.out.mkdir(parents=True,exist_ok=True)
    result = dict(schema=1,scope='S0 host analytical estimates only',cases=cases,memory=memory,sensitivity=stress)
    (a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    keys = ['name','parameters','cycles_with_command','ms_per_patch','first_completion_cycles',
            'mean_latency_cycles','max_latency_cycles','tail_ii_cycles','resource_lower_bound_ii',
            'fill_drain_cycles','utilization','resource_wait_cycles','implementation_eligible']
    summary = dict(schema=1,scope=result['scope'],
                   cases=[{k:r[k] for k in keys} for r in cases],
                   memory=memory,
                   sensitivity=[{k:r[k] for k in keys if k in r} for r in stress])
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(f'{len(cases)} cases + {len(stress)} sensitivity cases; {a.out}')

if __name__=='__main__':
    main()
