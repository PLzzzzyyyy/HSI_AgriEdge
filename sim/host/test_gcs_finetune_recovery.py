'''Offline recovery regression: no trainer, network, GUI or production fixture.'''
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scipy.io import savemat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import gcs_finetune_recovery as r


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        parent = (ROOT / 'build/host/gcs_closed_loop_recovery_01/testtmp').resolve()
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.tmp.name).resolve()
        self.assertTrue(self.root.is_relative_to(parent))
        self.addCleanup(self.tmp.cleanup)
        self.base, self.live, self.report = [self.root / n for n in ('base', 'live', 'report')]
        self.tag = 'live1012_093738'
        self.out = self.live / 'data/closed_loop/longkou/runs' / self.tag
        self.ev = self.live / 'build/host/gcs_training' / self.tag
        self.ckpt = self.live / f'data/ckpt/longkou_unoverlapping_s0_hold3_ft30_{self.tag}.pth'
        self.ckpt.parent.mkdir(parents=True)
        self.ckpt.write_bytes(b'existing trained weights')
        self.out.mkdir(parents=True)
        self.bl = self.base / 'data/closed_loop/longkou'
        self.bl.mkdir(parents=True)
        old = self.base / 'data/ckpt/longkou_unoverlapping_s0_hold3.pth'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'registered old checkpoint')
        self.gt = np.zeros((550, 400), dtype=np.uint8)
        self.gt[120:152, 20:84] = 3
        self.gt[152:184, 20:84] = 4
        train, test = np.zeros_like(self.gt), np.zeros_like(self.gt)
        for c in range(1, 10):
            train[400 + c, :100] = c; self.gt[400 + c, :100] = c
            test[450 + c, 0] = c; self.gt[450 + c, 0] = c
        self.paths = {}
        for name, filename, array in [('gt', 'gt.mat', self.gt), ('train', 'Train100.mat', train), ('test', 'Test100.mat', test)]:
            self.paths[name] = self.base / filename
            savemat(self.paths[name], {'values': array})
        self.paths['cube'] = self.base / 'cube.mat'
        self.paths['cube'].write_bytes(b'not opened by fixture evaluation')
        self.gt[120:184, 20:84].tofile(self.bl / 'gt_region.bin')
        np.full((64, 64), 4, np.uint8).tofile(self.bl / 'pred_old_region.bin')
        self.gt[120:184, 20:84].tofile(self.out / 'pred_new_region_ft30.bin')
        info = dict(scene='longkou', model='unoverlapping', seed=0, hold_class=3,
                    official_train='Train100.mat', official_test='Test100.mat',
                    region=dict(row0=120, col0=20, size=64, hold_pixels=2048),
                    old_ckpt=str(old), old_ckpt_sha256=r.sha(old), old_train=720, old_val=80,
                    old_region_oa=0.5, old_region_hold_recall=0.,
                    old_region_pred_hist=[0, 0, 0, 0, 4096, 0, 0, 0, 0, 0], old_test=dict(OA=0.9))
        put(self.bl / 'region.json', info)
        put(self.live / 'data/closed_loop/longkou/region.json', info)
        pts = np.argwhere(train == 3)
        order = np.lexsort((np.linalg.norm(pts - [152, 52], axis=1), np.ones(len(pts), dtype=bool)))
        put(self.out / 'annotations_30.json', dict(scene='longkou', hold_class=3,
            source='Train100.mat', inside_region=0, points=pts[order][:30].tolist()))
        put(self.ev / 'command.json', dict(argv=['python.exe', '-u', str(self.live / 'model/finetune_region.py'),
            'finetune', '--scene', 'longkou', '--hold-class', '3', '--annotate', '30',
            '--weights-version', self.tag, '--run-tag', self.tag], cwd=str(self.live),
            scene='longkou', base_version='hold3', annotate=30, rect=[120, 20, 64, 64]))
        put(self.ev / 'exit.json', dict(exit=1, seconds=190.22))
        self.log = self.ev / 'training.log'
        self.log.write_text(''.join(f'ep {ep:4d} loss 0.1000 val_oa 0.9556 best 0.9556@15 {ep}s\n'
            for ep in range(5, 31, 5)) + 'FileNotFoundError: pred_old_region.bin\n', encoding='utf-8')
        put(self.live / 'data/scenes/longkou/weights/hold3/board_model.json',
            dict(scene='longkou', tag='hold3', checkpoint_sha256=r.sha(old)))
        for name in r.SOURCES:
            for root in (self.base, self.live):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# fixture: ' + name + '\n', encoding='utf-8')
        self.originals = {p: p.read_bytes() for p in (self.ckpt, self.log, self.ev / 'exit.json',
            self.ev / 'command.json', self.out / 'pred_new_region_ft30.bin', self.out / 'annotations_30.json')}
        mock = patch.object(r, 'scene_files', return_value=self.paths)
        mock.start(); self.addCleanup(mock.stop)
        self.evaluations = 0

    def evaluate(self, plan):
        self.evaluations += 1
        return dict(metrics=dict(OA=1., AA=1., Kappa=1., per_class=[1.] * 9),
                    count=9, device='offline fixture', seconds=0.), bytes(range(1, 10))

    def export(self, plan):
        return dict(scene='longkou', tag=self.tag, wcrc='12345678',
                    provenance=dict(checkpoint_sha256=r.sha(self.ckpt)),
                    board_registered=False, board_persisted=None, board_activated=None)

    def recover(self, **overrides):
        return r.recover(self.live, self.base, self.tag, self.report,
            evaluate=overrides.get('evaluate', self.evaluate), export=overrides.get('export', self.export))

    def preserved(self):
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw, str(path))

    def test_recovers_only_offline_candidate_and_preserves_failure(self):
        result = self.recover()
        self.assertTrue(result['recovery']['training_reused'])
        self.assertFalse(result['recovery']['running_service_catalog_updated'])
        self.assertEqual(result['region']['new_oa'], 1.)
        self.assertEqual(result['region']['changed_pixels'], 2048)
        self.assertIsNone(result['seconds_train']); self.assertIsNone(result['best_val'])
        self.assertEqual(result['best_val_reported'], 0.9556)
        for name in ('gt_region.bin', 'pred_old_region.bin'):
            self.assertEqual((self.live / 'data/closed_loop/longkou' / name).read_bytes(), (self.bl / name).read_bytes())
        self.assertEqual(self.evaluations, 1); self.preserved()

    def test_finished_recovery_is_noop(self):
        first = self.recover()
        second = self.recover(evaluate=lambda _: self.fail('no duplicate evaluation'),
                              export=lambda _: self.fail('no duplicate export'))
        self.assertEqual(first, second); self.preserved()

    def test_export_failure_keeps_evaluation_for_resume(self):
        def fail(_): raise OSError('fixture export disk failure')
        with self.assertRaisesRegex(OSError, 'disk failure'): self.recover(export=fail)
        self.assertTrue((self.report / 'test_evaluation.json').exists())
        self.assertFalse((self.out / 'finetune_30.json').exists())
        self.recover(evaluate=lambda _: self.fail('reuse saved evaluation'))
        self.assertEqual(self.evaluations, 1); self.preserved()

    def test_rejects_old_checkpoint_mismatch_before_writes(self):
        (self.base / 'data/ckpt/longkou_unoverlapping_s0_hold3.pth').write_bytes(b'wrong weights')
        with self.assertRaisesRegex(ValueError, 'checkpoint'): self.recover()
        self.assertFalse((self.live / 'data/closed_loop/longkou/gt_region.bin').exists())
        self.assertEqual(self.evaluations, 0)

    def test_rejects_raw_gt_mismatch(self):
        self.gt[120, 20] = 4; savemat(self.paths['gt'], {'values': self.gt})
        with self.assertRaisesRegex(ValueError, 'GT'): self.recover()
        self.assertEqual(self.evaluations, 0)

    def test_rejects_different_runtime_raw_inputs(self):
        wrong = self.live / 'wrong_cube.mat'; wrong.write_bytes(b'another dataset')
        runtime_paths = dict(self.paths, cube=wrong)
        with patch.object(r, 'scene_files', side_effect=lambda root: runtime_paths if root == self.live else self.paths):
            with self.assertRaisesRegex(ValueError, 'raw input'): self.recover()
        self.assertEqual(self.evaluations, 0)

    def test_rejects_annotation_leakage(self):
        path = self.out / 'annotations_30.json'; annotation = json.loads(path.read_text())
        annotation['points'][0] = [450, 0]; put(path, annotation)
        with self.assertRaisesRegex(ValueError, 'annotation'): self.recover()
        self.assertEqual(self.evaluations, 0)

    def test_rejects_incomplete_training(self):
        self.log.write_text('ep 5 loss 0.1 val_oa 0.9 best 0.9@5 7s\nFileNotFoundError: pred_old_region.bin\n')
        with self.assertRaisesRegex(ValueError, 'completed'): self.recover()
        self.assertEqual(self.evaluations, 0)

    def test_conflicting_target_is_not_overwritten(self):
        target = self.live / 'data/closed_loop/longkou/gt_region.bin'; target.write_bytes(b'other session data')
        with self.assertRaisesRegex(ValueError, 'overwrite'): self.recover()
        self.assertEqual(target.read_bytes(), b'other session data'); self.assertEqual(self.evaluations, 0)

    def test_rejects_path_escape_and_source_drift(self):
        with self.assertRaises(ValueError): r.recover(self.live, self.base, '../escape', self.report)
        (self.live / 'model/finetune_region.py').write_text('# different defaults\n')
        with self.assertRaisesRegex(ValueError, 'source'): self.recover()
        self.assertEqual(self.evaluations, 0)

    def test_changed_saved_prediction_invalidates_receipt(self):
        self.recover()
        path = self.out / 'pred_new_region_ft30.bin'; raw = bytearray(path.read_bytes()); raw[0] = 4; path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'fingerprint'): self.recover()
        self.assertEqual(self.evaluations, 1)


if __name__ == '__main__': unittest.main()
