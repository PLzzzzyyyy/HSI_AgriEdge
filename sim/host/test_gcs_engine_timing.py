import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_engine_timing as e
def receipt():
    text='S2C TASK_ENGINE session=0000002a task=7 pixels=4 calls=1 cycles=200000 hz=199998000 valid=1\n'
    for k,c,us in zip(e.PARTS,(9,4,4,4,1,2,1,1),(100,300,500,600,20,20,1200,20)):
        text+=f'S2C TASK_DETAIL session=0000002a task=7 part={k} calls={c} us={us}\n'
    return text+'S2C TASK_DETAIL session=0000002a task=7 part=wait_service calls=3 us=100\n'
class Timing(unittest.TestCase):
    def test_real_counter_contract_separate_from_wait(self):
        d=e.parse(receipt(),42,7,4,3000,1);self.assertTrue(d['available']);self.assertAlmostEqual(d['engine']['us'],200000*1e6/199998000)
        self.assertAlmostEqual(d['engine']['ms_per_pixel'],200000*1000/199998000/4);self.assertEqual(d['other_step_us'],240)
    def test_missing_invalid_not_measurement(self):
        self.assertFalse(e.parse('',42,7,4,3000,1)['available'])
        self.assertFalse(e.parse(receipt().replace('valid=1','valid=0'),42,7,4,3000,1)['available'])
    def test_wrong_clock_counts_partial_overlap(self):
        for old,new in [('hz=199998000','hz=200000000'),('cycles=200000','cycles=0'),('pixels=4','pixels=3'),
                        ('part=embed calls=4','part=embed calls=3'),('part=wait_service calls=3 us=100','part=wait_service calls=3 us=1300')]:
            with self.assertRaises(ValueError):e.parse(receipt().replace(old,new),42,7,4,3000,1)
        with self.assertRaises(ValueError):e.parse(receipt(),42,7,4,2000,1)
        with self.assertRaises(ValueError):e.parse(receipt()+receipt(),42,7,4,3000,1)
if __name__=='__main__':unittest.main()
