"""Diagnostic receipts cannot treat a tool's exit zero as cosim success."""
import unittest
from run_m3_s2_rtl_n1 import SETUP_MARKER, setup_completed


class ReceiptTests(unittest.TestCase):
    def test_tool_exit_zero_without_marker_fails(self):
        self.assertFalse(setup_completed(dict(exit=0,timed_out=False),'Invalid attribute value'))

    def test_complete_setup(self):
        self.assertTrue(setup_completed(dict(exit=0,timed_out=False),SETUP_MARKER))

    def test_error_exit_and_timeout_fail(self):
        for rc,timeout,text in [(1,False,SETUP_MARKER),(0,True,SETUP_MARKER),
                               (0,False,SETUP_MARKER+' ERROR: failed')]:
            self.assertFalse(setup_completed(dict(exit=rc,timed_out=timeout),text))


if __name__=='__main__':
    unittest.main()
