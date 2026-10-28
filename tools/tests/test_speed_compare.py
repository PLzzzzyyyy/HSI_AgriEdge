import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
from speed_compare import Comparison


class FakeRun:
    total=6
    def __init__(self,identity,ms):
        self.id=identity;self.ms=ms;self.status='running';self.n=0
    def summary(self):
        self.n=min(6,self.n+2)
        if self.n==6 and self.status=='running':self.status='done'
        return dict(done=self.n,status=self.status,board_ms_per_px=self.ms,
                    board=dict(boot_id='01',session='02',task=self.id,model='checked',scene='longkou',wcrc='01'))


class SpeedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.compare=Comparison(self.temp.name)
    def join(self):
        self.compare.thread.join(3);self.assertFalse(self.compare.thread.is_alive())
    def test_same_roi_sequential_progress_and_saved_history(self):
        starts=[]
        def start(version,identity):
            starts.append(version);return FakeRun(len(starts),4 if version=='v2' else 5)
        self.compare.start('longkou',['v2','v3'],[1,2,2,3],start,lambda r:None,lambda:None);self.join()
        data=self.compare.snapshot();self.assertEqual(starts,['v2','v3']);self.assertEqual(data['state'],'done')
        self.assertEqual(data['rect'],[1,2,2,3]);self.assertEqual([i['done'] for i in data['items']],[6,6])
        self.assertEqual([i['rate'] for i in data['items']],[250,200])
        self.assertEqual([i['compute_ms'] for i in data['items']],[24,30])
        self.assertEqual(self.compare.load(data['id']),data)
        self.assertEqual(len(self.compare.history()),1)
        self.assertEqual([p['done'] for p in data['items'][0]['trace']],[0,2,4,6])
    def test_cancel_does_not_start_second_model(self):
        calls=[]
        def start(version,identity):
            calls.append(version);self.compare.stop();return FakeRun(1,4)
        def stop(run):run.status='stopped'
        self.compare.start('longkou',['v2','v3'],[1,2,2,3],start,stop,lambda:None);self.join()
        self.assertEqual(calls,['v2']);self.assertEqual(self.compare.snapshot()['state'],'cancelled')
    def test_invalid_and_changed_connection(self):
        for versions,rect in [(['v2','v2'],[0,0,1,1]),(['v2',{}],[0,0,1,1]),(['v2','v3'],[0,0,200,200])]:
            with self.assertRaises(ValueError):self.compare.start('longkou',versions,rect,None,None,lambda:None)
        count=0;stops=[]
        def check():
            nonlocal count;count+=1
            if count>=4:raise ValueError('connection changed')
        self.compare.start('longkou',['v2','v3'],[1,2,2,3],lambda v,i:FakeRun(1,4),lambda r:stops.append(r.id),check);self.join()
        self.assertEqual(self.compare.snapshot()['state'],'error');self.assertEqual(stops,[1])


if __name__=='__main__':unittest.main()
