"""Offline terminal reconnect never erases a claim or starts inference."""
import json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_link,board_task

def info_packet(flag=1,state=3):
    raw=bytearray(60)
    struct.pack_into('<HBBHHI',raw,0,0x4548,0x86,1,5,1,0)
    struct.pack_into('<IBBBB',raw,12,0x12345678,1,4,16,0)
    struct.pack_into('<IHBB4HIHBB',raw,20,18,5,1,0,20,10,5,10,0x27231983,25,state,flag)
    return bytes(raw)

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'.runtime-tmp');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.info=board_task.decode(info_packet())
    def test_info_flag_checked_without_weakening_roi_identity(self):
        self.assertTrue(self.info['terminal_owned'])
        self.assertFalse(board_task.decode(info_packet(0))['terminal_owned'])
        with self.assertRaises(ValueError):board_task.decode(info_packet(2))
        raw=bytearray(info_packet());struct.pack_into('<H',raw,24,6)
        with self.assertRaises(ValueError):board_task.decode(raw)
    def test_explicit_completed_local_handoff_preserves_original_claim(self):
        boots=self.root/'boots';boots.mkdir();claim=boots/'12345678.json'
        original={'boot_id':'12345678','session':18,'channel':'old'};claim.write_text(json.dumps(original))
        source=board_link.BoardSource(self.root)
        source.authorize('12345678',True,terminal_info=self.info)
        source.resume_terminal(self.info)
        self.assertEqual(json.loads(claim.read_text()),original)
        self.assertEqual((source.session,source.next_task,source.latest_task),(18,6,5))
        self.assertTrue(source.terminal_resume_pending)
        with patch.object(source,'_launch') as launch:
            source.request_models('query');launch.assert_called_once()
        self.assertIsNone(source.job) # reconnect queries, never STARTs a task
    def test_new_pc_can_claim_local_only_boot_with_no_existing_history(self):
        source=board_link.BoardSource(self.root)
        source.authorize('12345678',True,terminal_info=self.info);source.resume_terminal(self.info)
        self.assertEqual(json.loads((self.root/'boots/12345678.json').read_text())['session'],18)
    def test_busy_or_different_session_rejected(self):
        source=board_link.BoardSource(self.root)
        with self.assertRaises(ValueError):source.authorize('12345678',True,terminal_info=board_task.decode(info_packet(state=1)))
        boots=self.root/'boots';boots.mkdir();(boots/'12345678.json').write_text(json.dumps({'boot_id':'12345678','session':999}))
        source.authorize('12345678',True,terminal_info=self.info)
        with self.assertRaises(ValueError):source.resume_terminal(self.info)

if __name__=='__main__':unittest.main()
