"""Offline business fixtures. Never board performance or accuracy claims."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'gcs'), str(ROOT/'tools')]
import board_agri as a


def snapshot(cells=((0, 0, 0), (0, 1, 0x80000001)), task=1, model='v2', **over):
    result = dict(boot_id='12345678', session='0000002a', task=task, scene='longkou',
                  model=model, wcrc='27231983', ack=True, status='stopped', error=None,
                  roi=dict(x=0, y=0, width=4, height=3), total=12, received_pixels=len(cells),
                  cells=[dict(y=y, x=x, class_word=f'{w:08X}', class_id=w & 255,
                              confidence_q16=w >> 16, confidence=(w >> 16)/65536) for y, x, w in cells])
    return {**result, **over}


CLASSES = ['玉米', '水稻', '水体']
PARCELS = [dict(id='p1', name='地块一', pts=[[0, 0], [3, 0], [3, 2], [0, 2]])]


class ResultTests(unittest.TestCase):
    def result(self, **over):
        return a.BoardResult(snapshot(**over), (3, 4), CLASSES)

    def test_only_seen_pixels_count_raw_zero_is_crop_not_no_data(self):
        r = self.result()
        data = a.analyze(r, .5, conf_thr=.5, min_px=1)
        self.assertEqual(data['received_pixels'], 2)
        self.assertEqual([v['pixels'] for v in data['area']], [1, 1, 0])
        self.assertEqual(data['area'][0]['mean_conf'], 0)
        self.assertEqual(data['area'][1]['mean_conf'], .5)
        self.assertEqual(data['area'][0]['area_m2'], .25)
        self.assertEqual(data['coverage'], 2/12)
        self.assertFalse(data['complete_task_coverage'])
        self.assertEqual(data['patches'][0]['area_px'], 1)
        self.assertEqual(int(r.pred[0, 0]), 1)
        self.assertEqual(int(r.pred[2, 3]), 0)
        self.assertEqual(data['prediction_words_seen_sha256'], hashlib.sha256(r.words.tobytes()+r.seen.astype('u1').tobytes()).hexdigest())
        empty = a.analyze(self.result(cells=()), .5)
        self.assertIsNone(empty['area'][0]['share'])
        self.assertEqual(empty['patches'], [])

    def test_corruption_or_failed_task_is_not_business_success(self):
        for over in (dict(ack=False), dict(error='DMA failure', status='error'), dict(integrity_error=True),
                     dict(status='done'), dict(received_pixels=3), dict(cells_included=False),
                     dict(boot_id='00000000'), dict(task=True)):
            with self.subTest(over=over), self.assertRaises(ValueError):self.result(**over)
        for cells in (((0, 0, 0x100),), ((0, 0, 3),), ((3, 0, 0),), ((0, 0, 0), (0, 0, 0))):
            with self.subTest(cells=cells), self.assertRaises(ValueError):self.result(cells=cells)
        bad = snapshot();bad['cells'][0]['confidence'] = .3
        with self.assertRaises(ValueError):a.BoardResult(bad, (3, 4), CLASSES)
        self.assertEqual(self.result(ack=False, accepted_via_info=True).seen.sum(), 2)

    def test_snapshot_is_immutable_and_parameters_are_strict(self):
        snap = snapshot();r = a.BoardResult(snap, (3, 4), CLASSES)
        snap['cells'][0]['class_word'] = '00000002'
        self.assertEqual(r.words[0, 0], 0)
        with self.assertRaises(ValueError):r.words[0, 0] = 1
        for thr, px in ((float('nan'), 1), (-1, 1), (2, 1), (.5, 0), (.5, 1.5), (.5, True)):
            with self.subTest(thr=thr, px=px), self.assertRaises(ValueError):a.analyze(r, .5, thr, px)
        with self.assertRaises(ValueError):a.analyze(r, 0)

    def test_parcels_are_pixel_center_geometry_not_ground_truth(self):
        rows = a.parcel_rows(self.result(), PARCELS, .5, .5)
        p = rows[0]
        self.assertEqual((p['pixels'], p['received_pixels'], p['area_m2']), (6, 2, 1.5))
        self.assertAlmostEqual(p['done'], 1/3)
        self.assertEqual(p['main_c'], 1)  # tied: stable lower class index
        self.assertEqual(p['mix'], .5);self.assertEqual(p['low'], .5)
        outside = [dict(id='p2', name='未处理', pts=[[2, 2], [4, 2], [4, 3], [2, 3]])]
        p = a.parcel_rows(self.result(), outside, .5)[0]
        self.assertEqual(p['received_pixels'], 0)
        self.assertIsNone(p['main']);self.assertIsNone(p['main_share']);self.assertIsNone(p['low'])
        for pts in ([[0, 0], [1, 1]], [[0, 0], [4, 3], [0, 3], [4, 0]],
                    [[-1, 0], [1, 0], [0, 1]], [[0, 0], [float('nan'), 0], [0, 1]]):
            with self.subTest(pts=pts), self.assertRaises(ValueError):
                a.validate_parcels([dict(id='bad', name='bad', pts=pts)], (3, 4))

    def test_compare_common_received_pixels_same_fixed_test_mask(self):
        old = self.result(cells=((0, 0, 0), (0, 1, 1), (1, 0, 2)))
        new = self.result(cells=((0, 0, 1), (0, 1, 1), (2, 3, 0)), task=2, model='new-fixture', wcrc='87654321')
        test = np.zeros((3, 4), 'u1');test[0, :2] = [1, 2]
        c = a.compare(old, new, test, {'manifest_sha256': 'offline-fixture'})
        self.assertEqual((c['common'], c['changed'], c['labeled']), (2, 1, 2))
        self.assertEqual(c['acc_a'], 1.);self.assertEqual(c['acc_b'], .5)
        self.assertEqual(c['transition'][0][1], 1)
        self.assertEqual(c['metrics_a']['n'], c['metrics_b']['n'])
        self.assertFalse(c['complete_task_coverage'])
        self.assertEqual(c['a']['identity']['model'], 'v2')
        self.assertEqual(c['b']['identity']['wcrc'], '87654321')
        c = a.compare(old, new, evaluation_error='missing pinned labels')
        self.assertIsNone(c['acc_a']);self.assertFalse(c['evaluation']['available'])
        with self.assertRaises(ValueError):a.compare(old, old)
        with self.assertRaises(ValueError):a.compare(old, self.result(task=2, scene='honghu'))
        c = a.compare(old, self.result(task=2, cells=((2, 3, 0),)))
        self.assertEqual(c['common'], 0);self.assertIsNone(c['agree'])

    def test_report_zip_is_self_contained_hashed_and_no_training_scores(self):
        r = self.result();data = a.analyze(r, .5)
        ledger = dict(revision=1, parcels=[{**PARCELS[0], 'name':'<script>alert(1)</script>'}])
        report, raw = a.report_bundle(r, data, ledger, .5, ['#000000', '#ff0000', '#00ff00', '#0000ff'],
                                    dict(id=1, scene='longkou', version='v2'), evaluation={'available':False, 'error':'未测'})
        self.assertEqual(report['parcels'][0]['received_pixels'], 2)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            manifest = json.loads(z.read('sha256.json'))
            for name, digest in manifest.items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
            self.assertEqual(len(z.read('words_le_u32.bin')), 48)
            self.assertEqual(z.read('seen_u8.bin').count(b'\x01'), 2)
            html = z.read('report.html').decode()
            self.assertIn('data:image/png;base64,', html)
            self.assertNotIn('<script>', html);self.assertIn('&lt;script&gt;', html)
            self.assertIn('部分覆盖', html);self.assertIn('未测', html)
            self.assertNotIn('old_test', html)


class LedgerTests(unittest.TestCase):
    def test_restart_revision_conflicts_and_corrupt_file_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            store = a.ParcelStore(Path(d));self.assertEqual(store.load('longkou', (3, 4))['revision'], 0)
            doc = store.save('longkou', (3, 4), PARCELS, 0)
            self.assertEqual(doc['revision'], 1)
            self.assertEqual(a.ParcelStore(Path(d)).load('longkou', (3, 4)), doc)
            with self.assertRaises(a.RevisionConflict):store.save('longkou', (3, 4), [], 0)
            self.assertEqual(store.load('honghu', (3, 4))['parcels'], [])
            with self.assertRaises(ValueError):store.load('../escape', (3, 4))
            with self.assertRaises(ValueError):store.load('longkou', (4, 4))
            path = Path(d)/'longkou.json';path.write_text('{bad')
            with self.assertRaises(ValueError):store.save('longkou', (3, 4), [], 1)
            self.assertEqual(path.read_text(), '{bad')

    def test_only_one_concurrent_edit_wins(self):
        with tempfile.TemporaryDirectory() as d:
            store = a.ParcelStore(Path(d));ok=[];bad=[]
            def save():
                try:ok.append(store.save('longkou', (3, 4), PARCELS, 0))
                except a.RevisionConflict as exc:bad.append(str(exc))
            threads = [threading.Thread(target=save) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertEqual((len(ok), len(bad)), (1, 1))


class ServerTests(unittest.TestCase):
    def test_annotation_count_matches_recipe_and_never_uses_test_pixels(self):
        import server as s
        with patch.object(s.eng,'get_scene',side_effect=AssertionError('No PC scene inference')):
            ann=s.api_annotations('longkou',25)
        labels,_=s.board_metrics.load_label_set();pts=np.asarray(ann['points'])
        self.assertEqual(len(pts),25);self.assertTrue(np.all(labels['test'][pts[:,0],pts[:,1]]==0))
        self.assertTrue(np.all(labels['train'][pts[:,0],pts[:,1]]==ann['hold_class']))
        for scene,count in (('honghu',25),('longkou',91),('longkou',True)):
            with self.assertRaises(s.HTTPException):s.api_annotations(scene,count)

    def test_finetune_rejects_wrong_recipe_without_spawning_training(self):
        import server as s
        info=dict(region=dict(hold_class=3,region=dict(row0=1,col0=2,size=64)))
        base=dict(scene='longkou',base_version='hold3',rect=[1,2,64,64],annotate=30)
        with patch.object(s.S,'finetune',None),patch.object(s.E,'closed_loop_info',return_value=info),patch.object(s.threading,'Thread',side_effect=AssertionError('No training')):
            for over in (dict(scene='honghu'),dict(base_version='v2'),dict(rect=[0,0,64,64]),dict(annotate=91),dict(annotate=True),dict(annotate=2.5)):
                with self.subTest(over=over),self.assertRaises(ValueError):s.finetune({**base,**over})

    def test_real_board_routes_never_call_pc_engine_and_report_uses_same_snapshot(self):
        import server as s
        from sim.host.test_gcs_task_verify import fixture
        with tempfile.TemporaryDirectory() as d:
            job, _ = fixture(Path(d));state = s.State(Path(d))
            old = state.runs[9];old.board_job = job
            new = s.Run(10, 'region', 'longkou', 'v2', old.rect, old.coords, 550, 400, 'board')
            snap = job.snapshot();snap['task'] = 3;snap['cells'][0].update(class_word='80000001', class_id=1, confidence_q16=32768, confidence=.5)
            snap['class_counts'][2] -= 1;snap['class_counts'][1] += 1
            new.board_job = SimpleNamespace(snapshot=lambda: copy.deepcopy(snap), out=Path(d)/'task_second', lock=threading.RLock())
            new.status = 'done';state.runs[10] = new
            with patch.object(s, 'S', state), patch.object(s.eng, 'get_scene', side_effect=AssertionError('No PC engine')):
                result = s.api_compare(9, 10)
                self.assertEqual((result['common'], result['changed']), (10, 1))
                self.assertEqual(result['a']['identity']['task'], 2)
                analyzed = s.api_analysis(9, .6, 1)
                self.assertEqual(sum(x['pixels'] for x in analyzed['area']), 10)
                ledger = s.api_parcels('longkou')
                parcel = dict(id='edge', name='边角', pts=[[395, 548], [400, 548], [400, 550], [395, 550]])
                ledger = s.api_save_parcels('longkou', dict(revision=ledger['revision'], parcels=[parcel]))
                self.assertEqual(s.api_run_parcels(9)['rows'][0]['received_pixels'], 10)
                export = s.api_agri_report(9, dict(conf_thr=.6, min_px=1, ledger_revision=ledger['revision'], compare=10))
                rep = export['report']
                self.assertEqual(rep['analysis']['prediction_words_seen_sha256'], rep['comparison']['a']['prediction_words_seen_sha256'])
                report_id = export['download'].split('/')[-1].split('.')[0]
                response = s.api_agri_report_zip(9, report_id)
                self.assertTrue(Path(response.path).is_file())
                with self.assertRaises(s.HTTPException):s.api_agri_report_zip(9, '../escape')
                with self.assertRaises(s.HTTPException):s.api_agri_report(9, dict(ledger_revision=0))
                with self.assertRaises(s.HTTPException):s.api_compare(9, 9)
                job.error = 'keep error'
                with self.assertRaises(s.HTTPException):s.api_analysis(9)


if __name__ == '__main__':unittest.main(verbosity=2)
