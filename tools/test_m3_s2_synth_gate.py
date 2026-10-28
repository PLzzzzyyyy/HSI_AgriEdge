"""Focused regression for a successful tool exit that must NOT launch P2."""
from pathlib import Path
import unittest
import tempfile
import xml.etree.ElementTree as ET
from run_m3_s2_synth import continuation_blockers, scheduler_report, ROOT
from audit_m3_s2_synth import audit

def fixture(used=5,available=10,ii='1'):
    root=ET.Element('Report');area=ET.SubElement(root,'AreaEstimates')
    u=ET.SubElement(area,'Resources');a=ET.SubElement(area,'AvailableResources')
    for name in ('LUT','FF','DSP','BRAM_18K','URAM'):
        ET.SubElement(u,name).text=str(used);ET.SubElement(a,name).text=str(available)
    loops=ET.SubElement(root,'SummaryOfLoopLatency')
    main=ET.SubElement(loops,'VITIS_LOOP_308_4')
    ET.SubElement(main,'TripCount').text='undef'
    if ii is not None:ET.SubElement(main,'PipelineII').text=ii
    return ET.ElementTree(root)

class GateTests(unittest.TestCase):
    def test_outlined_block_scheduler_is_discovered(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);root=fixture();root.getroot().remove(root.find('.//SummaryOfLoopLatency'))
            root.write(p/'s2_engine_csynth.xml')
            child=fixture();child.find('.//SummaryOfLoopLatency')[0].tag='engine_body_schedule_loop'
            child.write(p/'Block_split2_proc45_csynth.xml')
            report,t=scheduler_report(p/'s2_engine_csynth.xml')
            self.assertEqual(report.name,'Block_split2_proc45_csynth.xml')
            self.assertEqual(continuation_blockers(root,'',t),[])
    def test_duplicate_named_schedulers_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);root=fixture();root.write(p/'s2_engine_csynth.xml')
            child=fixture();child.find('.//SummaryOfLoopLatency')[0].tag='schedule_loop'
            child.write(p/'one_csynth.xml');child.write(p/'two_csynth.xml')
            report,t=scheduler_report(p/'s2_engine_csynth.xml')
            self.assertIsNone(report)
            self.assertIn('scheduler loop not uniquely identified',continuation_blockers(root,'',t))
    def test_named_scheduler_excludes_cleanup_drain(self):
        t=fixture();loop=t.find('.//SummaryOfLoopLatency')[0];loop.tag='schedule_loop'
        other=ET.SubElement(t.find('.//SummaryOfLoopLatency'),'math_drain')
        ET.SubElement(other,'TripCount').text='undef'
        self.assertEqual(continuation_blockers(t,''),[])
    def test_dataflow_top_uses_child_schedule_but_whole_top_resources(self):
        top=fixture(11,10);top.getroot().remove(top.find('.//SummaryOfLoopLatency'))
        issues=continuation_blockers(top,'',fixture(ii='3'))
        self.assertEqual(len(issues),6)
        self.assertIn('scheduler II=3 exceeds fixed II=1 screen',issues)
    def test_completed_but_slow_pipeline_cannot_advance(self):
        self.assertIn('scheduler II=2 exceeds fixed II=1 screen',continuation_blockers(fixture(ii='2'),''))
    def test_final_ii_one_beats_transient_scheduler_warnings(self):
        self.assertEqual(continuation_blockers(fixture(),'WARNING: II Violation (II = 2)'),[])
    def test_missing_final_ii_cannot_advance(self):
        self.assertIn('scheduler PipelineII missing or invalid',continuation_blockers(fixture(ii=None),''))
    def test_within_capacity_only_allows_next_review_not_board_pass(self):
        self.assertEqual(continuation_blockers(fixture(),''),[])
    def test_estimate_over_capacity_stops_continuation(self):
        self.assertEqual(len(continuation_blockers(fixture(11,10),'')),5)
    def test_unmet_pipeline_blocks_even_when_resources_fit(self):
        issues=continuation_blockers(fixture(),'WARNING: [SCHED 204-65] Unable to satisfy pipeline directive for loop X')
        self.assertEqual(issues,['requested loop pipeline not achieved'])
    def test_missing_capacity_is_not_silent_pass(self):
        self.assertEqual(len(continuation_blockers(ET.ElementTree(ET.Element('Report')),'')),6)
    def test_real_completed_p1_is_blocked(self):
        p=ROOT/'build/hls/optimization_build/m3_s2_syn_8p1_pack_20261007_r2/sol/syn/report/s2_engine_csynth.xml'
        log=(ROOT/'build/host/m3_s2_synth_20261007_r2/8p1_pack.log').read_text(errors='replace')
        issues=continuation_blockers(ET.parse(p),log)
        self.assertEqual(issues,['HLS estimate requires review: LUT 361742 > 117120','requested loop pipeline not achieved',
                                 'scheduler PipelineII missing or invalid'])
    def test_expression_table_reconciles(self):
        p=ROOT/'build/hls/optimization_build/m3_s2_syn_8p1_pack_20261007_r2/sol/syn/report/s2_engine_csynth.rpt'
        d=audit(p)
        self.assertEqual(d['expression_lut_total'],275847)
        self.assertEqual(d['shifts']['lut_by_input_width']['64'],141231)

if __name__=='__main__':unittest.main(verbosity=2)
