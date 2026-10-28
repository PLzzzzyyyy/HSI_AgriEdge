"""Host-only C3 protocol regression; no board or network required."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('periph_pc', Path(__file__).with_name('periph_pc.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ProtocolTests(unittest.TestCase):
    def rx_result(self, packets=10, size=64, errors=0, byte_count=None):
        report = dict(packets=packets, bytes=packets*size if byte_count is None else byte_count,
                      elapsed_us=100, errors=errors, extra=0, seq_max=9, link_mbps=1000)
        with patch.object(m, 'drain'), patch.object(m, 'wait_report', return_value=report), patch.object(m.time, 'sleep'):
            return m.do_rx(MagicMock(), SimpleNamespace(board='127.0.0.1', board_port=5010), 10, size, 0)

    def test_rx_valid(self):
        self.assertTrue(self.rx_result()['pass'])

    def test_rx_excess_packets_rejected(self):
        self.assertFalse(self.rx_result(packets=11)['pass'])

    def test_rx_loss_rejected(self):
        self.assertFalse(self.rx_result(packets=9)['pass'])

    def test_rx_bad_size_rejected(self):
        self.assertFalse(self.rx_result(byte_count=639)['pass'])

    def test_rx_errors_rejected(self):
        self.assertFalse(self.rx_result(errors=1)['pass'])

    def test_rx_no_reset_report(self):
        with patch.object(m, 'drain'), patch.object(m, 'wait_report', return_value=None):
            self.assertFalse(m.do_rx(MagicMock(), SimpleNamespace(board='127.0.0.1', board_port=5010), 10, 64, 0)['pass'])

    def test_wire_layout(self):
        self.assertEqual(m.HDR.pack(m.MAGIC, m.RXDATA, 0, 1, 10).hex(), '4333555405000000010000000a000000')
        self.assertEqual(m.REPORT.size, 32)

    def test_bad_cli(self):
        for args in (['rx', '-n', '0'], ['rx', '-n', '-1'], ['tx', '-n', '2000001'], ['rx', '--rate', '-1'], ['tx', '--size', '1473']):
            with self.subTest(args=args), patch('sys.argv', ['periph_pc.py']+args), patch.object(m.socket, 'socket') as sock:
                with self.assertRaises(SystemExit):
                    m.main()
                sock.assert_not_called()

if __name__ == '__main__':
    unittest.main()
