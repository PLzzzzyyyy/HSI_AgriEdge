"""S1 arithmetic, existing QAT/golden and payload ownership tests (host only)."""
from collections import Counter
import json
from pathlib import Path
import sys
import unittest
import numpy as np
from m3_s1_candidate import (ROOT, D, N, H, DEPTH, POS, ref, Config, Banks,
    Ob, Scheduler, load_engine, pair_products, packed_projection)

GOLD = ROOT/'sim/golden/n6_engine_i8'
SUMMARY = {}

def same(a,b):
    np.testing.assert_array_equal(a,b)

class S1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = load_engine(GOLD/'weights_engine.bin')

    def test_entry_exhaustive_and_rounding(self):
        x = np.arange(-32768,32768,dtype=np.int64)
        # Independent quotient/remainder definition: nearest, ties toward +inf.
        expected=np.clip(x//256 + (x%256 >=128),-128,127)
        same(self.e.entry_a(x),expected)
        same(ref.rshift_rnd(np.array([-384,-128,128,384]),8),[-1,0,1,2])
        for shift in range(-10,18):
            v=np.array([-100000,-129,-128,-1,0,1,127,128,100000],np.int64)
            expect=v*(1<<(-shift)) if shift<=0 else v//(1<<shift)+(v%(1<<shift)>=(1<<(shift-1)))
            same(ref.rshift_rnd(v,shift),expect)
        same(ref.sat(np.array([-129,-128,127,128]),8),[-128,-128,127,127])
        SUMMARY['entry_exhaustive']=65536

    def test_pair_exhaustive(self):
        w0=np.arange(-128,128,dtype=np.int64)[:,None]
        w1=np.arange(-128,128,dtype=np.int64)[None,:]
        for x in range(-128,128):
            lo,hi=pair_products(x,w0,w1)
            same(lo,np.broadcast_to(x*w0,(256,256)))
            same(hi,np.broadcast_to(x*w1,(256,256)))
        SUMMARY['pair_exhaustive']=256**3

    def test_dot54_extremes_random_and_bad_packed_accumulator(self):
        rng=np.random.default_rng(54)
        x=rng.integers(-128,128,(10000,54),dtype=np.int64)
        w0=rng.integers(-128,128,x.shape,dtype=np.int64)
        w1=rng.integers(-128,128,x.shape,dtype=np.int64)
        for i,(a,b) in enumerate([(-128,-128),(-128,127),(127,-128),(127,127)]):
            x[i]=a; w0[i]=b; w1[i]=-b if b!=-128 else 127
        lo,hi=pair_products(x,w0,w1)
        same(lo.sum(1),(x*w0).sum(1)); same(hi.sum(1),(x*w1).sum(1))
        self.assertEqual(int(lo[0].sum()),884736)
        # Mutation: accumulate packed 54 products without unpacking. Must fail.
        raw=((((w1<<18)+w0)*x).sum(1))
        bad_lo=((raw+(1<<17))&((1<<18)-1))-(1<<17)
        self.assertFalse(np.array_equal(bad_lo,lo.sum(1)))
        self.assertEqual(int(bad_lo[0]),98304)
        SUMMARY['dot54_cases']=10000

    def test_qat_packages_exponents(self):
        from export_scene import engine_package
        records=[]
        for scene,ncls,package in [('longkou',9,GOLD/'weights_engine.bin'),
            ('honghu',22,ROOT/'data/scenes/honghu/weights/v1_int8/weights_engine.bin'),
            ('hanchuan',16,GOLD/'batch_hanchuan/weights_engine.bin')]:
            ckpt=ROOT/'data/ckpt'/f'{scene}_qat8_s0.pth'
            e=ref.Engine(str(ckpt),ncls,num=8)
            same(engine_package(e),np.fromfile(package,'u1'))
            if scene=='longkou':
                patch=np.fromfile(ROOT/'model/data/golden/patch_f32.bin','<f4')
                xin,_=ref.ps_embed_q312(e.net,patch)
                same(xin,np.fromfile(GOLD/'a/x_in_i16.bin','<i2').reshape(D,N))
            ex=[]
            for li,row in enumerate(e.wp):
                for pi,(m1,m2,m3,ee) in enumerate(row):
                    f=e.net.layers[li][('query','key','value','mlp')[pi]]['f']
                    for mat,fp,shift in zip((m1,m2,m3),f,ee):
                        self.assertEqual(shift,int(np.floor(np.log2(127/abs(fp).max()))))
                        same(mat,np.clip(np.floor(fp*2.**shift+.5),-127,127).astype(np.int64))
                        self.assertGreaterEqual(int(mat.min()),-127)
                    ex.extend(ee)
            records.append(dict(scene=scene,matrices=len(ex),exponent_min=min(ex),exponent_max=max(ex)))
        SUMMARY['qat']=records

    def test_longkou_all_existing_trace(self):
        counts={}
        for entry in ('a','b'):
            path=GOLD/entry
            if entry=='a':
                x0=self.e.entry_a(np.fromfile(path/'x_in_i16.bin','<i2').reshape(D,N))
            else:
                x0=self.e.entry_b(np.fromfile(GOLD/'cube_win_i16.bin','<i2').reshape(7,7,272),bfp=True)
            same(x0,np.fromfile(path/'x_embed_i32.bin','<i4').reshape(D,N))
            trace=[]; o=self.e.forward(x0,trace)
            count=0
            for li,t in enumerate(trace):
                for key,value in t.items():
                    dt='<i8' if key=='s' else '<i4'
                    same(value,np.fromfile(path/f'L{li}_{key}_{dt[1:]}.bin',dt).reshape(value.shape)); count+=1
            same(o['logits'],np.fromfile(path/'logits_q16_i32.bin','<i4')[:self.e.ncls])
            self.assertEqual((o['conf']<<16)|o['label'],int(np.fromfile(path/'class_u32.bin','<u4')[0]))
            counts[entry]=count
        SUMMARY['golden_trace_arrays']=counts

    def test_packed_all_48_projections_and_odd_output_tail(self):
        for li,row in enumerate(self.e.wp):
            for pi,w in enumerate(row):
                inp='xn2_q' if pi==3 else 'xn_q'
                out=('q','k','v','m')[pi]
                x=np.fromfile(GOLD/'a'/f'L{li}_{inp}_i4.bin','<i4').astype(np.int64).reshape(D,N)
                y=packed_projection(x,w,self.e.cfg)
                same(y,np.fromfile(GOLD/'a'/f'L{li}_{out}_i4.bin','<i4').reshape(D,N))
        SUMMARY['packed_golden_projections']=48

    def test_copy2_physical_ports_and_depth(self):
        # Check every pair, including c=52, a/parity changes and last p=2644.
        touched=set()
        for ctx in range(2):
            for p in range(0,D,2):
                reads=Counter(); writes=Counter()
                for t in range(N):
                    for q in (p,p+1):
                        a,b,c=q//378,(q//54)%7,q%54
                        reads[(t,a%2,b)]+=1; writes[(t,q%4)]+=1
                        addr=(t,q%4,ctx*DEPTH+q//4)
                        self.assertNotIn(addr,touched); touched.add(addr)
                        self.assertLess((a//2)*54+c,216)
                self.assertEqual(max(reads.values()),2)
                self.assertEqual(max(writes.values()),1)
        self.assertEqual(len(touched),2*D*N)
        # Direct K7 mode3->H4 writes: four writes in one bank, not two.
        self.assertEqual(max(Counter(((b*54)%4) for b in range(7)).values()),4)
        SUMMARY['copy_pairs_per_context']=D//2

    def test_copy_payload_p1_p2_both_widths_and_ob_lease(self):
        rng=np.random.default_rng(82)
        for num in (8,16):
            for p in (1,2):
                cfg=Config(num,p); bank=Banks(cfg); ob=Ob(); want=[]
                for c in range(p):
                    x=rng.integers(-(1<<(cfg.bits-1)),1<<(cfg.bits-1),(D,N),dtype=np.int64)
                    want.append(x); ob.claim(c); ob.put(c,x)
                    with self.assertRaises(AssertionError): ob.claim(c+1)
                    with self.assertRaises(AssertionError): ob.read(c+1)
                    ob.copy2(c,bank,c); ob.release(c)
                for c in range(p): same(bank.read(c),want[c])
                # Padding cells must remain untouched (last H4 group has 2 lanes).
                for c in range(p): same(bank.data[:,2:,c*DEPTH+661],np.zeros((N,2),np.int64))

    def test_kv_early_overwrite_and_early_ob_release_are_rejected(self):
        s=Scheduler(self.e,Config(8,2))
        slot=dict(id=0,layer=0,done={'V'},kv='K')
        s.ob.claim((0,0,'V'))
        with self.assertRaisesRegex(AssertionError,'K overwritten'):
            s.finish(0,slot,'CV')
        s.ob.release((0,0,'V'))
        # Mutation: release the M result before res2's last consumer.
        with self.assertRaisesRegex(AssertionError,'ob owner mismatch'):
            s.finish(0,slot,'R')

    def test_depth_packing_does_not_add_ports(self):
        from m3_s1_candidate import ports_fit
        self.assertTrue(ports_fit(['S','CV']))
        self.assertFalse(ports_fit(['S','CV','C']))
        self.assertFalse(ports_fit(['CQ','Q']))

    def test_scheduler_payload_order_backpressure_and_reflow(self):
        a=np.fromfile(GOLD/'a/x_embed_i32.bin','<i4').astype(np.int64).reshape(D,N)
        b=np.fromfile(GOLD/'b/x_embed_i32.bin','<i4').astype(np.int64).reshape(D,N)
        rng=np.random.default_rng(715)
        inputs=[a,b,a,ref.sat(a+rng.integers(-3,4,a.shape),8),ref.sat(-b,8)]
        expected=[self.e.forward(x) for x in inputs]
        records=[]
        for p in (1,2):
            for seed in (1,19,715):
                s=Scheduler(self.e,Config(8,p),seed)
                actual=s.run(inputs,stall_output_until=1800)
                for got,want in zip(actual,expected):
                    for key in ('x','logits','label','conf'): same(got[key],want[key])
                self.assertEqual(len(actual),5)
                self.assertEqual(sum(t[1]=='end' and t[4]=='R' for t in s.trace),60)
                self.assertGreater(s.waits['output'],0)
                self.assertGreater(s.waits['kv_join'],0)
                if p==2: self.assertGreater(s.waits['ob']+s.waits['xb'],0)
                # Independent trace audit: resources cannot be double-booked,
                # K must survive scores, and the next layer must await R.
                from m3_s1_candidate import UNIT, ports_fit
                running={}; ends={}
                for tick,event,patch,layer,stage in s.trace:
                    unit=UNIT[stage]; key=(patch,layer,stage)
                    if event=='start':
                        self.assertNotIn(unit,running); running[unit]=key
                        self.assertTrue(ports_fit([v[2] for v in running.values()]))
                        if stage=='CV': self.assertIn((patch,layer,'S'),ends)
                        if stage=='N1' and layer: self.assertIn((patch,layer-1,'R'),ends)
                    else:
                        self.assertEqual(running.pop(unit),key); ends[key]=tick
                self.assertFalse(running)
                records.append(dict(p=p,seed=seed,waits=s.waits,events=len(s.trace)))
        SUMMARY['payload_scheduler']=records

    def test_same_scheduler_int16_control(self):
        path=ROOT/'sim/golden/n6_engine'
        e=load_engine(path/'weights_engine.bin')
        a=np.fromfile(path/'a/x_embed_i32.bin','<i4').astype(np.int64).reshape(D,N)
        b=ref.sat(-a,e.cfg.DB)
        inputs=[a,b,a]; expected=[e.forward(x) for x in inputs]
        for p in (1,2):
            actual=Scheduler(e,Config(16,p),4).run(inputs)
            for got,want in zip(actual,expected):
                for key in ('x','logits','label','conf'): same(got[key],want[key])

    def test_hanchuan_32_existing_integer_goldens(self):
        path=GOLD/'batch_hanchuan'
        e=load_engine(path/'weights_engine.bin')
        wins=np.fromfile(path/'wins_i16.bin','<i2').reshape(-1,7,7,272)
        inputs=[e.entry_b(w,bfp=True) for w in wins]
        actual=Scheduler(e,Config(8,2),32).run(inputs,stall_output_until=3000)
        logits=np.fromfile(path/'expect_logits_i32.bin','<i4').reshape(32,32)
        classes=np.fromfile(path/'expect_class_u32.bin','<u4')
        for i,got in enumerate(actual):
            same(got['logits'],logits[i,:e.ncls])
            self.assertEqual((got['conf']<<16)|got['label'],classes[i])
        self.assertEqual(len(actual),32)
        SUMMARY['hanchuan_existing_goldens']=32

if __name__=='__main__':
    out=ROOT/'build/host/m3_s1_host'
    out.mkdir(parents=True,exist_ok=True)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(S1Tests))
    SUMMARY.update(tests=result.testsRun,passed=result.wasSuccessful(),scope='HOST_NOT_RTL_OR_BOARD')
    (out/'summary.json').write_text(json.dumps(SUMMARY,indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
