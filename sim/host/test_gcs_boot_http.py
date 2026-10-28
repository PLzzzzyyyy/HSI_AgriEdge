"""ASGI-only explicit Ethernet connection; no listener, board or App Build."""
from pathlib import Path
import sys,tempfile,unittest,json
from unittest.mock import patch
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'gcs'))
import server as s

class SdHttp(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        (Path(self.tmp.name)/'synthetic_audit.json').write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',app_id='gcs_r1_abi4',release_id='1'*64,source_set_sha256='2'*64,hardware_xsa_sha256='3'*64)))
        state=s.State(Path(self.tmp.name)/'history')
        self.patches=[patch.object(s,'S',state),patch.object(s.UART,'snapshot',return_value={'active':False}),
            patch.object(s,'emit_json'),patch.object(s.gcs_release,'audited_elf',return_value=Path(self.tmp.name)/'synthetic_audit.json'),
            patch.object(s.board_boot,'connect',return_value=dict(boot_id='12345678',ready=True,evidence='OFFLINE/startup',independent_cold_start_verified=False)),
            patch.object(s.UART,'start',side_effect=AssertionError('UART forbidden')),
            patch.object(state.board_source,'_launch',side_effect=AssertionError('UDP owner forbidden'))]
        self.mocks=[p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)
        self.client=TestClient(s.app);self.addCleanup(self.client.close)
    def test_get_and_unconfirmed_post_are_passive(self):
        self.assertEqual(self.client.get('/api/state').status_code,200)
        for body in ({},{'confirmed':False},{'confirmed':1}):
            self.assertEqual(self.client.post('/api/board/sd_connect',json=body).status_code,409)
        self.mocks[3].assert_not_called();self.mocks[4].assert_not_called()
    def test_explicit_idle_connect_only_authorizes_new_identity(self):
        response=self.client.post('/api/board/sd_connect',json={'confirmed':True})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertEqual(result['source']['boot_id'],'12345678')
        self.assertFalse(result['uart_opened']);self.assertFalse(result['discovery']['independent_cold_start_verified'])
        self.assertTrue(result['source']['authorized']);self.assertFalse(result['source']['active'])
        self.assertIsNone(s.S.board_source.session);self.assertIsNone(s.S.run)
        self.mocks[3].assert_called_once();self.mocks[4].assert_called_once()
    def test_uart_and_model_task_owner_cannot_be_replaced(self):
        for uart,active in ((True,False),(False,True)):
            self.mocks[1].return_value={'active':uart}
            with patch.object(s.S.board_source,'describe',return_value={'active':active}):
                response=self.client.post('/api/board/sd_connect',json={'confirmed':True})
            self.assertEqual(response.status_code,409)
        self.mocks[3].assert_not_called();self.mocks[4].assert_not_called()
    def test_bad_elf_gate_stops_before_discovery(self):
        self.mocks[3].side_effect=ValueError('OFFLINE stale App/ELF')
        response=self.client.post('/api/board/sd_connect',json={'confirmed':True})
        self.assertEqual(response.status_code,409);self.mocks[4].assert_not_called()
    def test_discovery_failure_clears_old_unused_authorization(self):
        s.S.board_source.authorize('87654321',True)
        self.mocks[4].side_effect=ValueError('OFFLINE invalid INFO')
        response=self.client.post('/api/board/sd_connect',json={'confirmed':True})
        self.assertEqual(response.status_code,409)
        self.assertIsNone(s.S.board_source.boot);self.assertIsNone(s.S.board_source.session)
    def test_pc_persistent_no_reuse_gate_is_not_bypassed(self):
        boots=s.S.board_source.root/'boots';boots.mkdir(parents=True)
        (boots/'12345678.json').write_text('{}')
        response=self.client.post('/api/board/sd_connect',json={'confirmed':True})
        self.assertEqual(response.status_code,409)
        self.assertIsNone(s.S.board_source.boot);self.assertIsNone(s.S.board_source.session)

    def test_jtag_and_sd_are_explicit_and_do_not_claim_cold_boot(self):
        for method in ('jtag','sd'):
            response=self.client.post('/api/board/connect',json={'confirmed':True,'boot_method':method})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['ready']);self.assertFalse(response.json()['uart_opened'])
            self.assertEqual(self.mocks[4].call_args.args[3],method)
            self.assertEqual(response.json()['source']['connection_transport'],'ethernet')
        for method in (None,'JTAG','cold',1):
            self.assertEqual(self.client.post('/api/board/connect',json={'confirmed':True,'boot_method':method}).status_code,409)
        self.assertEqual(self.mocks[4].call_count,2)

    def test_pending_scan_is_not_authorization_or_an_automatic_retry(self):
        self.mocks[4].return_value=dict(ready=False,result='STARTUP_PENDING',boot_id='12345678',
            evidence='OFFLINE/startup',startup={'state':'scanning_models','scan_progress':{'bytes':4096}})
        response=self.client.post('/api/board/connect',json={'confirmed':True,'boot_method':'jtag'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['ready']);self.assertFalse(response.json()['source']['authorized'])
        for _ in range(3):self.client.get('/api/state')
        self.mocks[4].assert_called_once();self.assertIsNone(s.S.board_source.session)

if __name__=='__main__':unittest.main()
