"""Offline wire fixtures only: no sockets, services, model, fake board or entropy."""
import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("s2c_client", ROOT / "tools/s2c_roi_client.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


def status(task=0, state=0, boot=0x12345678, session=42, flags=0, done=None):
    done = (15 if state == 3 else 0) if done is None else done
    body = struct.pack("<IIfffBBH", done, 15 if task else 0, *([float("nan")] * 3), state, flags, 0)
    tail = struct.pack("<IIIHBB8IHHI", boot, session, c.WCRC, 3 if state == 3 else 0, 1, 0, *([0]*8), 0, 0, 0)
    return c.packet(0x82, task, 1, 99, body + tail)


def ack(seq=1, code=0):
    return c.packet(0x83, 7, 3, 100, struct.pack("<BBHI", 1, code, seq, 0))


def row(y, words):
    return c.packet(0x81, 7, 4+y, 101, struct.pack("<HHHH5I", y, 0, 5, 0, *words))


class ClientTests(unittest.TestCase):
    def ready(self, start=True):
        a = c.Audit(0x12345678, 42, 7)
        a.sent(c.packet(5, 0, 0, 123, struct.pack("<I", 42)))
        a.received(c.packet(0x84, 0, 0, 126, struct.pack("<HHII", 0, 0, 123, 125)))
        a.received(status())
        if start: a.sent(c.start_packet(7, 1, 127, 42))
        return a

    def test_exact_start_layout(self):
        self.assertEqual(c.start_packet(7,1,127,42).hex(),
            "48450101070001007f000000010000000000000003000500831923272a000000")

    def test_completion_requires_ack_all_rows_and_done(self):
        a = self.ready(); a.received(status(7,3)); self.assertFalse(a.complete())
        expected = c.reference()
        for y in (2,0,1): a.received(row(y,[expected[x,y] for x in range(5)]))
        self.assertFalse(a.complete()); a.received(ack()); self.assertTrue(a.complete())
        self.assertTrue(all(x["match"] for x in a.compare()))

    def test_duplicate_not_more_pixels(self):
        a = self.ready(); data = row(0,[0]*5); a.received(data); a.received(data)
        self.assertEqual(len(a.compare()),5); self.assertEqual(a.duplicates,1)
        with self.assertRaisesRegex(ValueError,"conflicting"): a.received(row(0,[1]*5))

    def test_wrong_actual_is_not_replaced(self):
        a = self.ready(); a.received(row(0,[0]*5))
        self.assertFalse(any(x["match"] for x in a.compare()))
        self.assertEqual(a.compare()[0]["actual"],"00000000")

    def test_wrong_boot_session_flags(self):
        for data in (status(boot=9),status(session=9),status(flags=1)):
            with self.subTest(data=data), self.assertRaises(ValueError): self.ready(False).received(data)

    def test_bad_ack_and_rejected_command(self):
        for data in (ack(seq=2),ack(code=6)):
            with self.assertRaises(ValueError): self.ready().received(data)

    def test_second_start_never_allowed(self):
        with self.assertRaisesRegex(ValueError,"second START"):
            self.ready().sent(c.start_packet(7,2,128,42))

    def test_start_before_identity_forbidden(self):
        with self.assertRaisesRegex(ValueError,"handshake"):
            c.Audit(1,42,7).sent(c.start_packet(7,1,2,42))

    def test_exact_lengths_and_version(self):
        for good in (status(),ack(),row(0,[0]*5)):
            for n in range(len(good)):
                with self.assertRaises(ValueError): c.decode(good[:n])
            with self.assertRaises(ValueError): c.decode(good+b"\0")
            bad=bytearray(good); bad[3]=0
            with self.assertRaises(ValueError): c.decode(bad)

    def test_bad_roi_class_reserved(self):
        for data in (row(3,[0]*5),row(0,[9]*5),row(0,[0x100]*5)):
            with self.assertRaises(ValueError): c.decode(data)

    def test_inconsistent_done(self):
        with self.assertRaises(ValueError): self.ready().received(status(7,3,done=14))

    def test_boot_argument(self):
        for s in ("e86a03b1","e86a03","0x12345678"," 12345678","123456789"):
            with self.assertRaises(Exception): c.boot_value(s)
        self.assertEqual(c.boot_value("00000000"),0)


if __name__ == "__main__": unittest.main()
