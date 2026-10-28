import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_metrics as m

class EvaluationTests(unittest.TestCase):
    def test_confusion_f1_and_class_support(self):
        truth=np.array([[1,1,2],[2,3,0]],dtype=np.uint8)
        pred=np.array([[1,2,2],[1,3,1]],dtype=np.uint8)
        r=m.evaluate(pred,np.ones(truth.shape,dtype=bool),truth,3)
        self.assertEqual(r['n'],5);self.assertEqual(r['received_pixels'],6)
        self.assertEqual(r['cm'],[[1,1,0],[1,1,0],[0,0,1]])
        self.assertAlmostEqual(r['OA'],.6);self.assertAlmostEqual(r['AA'],2/3)
        self.assertAlmostEqual(r['macro_F1'],2/3);self.assertAlmostEqual(r['weighted_F1'],.6)
        self.assertEqual(r['correct_pixels'],3);self.assertEqual(r['evaluated_classes'],3)
        self.assertEqual(r['predicted_counts'],[2,2,1])

    def test_empty_and_uncovered_are_not_zero_accuracy(self):
        truth=np.array([[1,2,3]],dtype=np.uint8);pred=np.array([[2,1,1]],dtype=np.uint8)
        r=m.evaluate(pred,np.array([[True,False,False]]),truth,3)
        self.assertEqual(r['AA'],0);self.assertEqual(r['macro_F1'],0)
        self.assertEqual(r['per_class'],[0,None,None]);self.assertEqual(r['f1'],[0,0,None])
        empty=m.evaluate(pred,np.zeros(truth.shape,dtype=bool),truth,3)
        for key in ('OA','AA','Kappa','macro_F1','weighted_F1'):self.assertIsNone(empty[key])
        self.assertEqual(empty['coverage'],0)

    def test_roi_coverage_and_csv_use_only_received_class_words(self):
        truth=np.array([[1,1,2],[2,3,0]],dtype=np.uint8)
        meta={'classes':['玉米','大豆','水体']}
        cells=[dict(x=0,y=0,class_word='ffff0000',class_id=0),dict(x=1,y=1,class_word='ffff0002',class_id=2)]
        snap=dict(model_lifecycle=True,scene='longkou',model='v2',wcrc='27231983',boot_id='00000001',session=2,task=3,
                  ack=True,status='stopped',roi=dict(x=0,y=0,width=2,height=2),cells=cells,received_pixels=2)
        with patch.object(m.board_models,'task_identity'),patch.object(m,'load_labels',return_value=(truth,meta)):
            r=m.from_snapshot(snap)
        self.assertEqual(r['task_test_total'],4);self.assertEqual(r['task_test_coverage'],.5)
        self.assertEqual(r['coverage'],.4);self.assertEqual(r['OA'],1)
        r['class_names']=meta['classes'];text=m.csv_text(r)
        self.assertIn('玉米,1,1,1,1.0,1.0,1.0',text)
        self.assertIn('大豆,0,0,0,,,',text)

if __name__=='__main__':unittest.main()
