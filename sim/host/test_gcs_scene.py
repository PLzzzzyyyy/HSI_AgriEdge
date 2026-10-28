"""New full-scene PC receiver tests. Synthetic wire fixtures ONLY, no socket/model."""
from pathlib import Path
import sys,struct,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'gcs'))
import board_scene as s
import board_roi as b
w=s.wire

def status(task=0,state=0,done=0,boot=0x12345678,session=42):
    body=struct.pack('<IIfffBBH',done,s.TOTAL if task else 0,*([float('nan')]*3),state,0,0)
    body+=struct.pack('<IIIHBB8IHHI',boot,session,w.WCRC,done//400,1,0,*([0]*8),0,0,0)
    return w.packet(0x82,task,9,100,body)
def ack(code=0):return w.packet(0x83,7,2,3,struct.pack('<BBHI',1,code,1,0))
def row(y,col=0,n=348,word=0xa58f0000,task=7):
    return w.packet(0x81,task,4,5,struct.pack('<HHHH',y,col,n,0)+struct.pack(f'<{n}I',*([word]*n)))
class SceneTests(unittest.TestCase):
    def ready(self):
        j=b.Job(0x12345678,42,7,full=True);j.sent(w.packet(5,0,0,1,struct.pack('<I',42)))
        j.receive(w.packet(0x84,0,0,2,struct.pack('<HHII',0,0,1,2)));j.receive(status())
        j.sent(s.start_packet(7,1,3,42));return j
    def test_exact_full_start_and_row_sizes(self):
        p=s.start_packet(7,1,3,42)
        self.assertEqual(len(p),32);self.assertEqual(struct.unpack_from('<HH',p,20),(550,400));self.assertEqual(p[12],0)
        self.assertEqual(len(row(0)),1412);self.assertEqual(len(row(0,348,52)),228)
    def test_220000_unique_exact_completion(self):
        j=self.ready();j.receive(ack())
        for y in range(550):
            for c,n in [(348,52),(0,348)]:j.receive(row(y,c,n))
        self.assertEqual(j.audit.count,220000);self.assertFalse(j.audit.complete())
        j.receive(status(7,3,220000));self.assertTrue(j.finish())
        out=j.snapshot();self.assertEqual(len(out['cells']),220000);self.assertEqual(out['class_counts'][0],220000)
        self.assertEqual(out['cells'][-1]['x'],399);self.assertEqual(out['cells'][-1]['y'],549)
        self.assertEqual(out['cells'][-1]['class_word'],'A58F0000')
    def test_missing_segment_not_completed_by_done(self):
        j=self.ready();j.receive(ack());j.receive(row(0));j.receive(status(7,3,220000));self.assertFalse(j.finish())
        self.assertEqual(j.snapshot()['received_pixels'],348)
    def test_duplicate_overlap_unique_and_conflict_atomic(self):
        j=self.ready();j.receive(row(0));j.receive(row(0,300,100))
        self.assertEqual(j.audit.count,400);self.assertEqual(j.audit.duplicates,1)
        with self.assertRaisesRegex(ValueError,'conflicting'):j.receive(row(0,300,100,word=0xffff0005))
        self.assertFalse(j.finish());self.assertEqual(j.audit.count,400)
    def test_wrong_identity_task_and_failed_ack(self):
        for p in [status(7,1,4,boot=5),status(7,1,4,session=3),row(0,task=6),ack(6)]:
            j=self.ready()
            with self.assertRaises(ValueError):j.receive(p)
            self.assertFalse(j.finish())
    def test_malformed_rows_rejected(self):
        for p in [row(550),row(0,399,2),row(0,0,349),row(0,0,1,word=0xaabb0100),row(0,0,1,word=0xaabb0009),row(0)[:-1]]:
            j=self.ready()
            with self.assertRaises(ValueError):j.receive(p)
    def test_progress_invariants_and_light_snapshot(self):
        j=self.ready();j.receive(status(7,1,404));j.receive(row(0,0,348))
        out=j.snapshot(include_cells=False);self.assertEqual(out['cells'],[]);self.assertEqual(out['received_pixels'],348)
        self.assertEqual(out['last_status']['front_row'],1)
        with self.assertRaises(ValueError):j.receive(status(7,3,404))
if __name__=='__main__':unittest.main(verbosity=2)
