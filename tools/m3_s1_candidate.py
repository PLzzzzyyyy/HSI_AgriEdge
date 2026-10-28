"""S1 executable ownership/bank prototype, NOT a cycle-accurate HLS engine.

Reference operators carry real integer payloads. Persistent blocks have physical
depth-packed contexts; xb, ob and weights are single/shared. P1 and P2 use the
same scheduler. Time units below are adversarial service slots, never RTL cycles.
"""
from dataclasses import dataclass
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import engine_ref as ref

D, N, H, DEPTH = 2646, 6, 4, 662
POS = np.arange(D)

def load_engine(path):
    data = Path(path).read_bytes()
    hdr = np.frombuffer(data, '<u4', 4)
    assert tuple(hdr[:2]) == (0x32455454, 2)
    e = ref.Engine.__new__(ref.Engine)
    e.ncls, num = map(int, hdr[2:4])
    e.cfg = ref.Cfg(num)
    assert len(data) == (336064 if num == 8 else 480576)
    e.emb = np.frombuffer(data, '<i4', D*N, 64).astype(np.int64).reshape(D, N)
    hw = np.stack([np.frombuffer(data, '<i2', D, 63744+c*5312) for c in range(e.ncls)]).astype(np.int64)
    he = np.frombuffer(data, 'i1', e.ncls, 32).astype(np.int64)
    hb = np.frombuffer(data, '<i4', e.ncls, 63616).astype(np.int64)
    e.hw = hw, he, hb
    weights = np.frombuffer(data, 'i1' if num == 8 else '<i2', 144672, 191232).astype(np.int64).reshape(12,4,3014)
    exps = np.frombuffer(data, 'i1', 144, 335904).reshape(12,4,3) if num == 8 else np.full((12,4,3),14)
    e.wp = [[(w[:49].reshape(7,7), w[49:98].reshape(7,7), w[98:].reshape(54,54), tuple(map(int, exps[l,j])))
             for j,w in enumerate(row)] for l,row in enumerate(weights)]
    return e

def pair_products(x, w0, w1):
    product = ((w1.astype(np.int64) << 18) + w0) * x
    lo = ((product + (1 << 17)) & ((1 << 18)-1)) - (1 << 17)
    hi = (product >> 18) + (lo < 0)
    return lo, hi

def packed_contract(m, x, axis):
    """Pair output rows sharing each input; odd row padded, never dropped."""
    xx = np.moveaxis(x, axis, -1)
    shape = xx.shape
    xx = xx.reshape(-1, shape[-1])[:, None, :]
    mm = np.pad(m, ((0, len(m) % 2), (0, 0)))
    a,b = pair_products(xx, mm[0::2][None,:,:], mm[1::2][None,:,:])
    yy = np.stack((a.sum(-1), b.sum(-1)), -1).reshape(xx.shape[0], -1)[:, :len(m)]
    return np.moveaxis(yy.reshape(shape[:-1] + (len(m),)), -1, axis)

def packed_projection(x, w, cfg):
    assert cfg.num == 8 and not cfg.mix
    m1,m2,m3,(e1,e2,e3) = w
    t = x.T.reshape(N,7,7,54)
    t = ref.sat(ref.rshift_rnd(packed_contract(m1,t,1),e1),8)
    t = ref.sat(ref.rshift_rnd(packed_contract(m2,t,2),e2),8)
    t = ref.sat(ref.rshift_rnd(packed_contract(m3,t,3),e3),8)
    return t.reshape(N,D).T.copy()

@dataclass(frozen=True)
class Config:
    num: int = 8
    p: int = 2
    def __post_init__(self):
        if self.num not in (8,16) or self.p not in (1,2):
            raise ValueError(self)
    @property
    def bits(self):
        return 8 if self.num == 8 else 18

