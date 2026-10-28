#!/usr/bin/env python3
"""One real-board job; never imports gcs/model or runs inference/fake-board code.

Live target is immutable 192.168.1.10:5010. User must first confirm independent
business-App cold start. Offline replay never opens sockets or draws entropy.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TARGET = ("192.168.1.10", 5010)
WCRC = 0x27231983
REFERENCE = ROOT / "report/system_s1b/20261009_app_board_r1/uart_attempt_03_user.txt"
HEADER = struct.Struct("<HBBHHI")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boot_value(text):
    if not re.fullmatch(r"[0-9a-fA-F]{8}", text):
        raise argparse.ArgumentTypeError("boot-id requires exactly eight hex digits")
    if text.lower() == "e86a03b1":
        raise argparse.ArgumentTypeError("old S2b boot-id cannot be reused")
    return int(text, 16)


def packet(kind, task, seq, stamp, body):
    return HEADER.pack(0x4548, kind, 1, task, seq, stamp) + body


def start_packet(task, seq, stamp, session):
    return packet(1, task, seq, stamp,
                  struct.pack("<BBBBHHHHII", 1, 0, 0, 0, 0, 0, 3, 5, WCRC, session))


def decode(data):
    if len(data) < 12:
        raise ValueError("short header")
    magic, kind, ver, task, seq, stamp = HEADER.unpack_from(data)
    if magic != 0x4548 or ver != 1 or kind not in (0x81, 0x82, 0x83, 0x84):
        raise ValueError("unsupported header")
    d = dict(kind=kind, task=task, seq=seq, t_us=stamp)
    if kind == 0x81:
        if len(data) != 40:
            raise ValueError("fixed ROW must be 40 bytes")
        row, col, n, flags = struct.unpack_from("<4H", data, 12)
        if row >= 3 or col != 0 or n != 5 or flags != 0:
            raise ValueError("ROW outside fixed ROI or unexpected retransmission")
        words = struct.unpack_from("<5I", data, 20)
        if any((w & 0xff) > 8 or w & 0xff00 for w in words):
            raise ValueError("invalid CLASS word")
        d.update(row=row, words=words)
    elif kind == 0x82:
        if len(data) != 92:
            raise ValueError("STATUS length")
        done, total, ms, temp, power, state, flags, pad = struct.unpack_from("<IIfffBBH", data, 12)
        t = struct.unpack_from("<IIIHBB8IHHI", data, 36)
        if flags or pad or t[5] or t[15] or t[4] & ~3:
            raise ValueError("STATUS reserved/simulated flags")
        # ms/pixel：这一版 ABI4 固件在算过像素后会给出实测值，未算之前是 NaN；
        # 地面站（gcs/board_roi.py 也 import 本模块）会把该字段归一化后再解析，
        # 所以这里只做「NaN 或 有限且非负」的宽容校验，具体语义由调用方各自判定。
        if not (math.isnan(ms) or (math.isfinite(ms) and ms >= 0)):
            raise ValueError("invalid ms/pixel metric")
        if not all(math.isnan(v) for v in (temp, power)):
            raise ValueError("unmeasured metrics must remain NaN")
        d.update(done=done, total=total, state=state, boot_id=t[0], session=t[1],
                 wcrc=t[2], front_row=t[3], link=t[4], metrics=None,
                 tx_pkts=t[6], tx_bytes=t[7], tx_fail=t[8], tx_retx=t[9],
                 rx_pkts=t[10], rx_bad=t[11], rx_gap=t[12], rx_dup=t[13],
                 down_cnt=t[14], down_ms=t[16])
    elif kind == 0x83:
        if len(data) != 20:
            raise ValueError("ACK length")
        typ, code, ack_seq, value = struct.unpack_from("<BBHI", data, 12)
        d.update(acked_type=typ, code=code, acked_seq=ack_seq, value=value)
    else:
        if len(data) != 24:
            raise ValueError("PONG length")
        ping_seq, pad, t1, t2 = struct.unpack_from("<HHII", data, 12)
        if pad:
            raise ValueError("PONG reserved")
        d.update(ping_seq=ping_seq, t1=t1, t2=t2)
    return d


def reference():
    # This is only a comparison oracle, never a replacement for received data.
    found = re.findall(r"ROI x=(\d+) y=(\d+) class_word=([0-9A-F]{8})", REFERENCE.read_text())
    words = {(int(x), int(y)): int(w, 16) for x, y, w in found}
    if len(found) != 15 or set(words) != {(x, y) for y in range(3) for x in range(5)}:
        raise ValueError("historical accepted reference is incomplete")
    return words


class Audit:
    def __init__(self, boot, session, task):
        self.boot, self.session, self.task = boot, session, task
        self.start_seq = None
        self.pings = {}
        self.have_pong = self.ready = self.ack = False
        self.final = None
        self.rows = {}
        self.duplicates = 0
        self.statuses = 0

    def sent(self, data):
        if len(data) < 12:
            raise ValueError("TX truncated")
        magic, kind, ver, task, seq, stamp = HEADER.unpack_from(data)
        if magic != 0x4548 or ver != 1:
            raise ValueError("TX header")
        if kind == 5:
            if len(data) != 16 or struct.unpack_from("<I", data, 12)[0] != self.session:
                raise ValueError("TX PING session")
            self.pings[seq] = stamp
        elif kind == 1:
            if self.start_seq is not None:
                raise ValueError("second START forbidden, no blind retries")
            if not (self.ready and self.have_pong):
                raise ValueError("START before identity/idle handshake")
            if data != start_packet(self.task, seq, stamp, self.session):
                raise ValueError("unexpected START parameters")
            self.start_seq = seq
        else:
            raise ValueError("unauthorized TX type")

    def received(self, data):
        d = decode(data)
        if d["kind"] == 0x84:
            if self.pings.get(d["ping_seq"]) != d["t1"]:
                raise ValueError("PONG does not echo our PING")
            self.have_pong = True
        elif d["kind"] == 0x82:
            self.statuses += 1
            if (d["boot_id"], d["session"], d["wcrc"]) != (self.boot, self.session, WCRC):
                raise ValueError("boot/session/model mismatch; no restart/retry")
            if any(d[k] for k in ("tx_fail", "tx_retx", "rx_bad", "rx_gap", "rx_dup")):
                raise ValueError("nonzero error/gap/retry counters; preserve first failure")
            if self.start_seq is None:
                if (d["task"], d["state"], d["done"], d["total"], d["front_row"]) != (0, 0, 0, 0, 0):
                    raise ValueError("board is not a fresh idle business App")
                self.ready = True
            elif d["task"] == self.task:
                if d["state"] == 3:
                    if (d["done"], d["total"], d["front_row"]) != (15, 15, 3):
                        raise ValueError("inconsistent DONE status")
                    self.final = d
                elif (d["state"], d["done"], d["total"], d["front_row"]) != (1, 0, 15, 0):
                    raise ValueError("unexpected task progress")
            elif d["task"] != 0:
                raise ValueError("unexpected STATUS task")
        elif d["kind"] == 0x83:
            if (d["task"], d["acked_type"], d["acked_seq"]) != (self.task, 1, self.start_seq):
                raise ValueError("ACK correlation mismatch")
            if d["code"] != 0 or d["value"] != 0:
                raise ValueError(f"board ACK failure: code={d['code']} value=0x{d['value']:08x}")
            self.ack = True
        else:
            if self.start_seq is None or d["task"] != self.task:
                raise ValueError("unexpected ROW task")
            row = d["row"]
            if row in self.rows:
                if self.rows[row] != d["words"]:
                    raise ValueError("conflicting duplicate ROW")
                self.duplicates += 1
            self.rows[row] = d["words"]
        return d

    def complete(self):
        return self.ack and self.final is not None and set(self.rows) == {0, 1, 2}

    def compare(self):
        expected = reference()
        return [dict(x=x, y=y, actual=f"{w:08X}", expected=f"{expected[x,y]:08X}",
                     class_id=w & 255, confidence=(w >> 16) / 65536,
                     match=w == expected[x, y])
                for y, words in sorted(self.rows.items()) for x, w in enumerate(words)]


def save_output(out, audit, status, error, started):
    cells = audit.compare()
    result = dict(result=status, error=error, scope="minimal real-board ROI business loop only",
                  target=list(TARGET), boot_id=f"{audit.boot:08x}", session=f"{audit.session:08x}",
                  task=audit.task, start_seq=audit.start_seq, ack=audit.ack,
                  received_pixels=len(cells), matched_pixels=sum(c["match"] for c in cells),
                  rows=len(audit.rows), duplicates=audit.duplicates, statuses=audit.statuses,
                  final_status=audit.final, started=started, ended=datetime.now(timezone.utc).isoformat(),
                  reference_path=REFERENCE.relative_to(ROOT).as_posix(), reference_sha256=sha(REFERENCE),
                  client_sha256=sha(Path(__file__)), cells=cells,
                  limitations="No full v1/gcs/S3/retransmit/full-scene/OA/performance/PHY acceptance")
    (out / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out / "results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["x", "y", "actual", "expected", "class_id", "confidence", "match"])
        w.writeheader(); w.writerows(cells)
    table = "".join("<tr>" + "".join(f"<td>{html.escape(str(c[k]))}</td>" for k in
                     ("x", "y", "actual", "expected", "class_id", "confidence", "match")) + "</tr>" for c in cells)
    grid = "".join(f'<div class="cell {"ok" if c["match"] else "bad"}">({c["x"]},{c["y"]}) '
                   f'类别 {c["class_id"]}<br>{c["actual"]}<br>{c["confidence"]:.4f}</div>' for c in cells)
    page = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>S2c ROI evidence</title>
<style>body{{font:16px sans-serif;margin:32px;max-width:1100px}}.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}
.cell{{padding:15px;border:1px solid #777}}.ok{{background:#d9efda}}.bad{{background:#ffd6d6}}
td,th{{padding:6px;border:1px solid #aaa}}table{{border-collapse:collapse}}</style>
<h1>{status} · 最小板端业务闭环</h1><p>LongKou/v2 · ROI (0,0) 5×3 · wcrc=27231983</p>
<p>boot={audit.boot:08x} session={audit.session:08x} task={audit.task}; 收到 {len(cells)}/15；
匹配 {sum(c['match'] for c in cells)}/15。只展示本次 UDP 实收；历史字仅作对照。</p>
<p>{html.escape(error or '')}</p><div class="grid">{grid}</div>
<p>类别为零基，不推定作物名。置信度 Q0.16；温度、功率及性能指标未测。非完整地面站/完整 v1。</p>
<table><tr><th>x</th><th>y</th><th>本次 UDP</th><th>历史对照</th><th>类别</th><th>置信度</th><th>一致</th></tr>{table}</table></html>'''
    (out / "result.html").write_text(page, encoding="utf-8")
    return result


def live(args):
    import secrets
    import socket
    reference()  # validate comparison source before sending anything
    out = (args.out or ROOT / "build/host" / datetime.now().strftime("s2c_roi_%Y%m%d_%H%M%S_%f")).resolve()
    out.mkdir(parents=True, exist_ok=False)  # never replace the first attempt
    session = int(args.session, 16) if getattr(args, 'session', None) else secrets.randbits(32)
    audit = Audit(args.boot_id, session, secrets.randbelow(65535) + 1)
    started = datetime.now(timezone.utc).isoformat()
    session_info = dict(boot_id=audit.boot, session=audit.session, task=audit.task,
                        target=list(TARGET), started=started, client_sha256=sha(Path(__file__)))
    (out / "session.json").write_text(json.dumps(session_info, indent=2) + "\n")
    seq = 0; error = None; status = "FAIL"
    print(f"Evidence: {out}", flush=True)
    try:
        with (out / "packets.jsonl").open("x", encoding="utf-8") as log, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("", 0)); sock.settimeout(0.05)
            end = time.monotonic() + args.timeout
            handshake_end = time.monotonic() + 5
            next_ping = 0.0
            def record(direction, data, peer):
                log.write(json.dumps(dict(direction=direction, monotonic_ns=time.perf_counter_ns(),
                                          peer=list(peer), hex=data.hex())) + "\n"); log.flush()
            def send(data):
                audit.sent(data)
                record("tx", data, TARGET)  # preserve the attempted datagram even on send failure
                if sock.sendto(data, TARGET) != len(data):
                    raise RuntimeError("short UDP send")
            while time.monotonic() < end:
                now = time.monotonic()
                if now >= next_ping:
                    send(packet(5, audit.task if audit.start_seq is not None else 0, seq,
                                (time.perf_counter_ns() // 1000) & 0xffffffff, struct.pack("<I", audit.session)))
                    seq = (seq + 1) & 65535; next_ping = now + 0.25
                if audit.ready and audit.have_pong and audit.start_seq is None:
                    send(start_packet(audit.task, seq, (time.perf_counter_ns() // 1000) & 0xffffffff, audit.session))
                    seq = (seq + 1) & 65535
                    print(f"START once: boot={audit.boot:08x} session={audit.session:08x} task={audit.task}", flush=True)
                if audit.start_seq is None and now >= handshake_end:
                    raise TimeoutError("new App identity/ready handshake timeout; no START sent")
                try:
                    data, peer = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                record("rx", data, peer)
                if peer != TARGET:
                    continue
                d = audit.received(data)
                if d["kind"] == 0x81:
                    print(f"ROW y={d['row']}: " + " ".join(f"{w:08X}" for w in d["words"]), flush=True)
                if audit.complete():
                    if not all(c["match"] for c in audit.compare()):
                        raise ValueError("actual board CLASS differs from accepted reference")
                    status = "PASS"; break
            if status != "PASS":
                raise TimeoutError("bounded test ended before ACK + 15 UDP pixels + DONE; no retries/ROWREQ")
    except (Exception, KeyboardInterrupt) as exc:
        error = f"{type(exc).__name__}: {exc}"
    result = save_output(out, audit, status, error, started)
    print(f"{status}: received={result['received_pixels']}/15 matched={result['matched_pixels']}/15; {error or ''}")
    print(f"View locally: {out / 'result.html'}")
    return 0 if status == "PASS" else 1


def replay(path):
    info = json.loads((path / "session.json").read_text())
    audit = Audit(info["boot_id"], info["session"], info["task"])
    error = None
    try:
        for line in (path / "packets.jsonl").read_text().splitlines():
            p = json.loads(line); data = bytes.fromhex(p["hex"])
            if tuple(p["peer"]) != TARGET:
                if p["direction"] == "tx": raise ValueError("TX outside authorized endpoint")
                continue
            if p["direction"] == "tx": audit.sent(data)
            elif p["direction"] == "rx": audit.received(data)
            else: raise ValueError("unknown log direction")
        passed = audit.complete() and all(c["match"] for c in audit.compare())
    except Exception as exc:
        passed = False; error = str(exc)
    print(json.dumps(dict(result="PASS" if passed else "FAIL", error=error,
                          received=len(audit.compare()), matches=sum(c["match"] for c in audit.compare())), indent=2))
    return 0 if passed else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--boot-id", type=boot_value)
    p.add_argument("--session", help="复用板卡已锁定的会话号（8 位 hex）；默认随机生成")
    p.add_argument("--board-started", action="store_true", help="user has confirmed independent new App cold start")
    p.add_argument("--out", type=Path)
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--replay", type=Path)
    args = p.parse_args()
    if args.replay:
        return replay(args.replay)
    if args.boot_id is None or not args.board_started:
        p.error("live mode requires fresh --boot-id and --board-started after user's confirmation")
    if not 5 <= args.timeout <= 120:
        p.error("timeout must be 5..120 seconds")
    return live(args)


if __name__ == "__main__":
    sys.exit(main())
