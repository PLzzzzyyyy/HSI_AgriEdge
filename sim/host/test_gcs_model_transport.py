"""Three-scene lifecycle identity fixtures. No network/device/model inference."""
from pathlib import Path
import copy
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_task as t
import board_models as m
w=t.wire

def descriptor(scene='honghu',tag='demo',crc='12345678'):
    s=m.scene_spec(scene)
    return dict(scene=scene,model=tag,wcrc=crc,shape=s['shape'],classes=s['classes'],kind=1)

def status(scene='honghu',task=7,crc=0x12345678,done=1,state=3,rect=(939,474,1,1)):
    y,x,h,width=rect
    body=struct.pack('<IIfffBBH',done,h*width if task else 0,*(float('nan'),)*3,state,0,0)
    body+=struct.pack('<IIIHBB8IHHI',0x12345678,42,crc,y+done//width if task else 0,1,0,*(0,)*8,0,0,0)
    return w.packet(0x82,task,100,100,body)

def info(scene=1,task=7,crc=0x12345678,rect=(939,474,1,1),entries=()):
    y,x,h,width=rect
    body=struct.pack('<IBBBBIHBB4HIHBB',0x12345678,1,3,16,len(entries),42,task,1 if task else 0,scene if task else 0,
                     y if task else 0,x if task else 0,h if task else 0,width if task else 0,crc if task else 0,y+h if task else 0,3 if task else 0,0)
    for e in entries:body+=struct.pack('<BBHII16s',*e)
    return w.packet(0x86,task,101,101,body)

class ModelAuditTests(unittest.TestCase):
    def ready(self,scene='honghu',rect=(939,474,1,1)):
        a=t.Audit(0x12345678,42,7,rect,False,identity=descriptor(scene))
        a.sent(w.packet(1,7,1,1,a.start_body()))
        a.received(w.packet(0x83,7,1,1,struct.pack('<BBHI',1,0,1,0)))
        return a

    def test_three_scenes_start_rows_snapshot_own_identity(self):
        for scene in m.SCENES:
            spec=m.scene_spec(scene);h,width=spec['shape'];rect=(h-1,width-1,1,1);a=self.ready(scene,rect)
            body=struct.unpack('<BBBB4HII',a.start_body())
            self.assertEqual((body[1],body[-2]),(spec['id'],0x12345678))
            word=0xffff0000|spec['classes']-1
            a.received(w.packet(0x81,7,2,2,struct.pack('<4HI',h-1,width-1,1,0,word)))
            a.received(status(scene=scene,rect=rect));self.assertTrue(a.complete())
            j=t.Job(a.boot,a.session,a.task,rect,False,identity=descriptor(scene));j.audit=a
            s=j.snapshot();self.assertEqual((s['scene'],s['model'],s['wcrc']),(scene,'demo','12345678'))
            self.assertEqual(s['shape'],spec['shape']);self.assertEqual(len(s['class_counts']),spec['classes'])
            self.assertEqual(s['cells'][0]['class_id'],spec['classes']-1)
        self.assertEqual(t.rect_for(dict(kind='scan',scene='hanchuan',version='demo')),[0,0,1217,303])

    def test_task_specific_class_limit_and_late_other_model_status(self):
        a=self.ready('longkou',(549,399,1,1))
        b=w.packet(0x81,7,2,2,struct.pack('<4HI',549,399,1,0,0xffff0009))
        with self.assertRaisesRegex(ValueError,'CLASS'):a.received(b)
        self.assertEqual(a.count,0)
        self.assertIsNone(a.received(status(task=6,crc=0x98765432)))
        with self.assertRaisesRegex(ValueError,'model'):a.received(status(rect=(549,399,1,1),crc=0x98765432))
        fresh=t.Audit(a.boot,a.session,1,[0,0,550,400],True,identity=descriptor('longkou'))
        fresh.received(status(task=0,crc=0,done=0,state=0));self.assertTrue(fresh.ready)

    def test_registry_strict_shape_tag_padding_duplicate_and_task_identity(self):
        a=self.ready();a.begin_recovery();a.sent(w.packet(7,0,10,1,b''))
        entry=(1,1,0,m.ENGINE_BYTES,0x12345678,b'demo')
        d=a.received(info(entries=[entry]));self.assertEqual(d['entries'][0]['tag'],'demo')
        for e in [(1,1,1,m.ENGINE_BYTES,0x12345678,b'demo'),(1,1,0,99,0x12345678,b'demo'),
                  (1,1,0,m.ENGINE_BYTES,0x12345678,b'../bad'),(1,1,0,m.ENGINE_BYTES,0x12345678,b'demo\0x'),
                  (1,1,0,m.ENGINE_BYTES,0x12345678,b'a'*16)]:
            with self.assertRaises(ValueError):t.decode(info(entries=[e]))
        with self.assertRaises(ValueError):t.decode(info(entries=[entry,entry]))
        with self.assertRaisesRegex(ValueError,'mismatch'):a.received(info(scene=2,rect=(939,300,1,1)))

    def test_logits_scene_contract_and_argmax_not_pc_features(self):
        for scene in m.SCENES:
            s=m.scene_spec(scene);n=s['classes'];values=[-100]*n;values[-1]=500
            body=struct.pack('<HBBHHII',4,s['id'],n,s['shape'][0]-1,s['shape'][1]-1,0x12345678,0xffff0000|n-1)+struct.pack(f'<{n}i',*values)
            d=t.decode(w.packet(0x85,7,11,11,body));self.assertEqual(len(d['logits_q16']),n)
            bad=bytearray(body);bad[3]-=1
            with self.assertRaises(ValueError):t.decode(w.packet(0x85,7,11,11,bad))
        with self.assertRaises(ValueError):t.board_probe.decode(w.packet(0x85,7,11,11,body)) # frozen old codec

    def test_explicit_recovery_reanchors_wrapped_status_clock_after_info_pong(self):
        a=self.ready();a.received(status(done=0,state=1));a.begin_recovery();a.sent(w.packet(7,0,10,1,b''))
        later=bytearray(status(done=1,state=3));struct.pack_into('<I',later,8,3000000000)
        early=bytearray(later);struct.pack_into('<I',early,8,101)
        self.assertIsNone(a.received(early)) # no old status before recovery INFO
        a.received(info());a.sent(w.packet(5,7,11,99,struct.pack('<I',42)))
        a.received(w.packet(0x84,7,77,3000000000,struct.pack('<HHII',11,0,99,3000000000)))
        self.assertIsNotNone(a.received(later));self.assertEqual(a.reported_done,1)

    def test_large_scene_fragmented_row_repair_fits_one_bounded_v1_request(self):
        missing=list(range(0,1217,2))
        raw=t.row_request(missing);n,pad=struct.unpack_from('<HH',raw)
        self.assertLessEqual(n,349);self.assertEqual(pad,0);self.assertLessEqual(len(raw),1400)
        requested=set()
        for off in range(4,len(raw),4):
            row,count=struct.unpack_from('<HH',raw,off);self.assertGreater(count,0)
            self.assertLessEqual(row+count,1217);requested.update(range(row,row+count))
        self.assertTrue(set(missing)<=requested)
        # Extra rows may be safely re-requested, but no out-of-range position
        # or non-integer input may make it onto the real socket.
        for bad in ([],[1217],[-1],[True],[1.2]):
            with self.assertRaises(ValueError):t.row_request(bad)

if __name__=='__main__':unittest.main()
