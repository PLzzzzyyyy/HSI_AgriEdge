import struct,sys,unittest,zlib
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_display as d

class DisplayTests(unittest.TestCase):
    def test_parcel_packet_offsets_counts_and_geometry(self):
        a=SimpleNamespace(boot=1,session=2,crc=3,scene_id=0,scene_width=400,scene_height=550,identity={'classes':9})
        p={'id':'saved','pts':[[0,0],[400,0],[400,550],[0,550]]}
        row={'pixels':220000,'received_pixels':15,'low_pixels':3,'class_counts':[0,0,15,0,0,0,0,0,0]}
        body=d.parcel_body(SimpleNamespace(audit=a),4,p,row,.6,bytes(576),5)
        self.assertEqual(len(body)+12,744)
        self.assertEqual(struct.unpack_from('<III',body,0),(1,2,3))
        self.assertEqual(struct.unpack_from('<IIII',body,20),(5,220000,15,3))
        self.assertEqual(body[38:44],bytes([0,9,4,1,0,0]))
        self.assertEqual(struct.unpack_from('<HH',body,144),(65535,0))
    def test_temperature_rejects_wrong_boot_and_bad_values(self):
        def packet(value):return struct.pack('<HBBHHI',0x4548,d.TEMP,1,0,0,0)+struct.pack('<IIIIffI',1,2,3,0,value,60.,1)
        self.assertAlmostEqual(d.temperature(packet(55),1,2)['temp_c'],55)
        for data,boot in [(packet(55),8),(packet(float('nan')),1),(packet(80),1)]:
            with self.assertRaises(ValueError):d.temperature(data,boot,2)
    def test_mirror_rle_native_png_and_limits(self):
        raw=struct.pack('<HHHH',3,0xf800,1,0x07e0)
        png=d.png_from_rle(raw,2,2)
        self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack_from('>II',png,16),(2,2))
        for bad in [raw[:-1],struct.pack('<HH',0,1),struct.pack('<HH',5,1)]:
            with self.assertRaises(ValueError):d.png_from_rle(bad,2,2)

if __name__=='__main__':unittest.main()
