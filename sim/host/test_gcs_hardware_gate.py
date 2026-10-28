"""Read-only RTL binding mutation tests; never modify the completed candidate."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import install_gcs_cycle_counter as counter

class Binding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(counter.BUILD/'sol/syn/verilog/tt_engine.v').read_text()
        cls.template=counter.TEMPLATE.read_text()
    def test_exact_completed_binding(self):counter.verify_binding(self.text,self.template)
    def test_wrong_start_done_reset_and_tied_register_refused(self):
        for before,after in (('.accepted(ap_CS_fsm_state1 && ap_start)','.accepted(ap_idle && ap_start)'),
                ('.cycles_ap_vld(ap_done)','.cycles_ap_vld(cycles_ap_vld)'),
                ('.resetn(ap_rst_n)',".resetn(1'b1)"),('.done(ap_done)','.done(ap_ready)'),
                ('.cycles(tt_gcs_cycles)',".cycles(32'd0)")):
            with self.subTest(after=after),self.assertRaises(ValueError):
                counter.verify_binding(self.text.replace(before,after),self.template)
    def test_declaration_order_and_template_drift_refused(self):
        late=self.text.replace('wire [31:0] tt_gcs_cycles;','')+'\nwire [31:0] tt_gcs_cycles;\n'
        for text in (late,self.text.replace('count + 32\'d1','count + 32\'d2')):
            with self.assertRaises(ValueError):counter.verify_binding(text,self.template)

if __name__=='__main__':unittest.main()
