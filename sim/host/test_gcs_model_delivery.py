"""Delivery/export/API tests; subprocess/UDP are mocked, no training/device run."""
from pathlib import Path
import copy
import hashlib
import io
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'model')]
import board_link
import board_models
import export_board_candidate
import server as s
from sim.host.test_gcs_upload import candidate

class ModelDeliveryTests(unittest.TestCase):
    def test_existing_closed_loop_exports_are_verified_and_not_overwritten(self):
        for tag,name in [('hold3','longkou_unoverlapping_s0_hold3.pth'),('v3_board','longkou_unoverlapping_s0_hold3_ft30.pth'),('v3ft50_board','longkou_unoverlapping_s0_hold3_ft50.pth')]:
            folder=ROOT/'data/scenes/longkou/weights'/tag;before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
            result=export_board_candidate.export_candidate('longkou',ROOT/'data/ckpt'/name,tag)
            self.assertFalse(result['board_registered']);self.assertIsNone(result['board_activated'])
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()})
        with self.assertRaisesRegex(ValueError,'provenance'):
            export_board_candidate.export_candidate('longkou',ROOT/'data/ckpt/longkou_unoverlapping_s0_hold3_ft30.pth','hold3')
        with self.assertRaises(ValueError):export_board_candidate.export_candidate('longkou',ROOT/'data/ckpt/longkou_unoverlapping_s0_hold3.pth','../escape')

    def test_failed_local_package_save_does_not_consume_boot_or_open_socket(self):
        c,parts=candidate()
        with tempfile.TemporaryDirectory() as tmp:
            source=board_link.BoardSource(Path(tmp),lambda *args:(c,parts));source.authorize('12345678',True)
            with patch.object(Path,'write_bytes',side_effect=OSError('OFFLINE disk full')),patch.object(board_link.socket,'socket',side_effect=AssertionError('No actual UDP')) as sock:
                with self.assertRaisesRegex(OSError,'disk full'):source.request_models('upload','honghu','v1')
                self.assertIsNone(source.session);self.assertIsNone(source.operation);sock.assert_not_called()
                self.assertFalse((Path(tmp)/'boots/12345678.json').exists())

    def test_model_catalog_get_is_passive_and_legacy_directory_is_not_relabelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=s.State(Path(tmp))
            with (patch.object(s,'S',state),patch.object(board_link.socket,'socket',side_effect=AssertionError('No actual UDP')),
                  patch.object(s.eng,'get_scene',side_effect=AssertionError('No cube/model for catalog'))):
                result=s.api_models()
                self.assertTrue(any(c['scene']=='honghu' and c['available'] for c in result['candidates']))
                old=next(c for c in result['candidates'] if c['scene']=='longkou' and c['version']=='v1')
                self.assertTrue(old['available']);self.assertEqual(old['tag'],'v1_board')
                self.assertEqual(result['entries'],[]);self.assertFalse(state.board_source.describe()['active'])
                # The old directory still fails complete SHA provenance. The
                # UI v1 now points to an independent exact-checkpoint export.
                with self.assertRaisesRegex(ValueError,'SHA256'):board_models.load_candidate(s.E.DATA,'longkou','v1')
                self.assertEqual(old['parts'][1]['sha256'],hashlib.sha256((s.E.DATA/'longkou/weights/v1/weights_engine.bin').read_bytes()).hexdigest())
                with self.assertRaises(s.HTTPException):s.api_models_query(dict(confirmed=False))
            info=SimpleNamespace(info=lambda:dict(versions=[]))
            recipe=dict(region=dict(scene='longkou',hold_class=3,region=dict(row0=0,col0=0,size=64),old_test=dict(OA=1.)),ft30=dict(new_test=dict(OA=1.)))
            with patch.object(s.eng,'get_scene',return_value=info),patch.object(s.E,'closed_loop_info',return_value=recipe):
                public=s.api_scene('longkou')['closed_loop']
                self.assertNotIn('old_test',public['region']);self.assertNotIn('ft30',public)

    def test_training_claim_is_synchronous_and_only_candidates_reach_ui(self):
        recipe=dict(region=dict(hold_class=3,region=dict(row0=0,col0=0,size=64)))
        cmd=dict(scene='longkou',base_version='hold3',rect=[0,0,64,64],annotate=30)
        with tempfile.TemporaryDirectory() as tmp:
            state=s.State(Path(tmp)/'history')
            with patch.object(s,'S',state),patch.object(s.E,'closed_loop_info',return_value=recipe),patch.object(s.time,'strftime',return_value='live1011_111111'),patch.object(s.threading,'Thread') as thread:
                s.finetune(cmd);self.assertIsNotNone(state.finetune);s.finetune(cmd)
                self.assertEqual(thread.call_count,1);self.assertFalse(thread.call_args.kwargs['daemon'])
            state.finetune=None;events=[];process=Mock()
            payload=dict(new_ckpt='fixture.pth',new_ckpt_sha256='a'*64,new_test=dict(OA=1.,AA=1.),region=dict(new_oa=1.))
            process.stdout=io.StringIO(json.dumps(payload)+'\n');process.returncode=0;process.poll.return_value=0;process.wait.return_value=0
            def immediate(**kwargs):return SimpleNamespace(start=kwargs['target'])
            version_list=copy.deepcopy(s.E.VERSIONS)
            with (patch.object(s,'S',state),patch.object(s,'ROOT',Path(tmp)),patch.object(s.E,'DATA',Path(tmp)/'data'),
                 patch.object(s.E,'VERSIONS',version_list),patch.object(s.E,'closed_loop_info',return_value=recipe),
                 patch.object(s.time,'strftime',return_value='live1011_111111'),patch.object(s.threading,'Thread',side_effect=immediate),
                 patch.object(s.subprocess,'Popen',return_value=process),patch.object(s,'emit_json',side_effect=events.append),
                 patch.object(board_models,'load_candidate',return_value=dict(wcrc='12345678',provenance=dict(checkpoint_sha256='a'*64)))):
                s.finetune(cmd)
            self.assertIsNone(state.finetune);done=next(e for e in events if e.get('type')=='finetune' and e.get('state')=='done')
            self.assertFalse({'OA','AA','Kappa','new_test','old_test','region'} & (set(done)|set(done['candidate'])))
            self.assertEqual(done['candidate']['source'],'TRAINING_ARTIFACT_NOT_BOARD_RESULT')
            self.assertTrue((Path(tmp)/'build/host/gcs_training/live1011_111111/exit.json').is_file())

if __name__=='__main__':unittest.main()
