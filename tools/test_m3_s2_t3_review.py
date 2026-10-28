"""Focused checks for report-memory reconciliation, not hardware tests."""
import unittest
import json
import xml.etree.ElementTree as ET
from tempfile import TemporaryDirectory
from pathlib import Path
from review_m3_s2_t3 import memory_rows, memory_inventory, group_memories, named_loop_report
from run_m3_s2_synth import ROOT, continuation_blockers, scheduler_report


class MemoryReviewTests(unittest.TestCase):
    def fixture(self, storage=3456):
        return ('* Memory:\n'
            '| Memory | Module | BRAM_18K | FF | LUT | URAM | Words | Bits | Banks | W*Bits*Banks |\n'
            '|mem_ob_V_0_0_U|engine_task_mem_ob_V_0_0|1|0|0|0|432|8|1|%d|\n'
            '|Total| |1|0|0|0|432|8|1|3456|\n* FIFO:\n') % storage

    def test_named_bank_not_total(self):
        rows = memory_rows(self.fixture())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['banks'], 1)
        self.assertEqual(rows[0]['storage_bits'], 3456)

    def test_storage_mismatch_rejected(self):
        with self.assertRaises(AssertionError):
            memory_rows(self.fixture(777))

    def test_unknown_table_not_zero_bank_pass(self):
        with self.assertRaises(AssertionError):
            memory_rows('* Memory:\nN/A\n* FIFO:')

    def test_worker_memory_not_lost_when_owner_changes(self):
        row = memory_rows(self.fixture())[0]
        row.update(name='w_mem_ob_V_0_0_U', owner='core_service')
        groups = group_memories([row], required=('mem_ob',))
        self.assertEqual(groups['mem_ob']['owners'], ['core_service'])
        self.assertEqual(groups['mem_ob']['storage_bits'], 3456)

    def test_empty_named_memory_group_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'mem_wm12'):
            group_memories(memory_rows(self.fixture()), required=('mem_ob', 'mem_wm12'))

    def test_duplicate_memory_owners_rejected(self):
        a = dict(memory_rows(self.fixture())[0], owner='engine_task')
        b = dict(a, name='w_mem_ob_V_0_0_U', owner='core_service')
        with self.assertRaisesRegex(AssertionError, 'multiple owners'):
            group_memories([a, b], required=('mem_ob',))

    def test_project_loop_must_be_named_not_local_ii1(self):
        with TemporaryDirectory() as temp:
            d = Path(temp)
            p = d / 'run_csynth.xml'
            p.write_text('<r><SummaryOfLoopLatency><init_loop><PipelineII>1</PipelineII>'
                         '</init_loop></SummaryOfLoopLatency></r>')
            with self.assertRaisesRegex(AssertionError, 'project_loop'):
                named_loop_report(d, 'project_loop')
            p.write_text(p.read_text().replace('init_loop', 'project_loop'))
            owner, summary = named_loop_report(d, 'project_loop')
            self.assertEqual(owner, p)
            self.assertEqual(summary['pipeline_ii'], '1')
            (d / 'duplicate_csynth.xml').write_text(p.read_text())
            with self.assertRaisesRegex(AssertionError, 'uniquely'):
                named_loop_report(d, 'project_loop')

    def test_actual_t3_tool_success_is_not_g2_pass(self):
        base = ROOT / 'report/m3_g2_t3/20261008_t3_r1/20261008_t3_r1'
        result = json.loads((base / 'results.json').read_text())[0]
        self.assertTrue(result['synthesis_completed'])
        reports = base / '8p1_pack/reports'
        top = reports / 's2_engine_csynth.xml'
        _, tree = scheduler_report(top)
        issues = continuation_blockers(ET.parse(top), (base / '8p1_pack/synthesis.log').read_text(), tree)
        self.assertEqual(issues, ['HLS estimate requires review: LUT 201049 > 117120',
                                 'scheduler II=63 exceeds fixed II=1 screen'])

    def test_actual_t3_ob_bank_geometry(self):
        p = ROOT / 'report/m3_g2_t3/20261008_t3_r1/20261008_t3_r1/8p1_pack/reports/engine_task_csynth.rpt'
        rows = [r for r in memory_rows(p.read_text()) if r['name'].startswith('mem_ob_')]
        self.assertEqual(len(rows), 42)
        self.assertEqual(sum(r['bram18'] for r in rows), 42)
        self.assertEqual({(r['words'], r['bits'], r['banks']) for r in rows}, {(432, 8, 1)})

    def test_actual_r5_worker_hierarchy_is_not_empty_or_local_ii1_pass(self):
        reports = ROOT / 'report/m3_worker/20261008_t3_fix_r5/synthesis/20261008_t3_fix_r5/8p1_pack/reports'
        rows = memory_inventory(reports)
        groups = group_memories(rows)
        self.assertEqual(groups['mem_ob']['owners'], ['core_service'])
        self.assertEqual(groups['mem_ob']['instances'], 42)
        self.assertEqual(groups['projection_t1']['owners'], ['run'])
        self.assertEqual(groups['mem_head']['owners'], ['engine_task'])
        self.assertFalse(any('returned_value' in r['name'] for r in rows))
        project, summary = named_loop_report(reports, 'project_loop')
        main, scheduler = named_loop_report(reports, 'schedule_loop')
        self.assertNotEqual(main, project)
        self.assertEqual(summary['pipeline_ii'], '14')
        self.assertEqual(scheduler['pipeline_ii'], '64')


if __name__ == '__main__':
    unittest.main(verbosity=2)
