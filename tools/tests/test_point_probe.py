"""Offline point-task orchestration checks. No UDP, UART or hardware access."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import server


class PointProbeTests(unittest.TestCase):
    def setUp(self):
        self.owner=MagicMock(spec=server.board_link.BoardSource)
        self.state=SimpleNamespace(source=self.owner,board_source=self.owner,
                                   control_lock=threading.Lock(),run=None)
        self.run=SimpleNamespace(id=9,status='done',n=1,board_job=object(),summary=lambda:dict(id=9))
        self.cmd=dict(confirmed=True,scene='longkou',version='v2',row=169,col=68)
        self.owner.probe.return_value=dict(state='queued',row=169,col=68)
        self.state_patch=patch.object(server,'S',self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def start(self,cmd):
        self.state.run=self.run
        return self.run

    def test_click_receives_one_pixel_then_queues_full_probe(self):
        with patch.object(server,'start_run',side_effect=self.start) as start:
            result=server.api_board_point_probe(self.cmd)
        self.assertEqual(start.call_args.args[0]['rect'],[169,68,1,1])
        self.assertEqual(result['run']['id'],9)
        self.owner.probe.assert_called_once_with(self.run.board_job,169,68)

    def test_invalid_or_unconfirmed_click_never_starts(self):
        for update in (dict(confirmed=False),dict(row=True),dict(row=550),dict(col=-1),dict(scene='missing')):
            with self.subTest(update=update),patch.object(server,'start_run') as start:
                with self.assertRaises(server.HTTPException):
                    server.api_board_point_probe(dict(self.cmd,**update))
                start.assert_not_called()
        self.owner.probe.assert_not_called()

    def test_partial_or_failed_task_never_probes(self):
        for status,n in (('error',0),('stopped',0),('done',0)):
            self.run.status=status;self.run.n=n
            with self.subTest(status=status,n=n),patch.object(server,'start_run',side_effect=self.start):
                with self.assertRaises(server.HTTPException):server.api_board_point_probe(self.cmd)
        self.owner.probe.assert_not_called()

    def test_new_task_during_wait_never_probes_stale_task(self):
        self.run.status='running'
        def switched(cmd):
            self.state.run=object()
            return self.run
        with patch.object(server,'start_run',side_effect=switched):
            with self.assertRaises(server.HTTPException):server.api_board_point_probe(self.cmd)
        self.owner.probe.assert_not_called()

    def test_busy_owner_is_not_retried(self):
        with patch.object(server,'start_run',side_effect=ValueError('busy')) as start:
            with self.assertRaises(server.HTTPException):server.api_board_point_probe(self.cmd)
        start.assert_called_once()
        self.owner.probe.assert_not_called()

    def test_history_is_preserved_without_becoming_live(self):
        audit=SimpleNamespace(total=1,scene_height=2,scene_width=2,y=0,x=0,height=1,width=1,
                              scene='longkou',identity={'model':'v2'},rows={0:[0x80000000,None]},count=1,reported_done=1)
        job=SimpleNamespace(audit=audit,host_run={'id':5,'kind':'region'},lock=threading.RLock(),
                            ended='2026-10-17T22:00:00+08:00',state='done')
        with tempfile.TemporaryDirectory(dir=ROOT/'.runtime-tmp') as root,patch.object(server.board_history,'load_all',return_value=([job],[])),patch.object(server.E,'discover_board_exports',return_value=[]):
            state=server.State(root)
        self.assertIsNone(state.run)
        self.assertEqual(state.runs[5].n,1)
        self.assertEqual(state.next_id,6)


if __name__=='__main__':unittest.main()
