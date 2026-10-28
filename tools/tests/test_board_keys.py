import random
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_keys as keys
import board_agri as agri

class KeysTests(unittest.TestCase):
    def test_geometry_bounds_area_and_ledger(self):
        for scene,h,w,mm in [('longkou',550,400,463),('honghu',940,475,43),('hanchuan',1217,303,109)]:
            for seed in range(200):
                rng=random.Random(seed)
                r,c,dh,dw=keys.rectangle(scene,h,w,rng)
                self.assertTrue(0<=r<r+dh<=h and 0<=c<c+dw<=w)
                self.assertLessEqual(dh*dw*mm*mm,6000*1000000)
                self.assertLessEqual(dh*dw,4096)
                rect,pts=keys.polygon(scene,h,w,rng)
                r,c,dh,dw=rect
                self.assertTrue(3<=len(pts)<=5)
                valid=agri.validate_parcels([dict(id='test',name='test',pts=pts)],(h,w))
                box,mask=agri.polygon_mask(valid[0]['pts'],(h,w))
                self.assertGreater(mask.sum(),0)
                self.assertTrue(all(c<=x<=c+dw and r<=y<=r+dh for x,y in pts))
                self.assertLessEqual(mask.sum(),dh*dw)
                self.assertLessEqual(dh*dw*mm*mm,6000*1000000)
    def test_wire_identity_and_reset_key_rejected(self):
        packet=struct.pack('<HBBHHI',0x4548,keys.EVENT,1,2,3,0)+struct.pack('<IIIBBBB',17,18,1,5,3,0,0)
        self.assertEqual(keys.decode(packet,17,18)['gesture'],3)
        with self.assertRaises(ValueError):keys.decode(packet,17,19)
        wrong=packet[:24]+bytes([7])+packet[25:]
        with self.assertRaises(ValueError):keys.decode(wrong,17,18)
        self.assertEqual(len(keys.receipt(17,18,1,3,10,'honghu')),16)

if __name__=='__main__':unittest.main()
