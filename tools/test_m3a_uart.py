"""Regression tests for UART audit, no board or hardware tools."""
import unittest
from check_m3a_uart import ROOT, check

class UartAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(ROOT/'board/m3/20261007_acceptance/uart_user.txt').read_text(encoding='utf-8')
    def test_valid(self):
        result=check(self.text)
        self.assertEqual((result['samples'],result['groups'],result['dump_layers']),(120,12,12))
    def test_missing_sample(self):
        line=next(x for x in self.text.splitlines(True) if x.startswith('SAMPLE '))
        with self.assertRaises(ValueError): check(self.text.replace(line,'',1))
    def test_duplicate_sample(self):
        with self.assertRaises(ValueError): check(self.text.replace('n=1 run=1 ticks=113210','n=1 run=0 ticks=113210',1))
    def test_bad_sum(self):
        with self.assertRaises(ValueError): check(self.text.replace('total_ticks=1132181','total_ticks=1132182',1))
    def test_bad_metric(self):
        with self.assertRaises(ValueError): check(self.text.replace('patches_per_s=294.414','patches_per_s=394.414',1))
    def test_missing_layer(self):
        with self.assertRaises(ValueError): check(self.text.replace('PASS DUMP layer=11 elements=15876','',1))
    def test_failure(self):
        with self.assertRaises(ValueError): check(self.text.replace('M3A_APP_END PASS','M3A_APP_END FAIL',1))
    def test_bad_logits(self):
        with self.assertRaises(ValueError): check(self.text.replace('A_q16=619049,','A_q16=619048,',1))

if __name__=='__main__': unittest.main(verbosity=2)