class Banks:
    def __init__(self, cfg):
        self.cfg = cfg
        # No context partition: context is a depth address, not another bank.
        self.data = np.zeros((N,H,cfg.p*DEPTH), np.int64)
    def write(self, ctx, x):
        assert 0 <= ctx < self.cfg.p
        assert x.shape == (D,N) and np.all(x == ref.sat(x,self.cfg.bits))
        self.data[:, POS % H, ctx*DEPTH + POS//H] = x.T
    def read(self, ctx):
        assert 0 <= ctx < self.cfg.p
        return self.data[:,POS % H,ctx*DEPTH + POS//H].T.copy()

class Ob:
    def __init__(self):
        self.owner = None
        self.data = np.zeros((N,2,7,216), np.int64)
    def claim(self, owner):
        assert self.owner is None, 'ob still leased through consumption'
        self.owner = owner
    def put(self, owner, x):
        assert self.owner == owner
        a,b,c = POS//378, (POS//54)%7, POS%54
        self.data[:, a%2, b, (a//2)*54+c] = x.T
    def read(self, owner):
        assert self.owner == owner, 'ob owner mismatch'
        a,b,c = POS//378, (POS//54)%7, POS%54
        return self.data[:,a%2,b,(a//2)*54+c].T.copy()
    def release(self, owner):
        assert self.owner == owner
        self.owner = None
    def copy2(self, owner, dst, ctx):
        # Vectorized execution of exactly the pair addresses tested independently.
        dst.write(ctx, self.read(owner))

DEPS = dict(N1=set(), Q={'N1'}, CQ={'Q'}, K={'CQ'}, CK={'K'},
            S={'CK'}, V={'CK'}, CV={'V','S'}, SM={'S'}, C={'CV','SM'},
            N2={'C'}, M={'N2'}, R={'M'})
UNIT = dict(N1='norm', N2='norm', Q='proj', K='proj', V='proj', M='proj',
            CQ='copy', CK='copy', CV='copy', S='scores', SM='aux', C='ctx', R='res2', HEAD='aux')
# Conservative per-bank peak across token/H lanes; read+write share two ports.
# Contexts change depth addresses, NEVER the port count. HLS integration must
# still verify arbitration and the exact subcycle access phases.
PORTS = dict(N1={'x':1,'xn':1,'xb':1},N2={'x':1,'xn':1,'xb':1},
    Q={'xb':1,'ob':1},K={'xb':1,'ob':1},V={'xb':1,'ob':1},M={'xb':1,'ob':1},
    CQ={'ob':2,'q':1},CK={'ob':2,'kv':1},CV={'ob':2,'kv':1},
    S={'q':1,'kv':1},SM={},C={'kv':1,'xn':1,'x':1},
    R={'ob':1,'xn':1,'x':1},HEAD={'x':1})

def ports_fit(stages):
    from collections import Counter
    count=Counter()
    for stage in stages: count.update(PORTS[stage])
    return all(n<=2 for n in count.values())

class Scheduler:
    def __init__(self, engine, cfg, seed=1):
        assert engine.cfg.num == cfg.num
        self.e, self.cfg, self.rng = engine, cfg, np.random.default_rng(seed)
        self.banks = {k:Banks(cfg) for k in ('x','xn','q','kv')}
        self.ob, self.xb, self.xb_owner = Ob(), None, None
        self.trace = []
        self.waits = dict(ob=0, xb=0, output=0, kv_join=0)
    def run(self, inputs, stall_output_until=0):
        slots = [None]*self.cfg.p
        active, result, accepted, emitted, tick = {}, [], 0, 0, 0
        while emitted < len(inputs):
            assert tick < 200000, 'deadlock / missing output'
            # Downstream random backpressure; context retained until accepted output.
            for c,s in enumerate(slots):
                if s and s.get('output') is not None:
                    if s['id'] == emitted and tick >= stall_output_until and self.rng.random() > .35:
                        result.append(s['output']); slots[c] = None; emitted += 1
                    else:
                        self.waits['output'] += 1
            for c in range(self.cfg.p):
                if slots[c] is None and accepted < len(inputs):
                    self.banks['x'].write(c, inputs[accepted])
                    slots[c] = dict(id=accepted, layer=0, done=set(), busy=set(), kv=None, output=None)
                    accepted += 1
            # Nonpreemptive single-unit services. A random hold models backpressure.
            for unit,(c,stage,left) in list(active.items()):
                if left or self.rng.random() < .15:
                    active[unit] = (c,stage,max(0,left-1)); continue
                s = slots[c]
                self.finish(c,s,stage)
                s['busy'].remove(stage); s['done'].add(stage)
                self.trace.append((tick,'end',s['id'],s['layer'],stage))
                del active[unit]
                if stage == 'R':
                    assert not s['busy']
                    s['layer'] += 1; s['done'] = set(); s['kv'] = None
            order = self.rng.permutation(self.cfg.p)
            for c in order:
                s = slots[c]
                if not s or s['output'] is not None: continue
                stages = ['HEAD'] if s['layer']==12 else list(DEPS)
                for stage in stages:
                    if stage in s['done'] or stage in s['busy']: continue
                    if stage != 'HEAD' and not DEPS[stage] <= s['done']: continue
                    unit = UNIT[stage]
                    if unit in active: continue
                    if not ports_fit([v[1] for v in active.values()]+[stage]): continue
                    owner = (s['id'],s['layer'])
                    if stage in ('N1','N2') and self.xb_owner is not None:
                        self.waits['xb'] += 1; continue
                    if stage in ('Q','K','V','M') and self.ob.owner is not None:
                        self.waits['ob'] += 1; continue
                    if stage in ('Q','K','V','M'):
                        assert self.xb_owner == owner
                        self.ob.claim(owner+(stage,))
                    if stage in ('N1','N2'): self.xb_owner = owner
                    if stage == 'V' and 'S' not in s['done']: self.waits['kv_join'] += 1
                    s['busy'].add(stage)
                    active[unit] = (c,stage,int(self.rng.integers(1,8)))
                    self.trace.append((tick,'start',s['id'],s['layer'],stage))
            tick += 1
        assert not active and self.ob.owner is None and self.xb_owner is None
        return result

    def finish(self,c,s,stage):
        b,e = self.banks,self.e
        owner = (s['id'],s['layer'])
        read = lambda name:b[name].read(c)
        if stage in ('N1','N2'):
            xn = ref.normalize(read('x'),e.cfg)[0]
            b['xn'].write(c,xn); self.xb = xn
        elif stage in ('Q','K','V','M'):
            assert self.xb_owner == owner
            idx = {'Q':0,'K':1,'V':2,'M':3}[stage]
            self.ob.put(owner+(stage,),ref.proj(self.xb,e.wp[s['layer']][idx],e.cfg))
            if stage in ('V','M'): self.xb_owner = None; self.xb = None
        elif stage in ('CQ','CK','CV'):
            key = stage[1:]; dst = 'q' if key=='Q' else 'kv'
            if key=='V': assert 'S' in s['done'] and s['kv']=='K', 'K overwritten before score consumed'
            self.ob.copy2(owner+(key,),b[dst],c)
            self.ob.release(owner+(key,))
            if key in ('K','V'): s['kv'] = key
        elif stage=='S':
            assert s['kv']=='K'
            s['scores'] = read('q').T @ read('kv')
        elif stage=='SM':
            score=s.pop('scores'); d=(score.max(1,keepdims=True)-score) << (24-2*e.cfg.PF)
            ex=ref.exp_q24(d); s['attn']=(ex*((1<<47)//ex.sum(1,keepdims=True))+(1<<22))>>23
        elif stage=='C':
            assert s['kv']=='V'
            ctx=(s.pop('attn') @ read('kv').reshape(N,D)).reshape(D,N)
            ctx=ref.sat(ref.rshift_rnd(ctx,24),e.cfg.DB)
            b['x'].write(c,ref.sat(read('xn')+ctx,e.cfg.DB))
        elif stage=='R':
            m=self.ob.read(owner+('M',))
            b['x'].write(c,ref.sat(read('xn')+m,e.cfg.DB))
            self.ob.release(owner+('M',))
        elif stage=='HEAD':
            x=read('x'); logits,label,conf=ref.head(x[:,1],e.hw,e.cfg)
            s['output']=dict(x=x,logits=logits,label=label,conf=conf)
        else: raise ValueError(stage)
