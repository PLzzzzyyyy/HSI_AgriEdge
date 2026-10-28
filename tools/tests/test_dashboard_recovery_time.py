"""Repeated terminal status must not add reconnection time to a finished run."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import server

class RecoveryTimeTests(unittest.TestCase):
    def test_terminal_callback_preserves_original_end_time(self):
        run=SimpleNamespace(id=1,status='running',t0=100.,t_end=None,kind='region',n=15,total=15,summary=lambda:{})
        with patch.object(server,'emit_json'),patch.object(server,'log'),patch.object(server.time,'time',return_value=101.):
            done=server.run_callbacks(run)[1]
            done('done')
        self.assertEqual(run.t_end,101.)
        with patch.object(server,'emit_json'),patch.object(server,'log'),patch.object(server.time,'time',return_value=500.):
            done('done')
        self.assertEqual(run.t_end,101.)
        self.assertEqual(run.status,'done')

if __name__=='__main__':unittest.main()
