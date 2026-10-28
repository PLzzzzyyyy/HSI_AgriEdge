"""Fixed-label evaluation, never model inference or board task execution."""
from pathlib import Path
import sys, unittest, tempfile, json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'gcs'))
import board_metrics as m

class MetricsTests(unittest.TestCase):
    def test_snapshot_class_zero_is_crop_one_and_missing_is_unseen(self):
        test,meta=m.load_labels()
        y,x=map(int,np.argwhere(test==1)[0])
        snap=dict(scene='longkou',model='v2',wcrc='27231983',boot_id='12345678',session='0000002a',task=7,
                  status='done',error=None,ack=True,received_pixels=1,roi=dict(x=x,y=y,width=1,height=1),
                  cells=[dict(x=x,y=y,class_word='00000000',class_id=0)])
        r=m.from_snapshot(snap)
        self.assertEqual(r['n'],1);self.assertEqual(r['cm'][0][0],1);self.assertEqual(r['OA'],1)
        self.assertFalse(r['complete_test_coverage']);self.assertEqual(r['test_total'],203642)
        snap['cells'].append(snap['cells'][0])
        with self.assertRaises(ValueError):m.from_snapshot(snap)
    def test_pinned_label_bytes_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta=json.loads((ROOT/'gcs/eval_longkou_v2.json').read_text(encoding='utf-8'))
            for record in meta['files'].values():
                p=root/record['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/record['path']).read_bytes())
            manifest=root/'manifest.json';manifest.write_text(json.dumps(meta),encoding='utf-8')
            m.load_labels(root,manifest)
            test=root/meta['files']['test']['path'];raw=test.read_bytes();test.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            with self.assertRaises(ValueError):m.load_labels(root,manifest)

    def test_confusion_partial_coverage_absent_class(self):
        labels=np.array([[1,1,2],[2,3,0]],dtype='u1')
        pred=np.array([[1,2,2],[0,0,0]],dtype='u1');seen=pred>0
        r=m.evaluate(pred,seen,labels,3)
        self.assertEqual(r['cm'],[[1,1,0],[0,1,0],[0,0,0]])
        self.assertAlmostEqual(r['OA'],2/3);self.assertAlmostEqual(r['AA'],.75)
        self.assertAlmostEqual(r['Kappa'],.4)
        self.assertEqual(r['per_class'],[.5,1.,None])
        self.assertEqual(r['test_total'],5);self.assertEqual(r['n'],3)
        self.assertFalse(r['complete_test_coverage'])
    def test_no_seen_or_labeled_does_not_fabricate_accuracy(self):
        r=m.evaluate(np.zeros((2,2),'u1'),np.zeros((2,2),bool),np.ones((2,2),'u1'),2)
        self.assertEqual(r['n'],0);self.assertIsNone(r['OA']);self.assertIsNone(r['Kappa'])
    def test_invalid_received_prediction_not_zero_background(self):
        for bad in (0,4):
            with self.assertRaises(ValueError):m.evaluate(np.array([[bad]]),np.ones((1,1),bool),np.ones((1,1),'u1'),3)
        with self.assertRaises(ValueError):m.evaluate(np.ones((1,2)),np.ones((1,1),bool),np.ones((1,1)),3)
        with self.assertRaises(ValueError):m.evaluate(np.ones((1,1),'u1'),np.ones((1,1),bool),np.array([[-1]]),3)
    def test_train_and_test_must_be_disjoint_and_match_gt(self):
        gt=np.array([[1,2],[0,3]],dtype='u1');train=np.array([[1,0],[0,0]],dtype='u1');test=np.array([[0,2],[0,3]],dtype='u1')
        m.validate_labels(gt,train,test,3)
        with self.assertRaises(ValueError):m.validate_labels(gt,gt,test,3)
        test[0,1]=3
        with self.assertRaises(ValueError):m.validate_labels(gt,train,test,3)
        with self.assertRaises(ValueError):m.validate_labels(np.array([[-1]]),np.array([[-1]]),np.array([[0]]),3)

if __name__=='__main__':unittest.main(verbosity=2)
