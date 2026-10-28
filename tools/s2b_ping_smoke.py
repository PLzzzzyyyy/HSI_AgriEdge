#!/usr/bin/env python3
"""S2b v1 PING-only client. Running this file starts a real, bounded UDP test.

Default expected boot ID is the value supplied by the user on 2026-10-10,
NOT a generated board identity. After a new cold boot use --boot-id NEW8HEX.
No serial, board reset, business commands, gcs import, or background service.
"""
import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import struct
import time

ROOT = Path(__file__).resolve().parents[1]
HEADER = struct.Struct("<HBBHHI")
DEFAULT_BOOT = "e86a03b1"


def boot_hex(text):
    if not re.fullmatch(r"[0-9a-fA-F]{8}", text):
        raise argparse.ArgumentTypeError("boot-id must be exactly 8 hex digits")
    return int(text, 16)


def ipv4(text):
    try:
        return str(ipaddress.IPv4Address(text))
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def ping(seq, t1, session):
    return HEADER.pack(0x4548, 0x05, 1, 0, seq, t1) + struct.pack("<I", session)


class Results:
    def __init__(self, board, boot_id, session):
        self.board, self.boot_id, self.session = board, boot_id, session
        self.pending = {}
        self.pongs = set()
        self.status = self.duplicates = self.ignored = 0

    def receive(self, data, peer):
        if peer != self.board:
            self.ignored += 1
            return "ignored-peer"
        if len(data) < HEADER.size:
            raise ValueError("short board packet")
        magic, kind, ver, task, _, _ = HEADER.unpack_from(data)
        if (magic, ver, task) != (0x4548, 1, 0):
            raise ValueError("not an idle v1 packet (magic/version/task)")
        if kind == 0x84 and len(data) == 24:
            seq = struct.unpack_from("<H", data, 12)[0]
            t1 = struct.unpack_from("<I", data, 16)[0]
            if seq not in self.pending or self.pending[seq] != t1:
                self.ignored += 1
                return "unmatched-pong"
            if seq in self.pongs:
                self.duplicates += 1
                return "duplicate-pong"
            self.pongs.add(seq)
            return "PONG"
        if kind == 0x82 and len(data) == 92:
            boot_id, session = struct.unpack_from("<II", data, 36)
            if boot_id != self.boot_id:
                raise ValueError(f"boot_id mismatch: expected {self.boot_id:08x}, received {boot_id:08x}")
            if session != self.session:
                raise ValueError("STATUS session mismatch")
            if struct.unpack_from("<II", data, 12) != (0, 0) or data[32] != 0 or data[33] != 0:
                raise ValueError("STATUS is not the expected idle/non-simulator state")
            self.status += 1
            return "STATUS"
        raise ValueError(f"unexpected board packet: type=0x{kind:02x}, bytes={len(data)}")

    def passed(self):
        return bool(self.pongs and self.status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot-id", type=boot_hex, default=DEFAULT_BOOT,
                        help="expected ID already sent by UART0; default is this user's current boot")
    parser.add_argument("--board", type=ipv4, default="192.168.1.10")
    parser.add_argument("--bind", type=ipv4, default="0.0.0.0", help="optional existing PC Ethernet IPv4")
    args = parser.parse_args(argv)
    board = (args.board, 5010)
    out = ROOT / "build/host" / datetime.now().strftime("s2b_udp_%Y%m%d_%H%M%S_%f")
    out.mkdir(parents=True, exist_ok=False)
    # This is a PC protocol session, never a replacement for the board boot ID.
    session = secrets.randbits(32)
    results = Results(board, args.boot_id, session)
    sent = received = 0
    result, error = "FAIL", None
    print(f"S2b UDP smoke: {board[0]}:{board[1]}, expected boot_id={args.boot_id:08x}", flush=True)
    print("40 PINGs, about 10 seconds. Keep the current board App running.", flush=True)
    print(f"Logs: {out}", flush=True)
    try:
        with (out / "packets.jsonl").open("w", encoding="utf-8", newline="\n") as raw, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((args.bind, 0))  # reply-to-source contract; do not take port 5011
            def record(direction, data, peer):
                raw.write(json.dumps(dict(direction=direction, at_ns=time.monotonic_ns(),
                                          peer=peer, hex=data.hex())) + "\n")
            for seq in range(40):
                t1 = (time.monotonic_ns() // 1000) & 0xffffffff
                packet = ping(seq, t1, session)
                sock.settimeout(0.25)
                count = sock.sendto(packet, board)
                if count != len(packet):
                    raise OSError("short UDP send")
                record("tx", packet, board)
                sent += 1
                results.pending[seq] = t1
                deadline = time.monotonic() + 0.25
                while time.monotonic() < deadline:
                    sock.settimeout(max(0.001, deadline - time.monotonic()))
                    try:
                        data, peer = sock.recvfrom(65535)
                    except socket.timeout:
                        break
                    received += 1
                    record("rx", data, peer)
                    if received > 4096:
                        raise ValueError("receive budget exceeded; stop rather than drain indefinitely")
                    results.receive(data, peer)
            if results.passed():
                result = "PASS"
            else:
                error = "No matching PONG and/or STATUS. Check cable, PC route/IP, firewall and UART log."
    except KeyboardInterrupt:
        result, error = "ABORTED", "user interrupted"
    except (OSError, ValueError) as exc:
        error = str(exc)
    receipt = dict(result=result, board=board, boot_id=f"{args.boot_id:08x}", session=f"{session:08x}",
                   sent=sent, received=received, pong=len(results.pongs), status=results.status,
                   duplicates=results.duplicates, ignored=results.ignored, error=error,
                   finished=datetime.now().astimezone().isoformat(),
                   script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   scope="BASIC_V1_COMMUNICATION_SMOKE_ONLY; not business/performance/endurance acceptance")
    (out / "summary.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"RESULT={result} PONG={len(results.pongs)} STATUS={results.status} SENT={sent} boot_id={args.boot_id:08x}")
    if error:
        print("DETAIL:", error)
    print("Summary:", out / "summary.json")
    return 0 if result == "PASS" else (130 if result == "ABORTED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
