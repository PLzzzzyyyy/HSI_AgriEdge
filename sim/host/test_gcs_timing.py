"""Raw UART phase receipt tests. All durations/CLASS are synthetic fixtures."""
from pathlib import Path
import copy
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
import json
import io
import zipfile
import os
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_timing as timing
import gcs_task_verify
from sim.host.test_gcs_model_business import fixture

def phase_text():
    phases=dict(setup=300,step=5000,probe=200,results=60,display=150,rows=80,pump=120,model=50,control=40,wait_service=250)
    text='S2C TASK_CLOCK session=0000002a task=7 elapsed_us=10000 accounted_us=6000 other_us=4000 valid=1\n'
    for name,us in phases.items():text+=f'S2C TASK_PHASE session=0000002a task=7 part={name} calls=1 us={us}\n'
    return text

class TimingTests(unittest.TestCase):
    def test_complete_raw_receipt_correlates_task_and_preserves_nested_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,uart=fixture(Path(tmp),'honghu');text=uart.read_text()+phase_text();uart.write_text(text)
            result=timing.from_snapshot(job.snapshot(),text)
            self.assertTrue(result['available']);self.assertEqual(result['accounted_us'],6000)
            self.assertEqual(result['other_us'],4000);self.assertEqual(result['wait_service']['us'],250)
            self.assertFalse(result['pure_pl_available']);self.assertFalse(result['internal_ps_pl_split_available'])
            self.assertEqual(sum(p['us'] for p in result['phases']),6000) # service is a subset, not a tenth non-overlap phase
            report=gcs_task_verify.verify(job.out,uart);self.assertTrue(report['phase_timing']['available'])
            self.assertEqual(report['phase_timing']['identity']['wcrc'],job.audit.identity['wcrc'])

    def test_missing_legacy_partial_clock_or_other_model_is_not_a_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,uart=fixture(Path(tmp),'longkou');text=uart.read_text()
            self.assertFalse(timing.from_snapshot(job.snapshot(),text)['available'])
            old=job.snapshot();old['model_lifecycle']=False
            self.assertFalse(timing.from_snapshot(old,text+phase_text())['available'])
            running=job.snapshot();running['status']='running'
            self.assertFalse(timing.from_snapshot(running,text+phase_text())['available'])
            self.assertFalse(timing.from_snapshot(job.snapshot(),text+phase_text().replace('valid=1','valid=0'))['available'])
            wrong=job.snapshot();wrong['wcrc']='12345679'
            with self.assertRaisesRegex(ValueError,'identity'):timing.from_snapshot(wrong,text+phase_text())

    def test_duplicate_missing_overflow_bad_sum_and_compute_disagreement_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,uart=fixture(Path(tmp),'hanchuan');base=uart.read_text();good=phase_text()
            bad=[good+good.splitlines()[1]+'\n',good.replace('part=probe','part=unknown'),
                 good.replace('accounted_us=6000','accounted_us=6001'),good.replace('elapsed_us=10000','elapsed_us=9999'),
                 good.replace('part=step calls=1 us=5000','part=step calls=0 us=5000'),
                 good.replace('part=step calls=1 us=5000','part=step calls=1 us=5001'),
                 good.replace('part=wait_service calls=1 us=250','part=wait_service calls=1 us=10001'),
                 good.replace('elapsed_us=10000','elapsed_us=18446744073709551616'),
                 '\n'.join(good.splitlines()[:-1])+'\n']
            for text in bad:
                with self.subTest(text=text),self.assertRaises(ValueError):timing.from_snapshot(job.snapshot(),base+text)

    def test_api_and_report_read_saved_uart_only_and_do_not_reuse_old_result(self):
        import server as s
        import board_agri
        with tempfile.TemporaryDirectory() as tmp:
            job,uart=fixture(Path(tmp),'honghu');uart.write_text(uart.read_text()+phase_text());job.host_run['uart_evidence']=tmp
            run=SimpleNamespace(board_job=job)
            with patch.object(s,'_run',return_value=run),patch('serial.Serial',side_effect=AssertionError('No COM access')),patch.object(s.board_link.socket,'socket',side_effect=AssertionError('No UDP')):
                good=s.api_task_timing(1);self.assertTrue(good['available'])
                spec=s.business_metadata('honghu');result=board_agri.BoardResult(job.snapshot(),spec['shape'],spec['classes'])
                analysis=board_agri.analyze(result,spec['gsd_m'],.6,1)
                report,raw=board_agri.report_bundle(result,analysis,dict(revision=0,parcels=[]),spec['gsd_m'],spec['palette'],dict(id=1),phase_timing=good)
                self.assertTrue(report['phase_timing']['available'])
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(json.loads(archive.read('phase_timing.json')),good)
                    self.assertIn('非纯PL',archive.read('report.html').decode('utf-8'))
                    if os.environ.get('GCS_PHASE_ARTIFACTS'):
                        out=Path(os.environ['GCS_PHASE_ARTIFACTS']).resolve()
                        if not out.is_relative_to((ROOT/'build/host').resolve()):raise ValueError('Fixture output outside build/host')
                        out.mkdir(parents=True,exist_ok=True)
                        page=archive.read('report.html').decode('utf-8').replace('<body>',
                            '<body><p style="padding:12px;background:#7f1d1d;color:white">OFFLINE SYNTHETIC FIXTURE — NOT BOARD EVIDENCE</p>',1)
                        (out/'preview.html').write_text(page,encoding='utf-8')
                        (out/'phase_timing.json').write_bytes(archive.read('phase_timing.json'))
                        (out/'report_fixture.zip').write_bytes(raw)
                uart.write_text(uart.read_text().replace('accounted_us=6000','accounted_us=6001'))
                bad=s.api_task_timing(1);self.assertFalse(bad['available']);self.assertNotIn('phases',bad)

if __name__=='__main__':unittest.main()
