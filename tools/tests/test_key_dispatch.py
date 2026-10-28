import copy
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_keys
import board_agri
import board_link
import server

class Owner:
    boot=17;session=18;healthy=True;channel_ready=True;operation=None
    def __init__(self):self.calls=[];self.job=NS(probe_result=None);self.lock=threading.RLock()
    def probe(self,job,row,col):
        self.calls.append(('probe',row,col));job.probe_result=dict(state='done')
    def finish_key(self,event,**kwargs):self.calls.append(('finish',kwargs))
    def stop(self):self.calls.append(('stop',));server.S.run.status='stopped'
    def request_models(self,*args,**kwargs):
        self.calls.append(('activate',args));self.operation=NS(complete=True,state='done')

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'.runtime-tmp');self.addCleanup(self.tmp.cleanup)
        self.owner=Owner()
        self.state=NS(board_source=self.owner,source=self.owner,run=None,control_lock=threading.Lock(),
                      parcels=board_agri.ParcelStore(Path(self.tmp.name)/'ledger'))
        self.events=[]
        for target,value in [('S',self.state),('key_version',lambda scene:'v2'),
            ('business_metadata',lambda scene:dict(shape=[550,400])),('emit_json',self.events.append),('log',lambda *a:None)]:
            p=patch.object(server,target,value);p.start();self.addCleanup(p.stop)
    def event(self,key,gesture):return dict(boot_id=17,session=18,id=1,key=key,gesture=gesture,scene='longkou')
    def make_run(self,status='running'):
        run=NS(board_job=self.owner.job,scene='longkou',version='v2',status=status,n=100)
        run.summary=lambda:dict(id=1,status=run.status,scene=run.scene)
        self.state.run=run;return run
    def test_point_preserves_existing_region(self):
        run=self.make_run();server.execute_key(self.event(5,1))
        self.assertEqual((run.n,run.status),(100,'running'))
        _,r,c=self.owner.calls[0];self.assertTrue(0<=r<550 and 0<=c<400)
    def test_busy_scan_rejected_without_overwriting_task(self):
        run=self.make_run()
        with self.assertRaisesRegex(ValueError,'运行中'):server.execute_key(self.event(5,2))
        self.assertIs(self.state.run,run);self.assertEqual(self.owner.calls,[])
    def test_polygon_appends_ledger_and_selects_its_own_statistics(self):
        old=dict(id='manual',name='人工地块',pts=[[0,0],[10,0],[0,10]])
        self.state.parcels.save('longkou',[550,400],[old],0)
        run=self.make_run('done');commands=[]
        with patch.object(server,'start_run',lambda cmd:(commands.append(cmd) or run)):
            run.id=1;server.execute_key(self.event(6,2))
        ledger=self.state.parcels.load('longkou',[550,400])
        self.assertEqual(ledger['parcels'][0],old);self.assertEqual(len(ledger['parcels']),2)
        self.assertEqual(self.state.dp_selection['parcel_id'],ledger['parcels'][1]['id'])
        self.assertEqual(commands[0]['kind'],'region')
    def test_hold_stops_before_switching_and_retains_pixels(self):
        run=self.make_run();server.execute_key(self.event(6,3))
        self.assertEqual(run.n,100);self.assertEqual(run.status,'stopped')
        self.assertEqual(self.owner.calls[0],('stop',))
        self.assertEqual(self.owner.calls[1],('finish',dict(code=10,scene='honghu')))
        self.assertFalse(any(call[0]=='activate' for call in self.owner.calls))
        self.assertTrue(self.state.key_preview)
        self.assertEqual(self.events[0]['state'],'preparing')
        self.assertEqual(self.state.key_context['scene'],'honghu')
    def test_duplicate_physical_packet_never_enqueues_twice(self):
        owner=board_link.BoardSource(Path(self.tmp.name)/'channel');owner.boot=17;owner.session=18
        raw=struct.pack('<HBBHHI',0x4548,board_keys.EVENT,1,0,0,0)+struct.pack('<IIIBBBB',17,18,1,5,3,0,0)
        owner.receive_key(raw);owner.receive_key(raw)
        self.assertEqual(len(owner.key_events),1)
        event=owner.take_key();owner.finish_key(event,scene='honghu',code=10)
        owner.receive_key(raw)
        self.assertIsNone(owner.take_key());self.assertEqual(owner.key_responses[-1]['scene'],'honghu')
        with self.assertRaises(ValueError):owner.receive_key(raw[:25]+bytes([1])+raw[26:])
    def test_scene_area_parameters_match_existing_console(self):
        self.assertEqual(tuple(round(server.E.MISSION[s]['gsd_m']*1000) for s in board_keys.SCENES),board_keys.GSD_MM)

if __name__=='__main__':unittest.main()
