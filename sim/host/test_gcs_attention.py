import copy,struct,sys,types,unittest,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_attention as a
import board_task as t
import board_history as h
def identity():return dict(scene='longkou',model='v2',classes=9,wcrc='27231983')
def fragments():
    raw=struct.pack('<432I',*([1<<24,0,0,0,0,0]*72));crc=zlib.crc32(raw);packets=[]
    for n in (0,1):packets.append(a.HEADER.pack(0x4548,0x87,1,7,10+n,99)+a.META.pack(2,0,9,0,0,0x27231983,0x12345678,99,crc,432,n,2,n*216,216,12,6,24,0)+raw[n*864:(n+1)*864])
    return packets
def audit():return types.SimpleNamespace(boot=0x12345678,session=99,task=7,identity=identity(),rows={},scene_width=400)
def probe():return dict(state='running',req_seq=2,row=0,col=0,attention_requested=True,identity=identity(),ping_seq=1,stamp=123,have_pong=True,have_status=True,result=dict(class_word='FFFF0000',class_id=0,confidence_q16=65535,logits_q16=[1]+[0]*8))
class Attention(unittest.TestCase):
    def test_reorder_duplicate_complete(self):
        p=probe();f=fragments();h.apply_probe_reply(p,t.decode(f[1]),audit());self.assertEqual(p['state'],'running')
        h.apply_probe_reply(p,t.decode(f[1]),audit());h.apply_probe_reply(p,t.decode(f[0]),audit())
        self.assertEqual((p['state'],p['attention_shape']),('done',[12,6,6]));self.assertEqual(len(p['attention_q24']),432)
    def test_incomplete_never_done(self):
        p=probe();h.apply_probe_reply(p,t.decode(fragments()[0]),audit());self.assertNotIn('attention_q24',p);self.assertEqual(p['state'],'running')
    def test_conflict_clears(self):
        p=probe();d=t.decode(fragments()[0]);h.apply_probe_reply(p,d,audit());d['words'][0]-=1
        with self.assertRaises(ValueError):h.apply_probe_reply(p,d,audit())
        self.assertEqual(p['state'],'error');self.assertNotIn('attention_q24',p)
    def test_crc_and_identity(self):
        for key in ('boot_id','session','task','wcrc','row','scene'):
            p=probe();d=t.decode(fragments()[0]);d[key]+=1
            with self.assertRaises(ValueError):a.accept(p,d,audit())
        p=probe();d=t.decode(fragments()[0]);d['words'][0]-=1;a.accept(p,d,audit())
        with self.assertRaises(ValueError):a.accept(p,t.decode(fragments()[1]),audit())
    def test_wire_mutation_and_no_substitute(self):
        for offset,value in ((38,2),(39,3),(44,11),(46,16),(47,1)):
            raw=bytearray(fragments()[0]);raw[offset]=value
            with self.assertRaises(ValueError):t.decode(raw)
        p=probe();p['attention_requested']=False
        with self.assertRaises(ValueError):a.accept(p,t.decode(fragments()[0]),audit())
if __name__=='__main__':unittest.main()
