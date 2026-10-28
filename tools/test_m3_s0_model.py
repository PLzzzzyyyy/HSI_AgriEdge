"""S0 scheduling invariants; these tests do not validate RTL or candidate numerics."""
import unittest
from collections import Counter, defaultdict
from m3_s0_model import Event,schedule,bram18,memory_budget,make_events,run_case,projection_cycles

class SchedulerTests(unittest.TestCase):
    def test_shared_core_serializes(self):
        ev=[Event('a',5,resources={'core':1}),Event('b',7,resources={'core':1})]
        self.assertEqual(schedule(ev,{'core':1})['cycles'],12)
    def test_independent_units_overlap(self):
        ev=[Event('a',5,resources={'a':1}),Event('b',7,resources={'b':1})]
        self.assertEqual(schedule(ev,{'a':1,'b':1})['cycles'],7)
    def test_ports_and_dependency(self):
        ev=[Event('a',3,resources={'ram':1}),Event('b',4,resources={'ram':1}),
            Event('c',5,deps=('a',),resources={'ram':2})]
        self.assertEqual(schedule(ev,{'ram':2})['cycles'],9)
    def test_buffer_lease_includes_consumer_wait(self):
        ev=[Event('a',2,acquire='ob',owner='x'),Event('wait',8),
            Event('consume',3,deps=('a','wait'),release='ob',owner='x'),
            Event('b',2,acquire='ob',owner='y'),Event('consume_b',1,deps=('b',),release='ob',owner='y')]
        self.assertEqual(schedule(ev,{}, {'ob':1})['times']['b'][0],11)
    def test_invalid_demand(self):
        with self.assertRaises(ValueError):
            schedule([Event('a',1,resources={'r':3})],{'r':2})
    def test_dependency_deadlock(self):
        with self.assertRaises(RuntimeError):
            schedule([Event('a',1,deps=('b',)),Event('b',1,deps=('a',))],{})
    def test_no_infinite_buffer(self):
        with self.assertRaises(RuntimeError):
            schedule([Event('a',1,acquire='q',owner='x'),Event('b',1,acquire='q',owner='y')],{}, {'q':1})
    def test_physical_granularity(self):
        self.assertEqual(bram18(662,18),1)
        self.assertEqual(bram18(1324,18),2)
        self.assertEqual(bram18(1986,8),1)
        self.assertEqual(bram18(432,8),bram18(432,18))
    def test_memory_mapping(self):
        self.assertEqual(memory_budget(16,1,'private')['bram36'],113.5)
        self.assertGreater(memory_budget(16,2,'private')['bram36'],144)
        self.assertEqual(memory_budget(8,3,'depth')['bram36'],113.5)
        self.assertGreater(memory_budget(8,2,'private')['bram36'],144)
        self.assertEqual(memory_budget(16,2,'uram_x')['uram'],32)
    def test_p1_calibration_is_not_validation(self):
        r=run_case(p=1,n=3,pipeline=False)
        self.assertEqual(r['cycles_with_command'],1989478)
        self.assertGreater(r['opaque_fraction'],.27)
    def test_int8_not_automatically_faster(self):
        a=run_case(p=1,n=3,width=16,pipeline=False)
        b=run_case(p=1,n=3,width=8,pipeline=False)
        self.assertEqual(a['cycles'],b['cycles'])
    def test_token_fill_drain_and_odd_group_not_halved(self):
        self.assertEqual(projection_cycles(1),3437)
        self.assertEqual(projection_cycles(2),2087)
        self.assertGreater(projection_cycles(2),3437/2)
    def test_finite_contexts_kv_join_recurrence_and_order(self):
        events,cap,slots=make_events(p=2,n=5)
        t=schedule(events,cap,slots)['times']
        for k in range(5):
            if k>=2:
                self.assertGreaterEqual(t[f'{k}:load'][0],t[f'{k-2}:store'][1])
            for l in range(12):
                a=f'{k}:{l}:'
                self.assertGreaterEqual(t[a+'vcopy'][0],t[a+'scores'][1])
                self.assertGreaterEqual(t[a+'ctx'][0],t[a+'softmax'][1])
                self.assertGreaterEqual(t[a+'mproj'][0],t[a+'norm2'][1])
                if l:
                    self.assertGreaterEqual(t[a+'stats1'][0],t[f'{k}:{l-1}:opaque'][1])
            if k:
                self.assertGreaterEqual(t[f'{k}:store'][0],t[f'{k-1}:store'][1])
    def test_peak_ports_wider_compute(self):
        ev,cap,slots=make_events(p=2,n=1,projection_rate=2,attention_rate=2)
        e={x.name:x for x in ev}
        self.assertEqual(e['0:0:scores'].resources['ram:q:shared'],2)
        self.assertEqual(e['0:0:qproj'].resources['ram:xb:shared'],2)
        schedule(ev,cap,slots)
    def test_finite_batch_not_response_latency(self):
        r=run_case(p=2,n=16)
        self.assertGreater(r['mean_latency_cycles'],r['cycles']/16)
        self.assertTrue(all(0<=u<=1 for u in r['utilization'].values()))
    def test_elimination_is_only_bound(self):
        self.assertFalse(run_case(copy_fraction=0)['implementation_eligible'])
    def test_no_unbudgeted_four_port_copy(self):
        ev,cap,slots=make_events(copy_fraction=.25)
        with self.assertRaises(ValueError):
            schedule(ev,cap,slots)
    def test_direct_dump_layout_conflicts(self):
        # K7 output emits b=0..6 at fixed (a,c); p=(a*7+b)*54+c.
        for a in range(7):
            for c in range(54):
                banks=Counter(((a*7+b)*54+c)%4 for b in range(7))
                self.assertEqual(max(banks.values()),4)
        # Adjacent p-pairs read at most two words in one ob bank.
        for p in range(0,2646,2):
            banks=Counter(((i//54)%7) for i in (p,p+1))
            self.assertLessEqual(max(banks.values()),2)
    def test_independent_resource_audit_and_service_counts(self):
        ev,cap,slots=make_events(p=3,n=7,width=8,projection_rate=2,attention_rate=2,copy_fraction=.5)
        t=schedule(ev,cap,slots)['times']
        edges=defaultdict(lambda: defaultdict(int))
        for e in ev:
            begin,end=t[e.name]
            self.assertEqual(end-begin,e.duration)
            for d in e.deps:
                self.assertGreaterEqual(begin,t[d][1])
            for r,q in e.resources.items():
                edges[begin][r]+=q
                edges[end][r]-=q
        live=defaultdict(int)
        for tick in sorted(edges):
            for r,q in edges[tick].items():
                live[r]+=q
                self.assertGreaterEqual(live[r],0)
                self.assertLessEqual(live[r],cap[r])
        self.assertEqual(sum(e.name.endswith('proj') for e in ev),7*48)

if __name__=='__main__':
    unittest.main(verbosity=2)
