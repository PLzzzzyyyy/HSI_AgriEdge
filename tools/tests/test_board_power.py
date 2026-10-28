import copy
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_power as p

def packet(task=1,active=True,counter=1,duration=1000000,energy=6.029):
    return struct.pack('<HBBHHI',0x4548,p.MESSAGE,1,task,0,0)+struct.pack('<5IHHIffdQQII',
        17,18,int(p.PROFILE['model_id'],16),counter,0,task,1|2|(4 if active else 0)|(8 if task else 0),
        15 if task else 0,6.029,40,energy,duration,0,15 if task else 0,0)

class PowerTests(unittest.TestCase):
    def test_wire_and_scope(self):
        sample=p.decode(packet(),17,18)
        self.assertFalse(sample['measured']);self.assertFalse(sample['calibrated'])
        self.assertEqual(sample['scope'],'CHIP_PS_PL_ONLY')
        self.assertAlmostEqual(sample['energy_est_mj_per_px'],401.9333333)
        self.assertEqual(p.decode(packet(0,False,energy=0,duration=0),17,18)['energy_est_j'],None)

    def test_bad_identity_values_model_and_header(self):
        raw=packet()
        for data,b,s in [(raw,19,18),(raw,17,19),(raw[:-1],17,18),(raw+b'0',17,18)]:
            with self.assertRaises(ValueError):p.decode(data,b,s)
        for offset,fmt,value in [(20,'I',0),(40,'f',float('nan')),(44,'f',80),(48,'d',-1),(64,'Q',2000000),(76,'I',1),(4,'H',2)]:
            data=bytearray(raw);struct.pack_into('<'+fmt,data,offset,value)
            with self.assertRaises(ValueError):p.decode(data,17,18)

    def test_task_isolation_monotonicity_freeze(self):
        job=SimpleNamespace(audit=SimpleNamespace(boot=17,session=18,task=1,total=15),power_estimate=None)
        first=p.decode(packet(),17,18);self.assertTrue(p.accept_job(job,first))
        self.assertFalse(p.accept_job(job,first))
        other=copy.deepcopy(first);other['task']=2
        self.assertFalse(p.accept_job(job,other))
        final=p.decode(packet(active=False,counter=2),17,18)
        self.assertTrue(p.accept_job(job,final))
        with self.assertRaises(ValueError):p.accept_job(job,p.decode(packet(counter=3),17,18))
        self.assertTrue(p.accept_job(job,p.decode(packet(active=False,counter=4),17,18)))

if __name__=='__main__':unittest.main()
