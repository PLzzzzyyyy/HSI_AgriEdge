from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import gcs_boot_provision as p
import gcs_sd_boot_verify as v
def uart(gen):return (f'S2C BUILD app=gcs_r1_abi4 release={"1"*64} sources={"2"*64} xsa={"3"*64}\n'+f'S2C IDENTITY source=sd-journal boot_id={0x10203040+gen:08x} generation={gen} nonce=1234567887654321 abi=4\n'+f'S2C READY boot_id={0x10203040+gen:08x} registry=6 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app=gcs_r1_abi4\n').encode()
class BootTools(unittest.TestCase):
    def test_record_and_correlate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for slot,gen in ((0,2),(1,1)):(root/f'jrn{slot}.bin').write_bytes(p.record(slot,0x10203040,gen,0x1234567887654321))
            (root/'uart.bin').write_bytes(uart(2));(root/'prev.bin').write_bytes(uart(1))
            r=v.verify(root/'uart.bin',root,root/'prev.bin');self.assertEqual(r['result'],'FILE_CORRELATION_PASS');self.assertFalse(r['independent_cold_start_acceptance'])
            (root/'prev.bin').write_bytes(uart(2))
            with self.assertRaises(ValueError):v.verify(root/'uart.bin',root,root/'prev.bin')
            (root/'uart.bin').write_bytes(uart(3))
            with self.assertRaises(ValueError):v.verify(root/'uart.bin',root)
    def test_crc_reservation_and_destination(self):
        raw=p.record(0,0x10203040,2,1);self.assertEqual(v.record(raw,0)['generation'],2)
        bad=bytearray(raw);bad[24]^=1
        with self.assertRaises(ValueError):v.record(bad,0)
        with self.assertRaises(ValueError):p.provision(ROOT/'vitis/forbidden_test_target')
        with self.assertRaises(ValueError):v.uart_identity(uart(2)+uart(2))
        with self.assertRaises(ValueError):v.uart_identity(b'S2B BOOT_ID: 8 hex digits + LF/CRLF\n'+uart(2))
if __name__=='__main__':unittest.main()
