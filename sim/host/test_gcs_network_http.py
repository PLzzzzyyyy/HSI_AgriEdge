"""Direct HTTP/control handlers: network identity never consults legacy UART."""
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from unittest.mock import patch
from sim.host import test_gcs_network_records as records
from sim.host import test_gcs_network_owner as owner

s=records.s

class NetworkHttp(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        state=s.State(self.root/'history')
        source,_=owner.NetworkOwner.source(self,self.root)
        state.board_source=state.source=source
        self.source=source
        for p in (patch.object(s,'S',state),patch.object(s,'emit_json'),patch.object(s,'log'),
                  patch.object(s.board_link.socket,'socket',side_effect=AssertionError('HTTP test must not open UDP'))):
            p.start();self.addCleanup(p.stop)

    def test_network_upload_does_not_consult_even_failed_same_boot_uart(self):
        with (patch.object(s.UART,'snapshot',side_effect=AssertionError('Network upload must not read UART')),
              patch.object(self.source,'request_models',return_value={'state':'queued'}) as request):
            self.assertEqual(s.upload(dict(scene='longkou',version='v2',activate=True)),{'state':'queued'})
            self.assertEqual(request.call_args.args,('upload','longkou','v2'))
            self.assertTrue(request.call_args.kwargs['activate'])

    def test_network_start_has_no_uart_guard_or_uart_evidence_attachment(self):
        with (patch.object(s.UART,'snapshot',side_effect=AssertionError('Network START must not read UART')),
             patch.object(s.eng,'get_scene',return_value=SimpleNamespace(H=550,W=400)),
              patch.object(self.source,'start') as start):
            s.start_run(dict(kind='region',scene='longkou',version='v2',rect=[549,399,1,1]))
            self.assertIsNone(s.S.run.uart_evidence)
            self.assertIs(start.call_args.args[0],s.S.run)

    def recovery_run(self):
        job,_=records.network_fixture(self.root/'job')
        run=SimpleNamespace(board_job=job,id=1,source='board')
        s.S.runs={1:run}
        cmd={k:job.snapshot(False)[k] for k in ('boot_id','session','task','wcrc')}
        cmd['confirmed']=True
        return run,cmd

    def test_network_recovery_uses_saved_transport_before_owner_is_restored(self):
        (self.root/'job').mkdir();run,cmd=self.recovery_run()
        self.source.network_startup=None
        with (patch.object(s.UART,'snapshot',side_effect=AssertionError('Network recovery must not read UART')),
             patch.object(s.gcs_release,'audited_elf',return_value=self.source.build_evidence),
             patch.object(s,'run_callbacks',return_value=(None,None,None)),
              patch.object(self.source,'recover',return_value={'recovering':True}) as recover):
            self.assertEqual(s.api_board_recover(1,cmd),{'recovering':True})
            self.assertIs(recover.call_args.args[0],run.board_job)
            self.assertEqual(self.source.release_id,owner.BUILD['release_id'])

    def test_failed_legacy_uart_still_blocks_upload_start_and_recovery(self):
        self.source.network_startup=None
        receipt=dict(error='retained legacy failure',boot_id='12345678',evidence='legacy',active=False)
        with (patch.object(s.UART,'snapshot',return_value=receipt),
             patch.object(self.source,'request_models') as request,
              patch.object(self.source,'start') as start):
            with self.assertRaisesRegex(ValueError,'UART'):s.upload(dict(scene='longkou',version='v2'))
            with self.assertRaisesRegex(ValueError,'UART'):s.start_run(dict(kind='region',scene='longkou',version='v2'))
            request.assert_not_called();start.assert_not_called()
        (self.root/'job').mkdir();run,cmd=self.recovery_run();run.board_job.host_run['network_startup']=None
        with patch.object(s.UART,'snapshot',return_value=receipt),patch.object(self.source,'recover') as recover:
            with self.assertRaises(s.HTTPException) as failed:s.api_board_recover(1,cmd)
            self.assertEqual(failed.exception.status_code,409);self.assertIn('UART',failed.exception.detail)
            recover.assert_not_called()

    def test_network_transport_does_not_bypass_health_confirmation_or_release_gate(self):
        self.source.healthy=False
        with patch.object(s.UART,'snapshot',side_effect=AssertionError('No legacy fallback')):
            with self.assertRaises(ValueError):s.upload(dict(scene='longkou',version='v2'))
        (self.root/'job').mkdir();run,cmd=self.recovery_run()
        with (patch.object(s.UART,'snapshot',side_effect=AssertionError('No legacy fallback')),
             patch.object(s.gcs_release,'audited_elf',side_effect=ValueError('OFFLINE release mismatch')) as audit,
              patch.object(self.source,'recover') as recover):
            cmd['confirmed']=False
            with self.assertRaises(s.HTTPException):s.api_board_recover(1,cmd)
            audit.assert_not_called()
            cmd['confirmed']=True
            with self.assertRaises(s.HTTPException) as failed:s.api_board_recover(1,cmd)
            self.assertIn('release mismatch',failed.exception.detail);recover.assert_not_called()

if __name__=='__main__':unittest.main()
