"""New server integration checks only; direct API/control calls, no network server."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'gcs'))
import server as s
import board_roi as b

class ServerGateTests(unittest.TestCase):
    def test_run_summary_uses_board_compute_timing_not_wall_time(self):
        from types import SimpleNamespace
        import numpy as np
        r=s.Run(1,'region','longkou','v2',[0,0,1,5],np.zeros((5,2)),550,400,'board')
        r.n=5;r.t0=10;r.t_end=20
        r.board_job=SimpleNamespace(full=True,snapshot=lambda **k:dict(performance=dict(ms_per_pixel=5)))
        summary=r.summary()
        self.assertEqual(summary['board_ms_per_px'],5)
        self.assertEqual(summary['receive_rate'],.5)
        self.assertIsNone(summary['compute_s'])
        r.board_job=SimpleNamespace(full=True,snapshot=lambda **k:dict(performance=None))
        self.assertIsNone(r.summary()['board_ms_per_px'])
    def test_default_state_is_passive_board_only(self):
        with patch.object(b.socket,'socket',side_effect=AssertionError('No socket on startup')), \
             patch.object(s.sources,'PcSource',side_effect=AssertionError('No PC source')):
            state=s.State()
            self.assertIs(state.source,state.board_source)
            self.assertIsNone(state.source.boot)
            self.assertIsNone(state.source.worker)

    def test_pc_source_rejected_without_changing_current_task(self):
        current=object();s.S.run=current
        with patch.object(s.sources,'PcSource',side_effect=AssertionError('No PC source')):
            with self.assertRaises(ValueError):s.set_source(dict(source='pc'))
        self.assertIs(s.S.source,s.S.board_source)
        self.assertIs(s.S.run,current)

    def test_board_metrics_route_does_not_infer(self):
        from types import SimpleNamespace
        payload=dict(source='board',n=3)
        class Job:
            out=None
            def snapshot(self):return {'fixture':'received words'}
        s.S.runs[12]=SimpleNamespace(source='board',board_job=Job())
        with patch.object(s.eng,'get_scene',side_effect=AssertionError('No GPU scene')), \
             patch.object(s.eng,'probe',side_effect=AssertionError('No PC model')), \
             patch.object(s.board_metrics,'from_snapshot',return_value=payload) as evaluate:
            self.assertEqual(s.api_metrics(12),payload)
            evaluate.assert_called_once_with({'fixture':'received words'})

    def test_local_input_never_uses_pc_model_or_board_probe(self):
        payload = dict(scene='longkou',row=0,col=0,board_returned=False,pc_model_inference=False)
        with patch.object(s.eng,'probe',side_effect=AssertionError('No PC inference')), \
             patch.object(s.eng,'get_scene',side_effect=AssertionError('No GPU scene loading')), \
             patch.object(s.S.board_source,'probe',side_effect=AssertionError('No board inference')), \
             patch.object(s.INPUTS,'point',return_value=payload):
            self.assertEqual(s.api_input_point('longkou',0,0),payload)
        with patch.object(s.INPUTS,'point',side_effect=ValueError('CRC mismatch')):
            with self.assertRaises(s.HTTPException) as error:s.api_input_point('longkou',0,0)
            self.assertEqual(error.exception.status_code,409)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=(s.S.source,s.S.board_source,s.S.run,s.S.runs)
        s.S.board_source=b.BoardSource(Path(self.temp.name));s.S.source=s.S.board_source;s.S.run=None;s.S.runs={}
    def tearDown(self):
        s.S.source,s.S.board_source,s.S.run,s.S.runs=self.old;self.temp.cleanup()
    def test_unconfirmed_start_before_scene_or_inference(self):
        with patch.object(s.eng,'get_scene',side_effect=AssertionError('must gate first')):
            with self.assertRaises(ValueError):s.start_run(dict(kind='region',scene='longkou',version='v2',rect=b.RECT))
        self.assertIsNone(s.S.run);self.assertEqual(s.S.runs,{})
    def test_bad_roi_not_clamped_into_allowed_job(self):
        s.S.board_source.authorize('12345678',True)
        with patch.object(s.eng,'get_scene',side_effect=AssertionError('must reject first')):
            for rect in ([0,0,5,3],[-1,0,3,5],[0,0,3,6]):
                with self.assertRaises(ValueError):s.start_run(dict(kind='region',scene='longkou',version='v2',rect=rect))
    def test_source_selection_no_udp_and_no_pc_fallback(self):
        with patch.object(b.socket,'socket',side_effect=AssertionError('No socket on source select')):
            s.set_source(dict(source='board',board_ip='192.168.1.10'))
            with self.assertRaises(ValueError):s.set_source(dict(source='board',board_ip='127.0.0.1'))
            self.assertIs(s.S.source,s.S.board_source)
    def test_pc_probe_blocked_before_engine_call(self):
        with patch.object(s.eng,'probe',side_effect=AssertionError('No PC inference')):
            with self.assertRaises(s.HTTPException) as cm:s.api_probe('longkou','v2',0,0)
        self.assertEqual(cm.exception.status_code,409)
    def test_unimplemented_upload_rejected_synchronously(self):
        with self.assertRaises(ValueError):s.upload(dict(scene='longkou',version='v2'))
    def test_explicit_probe_requires_current_live_session_no_pc_fallback(self):
        with patch.object(s.eng,'probe',side_effect=AssertionError('No PC inference')), patch.object(b.socket,'socket',side_effect=AssertionError('No new peer')):
            with self.assertRaises(s.HTTPException) as cm:s.api_board_probe(99,dict(row=0,col=0))
            self.assertEqual(cm.exception.status_code,409)
    def test_probe_dispatch_only_to_same_board_job(self):
        from types import SimpleNamespace
        job=object();s.S.runs[7]=SimpleNamespace(board_job=job)
        with patch.object(s.S.board_source,'probe',return_value={'state':'queued'}) as fn:
            self.assertEqual(s.api_board_probe(7,dict(row=549,col=399)),{'state':'queued'})
            fn.assert_called_once_with(job,549,399)
    def test_uart_refuses_old_build_before_opening_com(self):
        with patch.object(s.gcs_release,'audited_elf',side_effect=ValueError('ELF is still OLD')), patch.object(s.UART,'start') as start:
            with self.assertRaises(s.HTTPException) as cm:s.api_uart_start(dict(port='COM5',baudrate=115200,confirmed=True))
            self.assertIn('OLD',cm.exception.detail);start.assert_not_called()
    def test_uart_requires_click_confirmation_before_build_audit(self):
        with patch.object(s.gcs_release,'audited_elf') as audit,patch.object(s.UART,'start') as start:
            with self.assertRaises(s.HTTPException):s.api_uart_start(dict(port='COM5',baudrate=115200,confirmed=False))
            audit.assert_not_called();start.assert_not_called()
    def test_uart_new_build_receipt_passed_to_opt_in_capture(self):
        with patch.object(s.gcs_release,'audited_elf',return_value=Path('offline_build_receipt')),patch.object(s.UART,'start',return_value={'active':True}) as start:
            self.assertEqual(s.api_uart_start(dict(port='COM5',baudrate=115200,confirmed=True)),{'active':True})
            start.assert_called_once_with('COM5',115200,True,'offline_build_receipt')
    def test_connect_button_selects_only_idle_board_without_inference(self):
        s.S.source=object()
        with patch.object(s.gcs_release,'audited_elf',return_value=Path('offline_build_receipt')), \
             patch.object(s.UART,'start',return_value={'active':True}) as start, \
             patch.object(b.socket,'socket',side_effect=AssertionError('No UDP')):
            self.assertEqual(s.api_uart_start(dict(port='COM6',baudrate=115200,confirmed=True,connect_board=True)),{'active':True})
            self.assertIs(s.S.source,s.S.board_source)
            start.assert_called_once_with('COM6',115200,True,'offline_build_receipt')
            self.assertIsNone(s.S.run)

    def test_connect_button_never_takes_over_running_or_paused_task(self):
        from types import SimpleNamespace
        for status in ('running','paused'):
            s.S.run=SimpleNamespace(status=status)
            with patch.object(s.gcs_release,'audited_elf') as audit,patch.object(s.UART,'start') as start:
                with self.assertRaises(s.HTTPException):
                    s.api_uart_start(dict(port='COM6',baudrate=115200,confirmed=True,connect_board=True))
                audit.assert_not_called();start.assert_not_called()
        s.S.run=None
        with patch.object(s.S.board_source,'describe',return_value={'active':True}), \
             patch.object(s.UART,'start') as start:
            with self.assertRaises(s.HTTPException):
                s.api_uart_start(dict(port='COM6',baudrate=115200,confirmed=True,connect_board=True))
            start.assert_not_called()

    def test_connect_audit_failure_does_not_change_source(self):
        original=object();s.S.source=original
        with patch.object(s.gcs_release,'audited_elf',side_effect=ValueError('OLD ELF')),patch.object(s.UART,'start') as start:
            with self.assertRaises(s.HTTPException):
                s.api_uart_start(dict(port='COM6',baudrate=115200,confirmed=True,connect_board=True))
            self.assertIs(s.S.source,original);start.assert_not_called()

    def test_reapply_same_source_is_passive_but_switch_during_uart_rejected(self):
        with patch.object(s.UART,'snapshot',return_value={'active':True}),patch.object(s.S.board_source,'close') as close:
            s.set_source(dict(source='board',board_ip='192.168.1.10'))
            close.assert_not_called()
            with self.assertRaises(ValueError):s.set_source(dict(source='pc'))
            with self.assertRaises(ValueError):s.set_source(dict(source='board',board_ip='127.0.0.1'))

    def test_board_summary_unmeasured_and_exact_cells(self):
        import numpy as np
        r=s.Run(1,'region','longkou','v2',b.RECT,np.zeros((15,2)),550,400,'board')
        r.board_job=b.Job(0x12345678,42,7)
        s.S.runs[1]=r;s.S.run=r
        out=r.summary();self.assertIsNone(out['compute_s']);self.assertIsNone(out['energy_j'])
        self.assertEqual(s.api_board_result(1)['cells'],[])
        self.assertEqual(s.api_state()['service'],'gcs-s2c-roi')
        with self.assertRaises(s.HTTPException):s.api_metrics(1)

if __name__=='__main__':unittest.main(verbosity=2)
