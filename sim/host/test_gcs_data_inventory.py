"""Local future-SD inventory validation; never an SD/device test."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import gcs_data_inventory as inv
import board_models as m

class InventoryTests(unittest.TestCase):
    def test_missing_files_are_errors_not_empty_success_or_board_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=inv.inventory(tmp,{'honghu':['v1']})
            self.assertFalse(r['local_data_verified']);self.assertEqual(len(r['errors']),2);self.assertEqual(r['files'],[])
            self.assertIsNone(r['sd_present']);self.assertIsNone(r['board_activated']);self.assertFalse(r['boot_image_created'])
            self.assertFalse(r['standalone_identity_ready']);self.assertFalse(r['first_release_complete'])
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_paths_duplicates_and_scene_contracts_reject_before_reading(self):
        for selection in ({},{'longkou':['../other']},{'honghu':['v1','v1']},{'other':['v1']}):
            with self.subTest(selection=selection),patch.object(inv.InputReader,'_manifest',side_effect=AssertionError('Must reject before read')):
                with self.assertRaises(ValueError):inv.inventory(ROOT/'data/scenes',selection)
    def test_data_claim_includes_current_byte_crc_contract_not_only_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec=m.scene_spec('longkou');path=Path(tmp)/'longkou/cube_f32.bin'
            forged=(path,None,(*spec['shape'],3,270),dict(bytes=spec['cube_bytes'],crc32='00000000',sha256='0'*64))
            with patch.object(inv.InputReader,'_manifest',return_value=forged):r=inv.inventory(tmp,{'longkou':['v2']})
            self.assertFalse(r['local_data_verified']);self.assertIn('board scene contract',r['errors'][0]['error'])
            self.assertEqual(list(Path(tmp).iterdir()),[])

if __name__=='__main__':unittest.main()
