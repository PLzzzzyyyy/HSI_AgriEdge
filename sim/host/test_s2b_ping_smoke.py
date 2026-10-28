"""Offline packet fixtures only. Never call main, socket, entropy or a board."""
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("s2b_ping_smoke", ROOT / "tools/s2b_ping_smoke.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
BOARD = ("192.168.1.10", 5010)


def header(kind):
    return struct.pack("<HBBHHI", 0x4548, kind, 1, 0, 7, 23456)


def pong(seq=2, t1=12345):
    return header(0x84) + struct.pack("<HHII", seq, 0, t1, 23400)


def status(boot=0xe86a03b1, session=0x11223344):
    data = bytearray(header(0x82) + bytes(80))
    struct.pack_into("<fff", data, 20, float("nan"), float("nan"), float("nan"))
    struct.pack_into("<II", data, 36, boot, session)
    data[50] = 1
    return data


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.io_guard = patch.object(client.socket, "socket", side_effect=AssertionError("NO NETWORK"))
        self.entropy_guard = patch.object(client.secrets, "randbits", side_effect=AssertionError("NO ENTROPY"))
        self.io_guard.start(); self.entropy_guard.start()
        self.addCleanup(self.io_guard.stop); self.addCleanup(self.entropy_guard.stop)
        self.results = client.Results(BOARD, 0xe86a03b1, 0x11223344)
        self.results.pending[2] = 12345

    def test_ping_actual_wire_bytes(self):
        self.assertEqual(client.ping(2, 12345, 0x11223344).hex(),
                         "48450501000002003930000044332211")

    def test_requires_both_matching_packet_types(self):
        self.results.receive(pong(), BOARD)
        self.assertFalse(self.results.passed())
        self.results.receive(status(), BOARD)
        self.assertTrue(self.results.passed())

    def test_status_alone_does_not_pass(self):
        self.results.receive(status(), BOARD)
        self.assertFalse(self.results.passed())

    def test_duplicate_and_delayed_pong(self):
        self.results.pending[3] = 54321
        self.results.receive(pong(), BOARD)  # earlier sent packet still valid
        self.results.receive(pong(), BOARD)
        self.assertEqual(len(self.results.pongs), 1)
        self.assertEqual(self.results.duplicates, 1)

    def test_wrong_peer_or_stale_echo_does_not_count(self):
        self.results.receive(pong(), (BOARD[0], 5000))
        self.results.receive(pong(t1=12344), BOARD)
        self.results.receive(pong(seq=30), BOARD)
        self.assertFalse(self.results.pongs)

    def test_wrong_identity_session_rejected(self):
        for packet in (status(boot=0x00000000), status(session=0)):
            with self.subTest(packet=packet.hex()), self.assertRaises(ValueError):
                self.results.receive(packet, BOARD)

    def test_wrong_version_length_task_type_rejected(self):
        packets = [b"", pong()[:-1], pong()+b"x", header(0x83)]
        for offset, value in ((0, 0), (3, 0), (4, 1)):
            data = bytearray(pong()); data[offset] = value; packets.append(data)
        for packet in packets:
            with self.subTest(packet=packet.hex()), self.assertRaises(ValueError):
                self.results.receive(packet, BOARD)

    def test_running_simulator_and_nonzero_work_rejected(self):
        for offset in (12, 16, 32, 33):
            data = status(); data[offset] = 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.results.receive(data, BOARD)

    def test_default_expected_id_and_input_validation(self):
        self.assertEqual(client.boot_hex(client.DEFAULT_BOOT), 0xe86a03b1)
        self.assertEqual(client.boot_hex("00000000"), 0)
        for text in ("e86a03", "0xe86a03b1", "e86a03b1\n", " e86a03b1", "gggggggg"):
            with self.subTest(text=text), self.assertRaises(client.argparse.ArgumentTypeError):
                client.boot_hex(text)

    def test_help_never_opens_socket_or_generates_entropy(self):
        with self.assertRaises(SystemExit) as result:
            client.main(["--help"])
        self.assertEqual(result.exception.code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
