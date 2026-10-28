# -*- coding: utf-8 -*-
"""一键复现板端演示：激活模型 → 下发一个 5×3 的 ROI 任务 → 收结果 → 看 DP。

板卡单独上电时只会显示「等待任务 / 尚未选择模型」：选择模型和下发任务本来由地面站做，
这里用最小的 UDP 客户端把同样的两件事做完（协议见 docs/protocol.md）。

    D:\\Anaconda\\python.exe tools\\demo_roi.py

运行后看显示器：
  · 右上角状态从「等待任务」变成「运行中」，任务卡出现 5×3 的小图，
    跑完变「已完成」，模型那一行显示已选中的权重包 tag。
"""

import argparse
import math
import socket
import struct
import sys
import time

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548
PING, START, WACT = 0x05, 0x01, 0x13
ROW, STATUS, ACK, PONG = 0x81, 0x82, 0x83, 0x84

NAMES = {0: "LongKou", 1: "HongHu", 2: "HanChuan"}


class Board:
    def __init__(self, host, port):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.settimeout(0.05)
        self.seq = 0
        self.session = None
        self.task = None

    def send(self, kind, body=b""):
        t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
        self.sock.sendto(HDR.pack(MAGIC, kind, 1, self.task or 0, self.seq, t) + body, self.addr)
        self.seq = (self.seq + 1) & 0xFFFF

    def ping(self):
        self.send(PING, struct.pack("<I", self.session))

    def drain(self, seconds, on_row=None, on_status=None):
        """收若干秒包；返回 (是否收到 ACK, 最后一条 STATUS)。"""
        got_ack = False
        last = None
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            kind = data[2]
            if kind == STATUS and len(data) >= 92:
                last = parse_status(data)
                if on_status:
                    on_status(last)
            elif kind == ROW and len(data) >= 20:
                row, col, n, _flags = struct.unpack_from("<4H", data, 12)
                words = struct.unpack_from("<%dI" % n, data, 20)
                if on_row:
                    on_row(row, col, words)
            elif kind == ACK and len(data) >= 20:
                typ, code, acked, value = struct.unpack_from("<BBHI", data, 12)
                got_ack = True
                print("      ACK type=0x%02x code=%d seq=%d value=%s"
                      % (typ, code, acked, ("0x%08x" % value) if typ == 1 else str(value)))
                if code != 0:
                    print("      !! 板卡拒绝：code=%d（5=没有这个权重 8=参数非法 9=任务号不符）" % code)
        return got_ack, last


def parse_status(d):
    done, total, ms, temp, power, state, flags, pad = struct.unpack_from("<IIfffBBH", d, 12)
    boot, session, wcrc, front, link = struct.unpack_from("<IIIHB", d, 36)
    tail = struct.unpack_from("<8I", d, 52)
    tx_pkts, tx_bytes, tx_fail, tx_retx, rx_pkts, rx_bad, rx_gap, rx_dup = tail
    return dict(task=struct.unpack_from("<H", d, 4)[0], done=done, total=total, ms=ms, state=state,
                boot=boot, session=session, wcrc=wcrc, front=front, link=link,
                tx_pkts=tx_pkts, tx_fail=tx_fail, tx_retx=tx_retx,
                rx_pkts=rx_pkts, rx_bad=rx_bad, rx_gap=rx_gap, rx_dup=rx_dup)


def main(argv=None):
    ap = argparse.ArgumentParser(description="一键复现板端 ROI 演示")
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--scene", type=int, default=0, help="0=LongKou 1=HongHu 2=HanChuan")
    ap.add_argument("--wcrc", default="27231983", help="权重包 CRC32（INFO 里能查到）")
    ap.add_argument("--session", default="5a5a0001", help="会话号；板卡已绑定别的会话就改这里")
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--quiet", action="store_true", help="不打印逐行/逐像素明细（大块时用）")
    ap.add_argument("--timeout", type=float, default=40.0)
    args = ap.parse_args(argv)

    wcrc = int(args.wcrc, 16)
    scene = args.scene
    board = Board(args.board, args.port)
    board.session = int(args.session, 16)

    print("[1/4] 连板卡 %s:%d（PING …）" % board.addr)
    board.ping()
    ack, st = board.drain(1.5)
    if st is None:
        print("      没有收到 STATUS。检查：板卡上电、网线、本机 IP 设成 192.168.1.102/24；"
              "或者板卡已绑定别的会话号（换 --session）")
        return 1
    print("      boot_id=%08x  当前模型 wcrc=%08x  状态 state=%d  任务=%d"
          % (st["boot"], st["wcrc"], st["state"], st["task"]))

    print("[2/4] 选择场景 %s（%d）的权重包" % (NAMES.get(scene, "?"), scene))
    if st["wcrc"] == wcrc:
        print("      已经是这个版本，跳过")
    else:
        board.send(WACT, struct.pack("<BBHI", scene, 0, 0, wcrc))
        print("      等待从 SD 装入权重（480 KB，约 1~3 s，DP 会短暂停顿）…")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            board.ping()
            _ack, st = board.drain(0.4)
            if st and st["wcrc"] == wcrc:
                break
        else:
            print("      超时：wcrc 仍是 %08x（该版本可能没登记在 SD 上）"
                  % (st["wcrc"] if st else 0))
            return 1
        print("      已选中 wcrc=%08x" % st["wcrc"])

    print("[3/4] 下发 ROI 任务 %d 行 × %d 列（(0,0) 起点，mode=1）" % (args.rows, args.cols))
    task = (int(time.time() * 1000) & 0x7FFF) + 1
    while task == st["task"]:
        task = (task + 1) & 0x7FFF or 1
    board.task = task
    board.ping()
    board.drain(0.2)
    body = struct.pack("<BBBBHHHHII", 1, scene, 0, 0, 0, 0, args.rows, args.cols, wcrc, board.session)
    board.send(START, body)
    print("      task=%d 已发出，等 ACK 与 ROW" % task)

    rows = {}
    states = []

    def on_row(row, col, words):
        rows[row] = words
        if not args.quiet:
            print("      ROW y=%d: %s" % (row, " ".join("%08X" % w for w in words)))

    def on_status(s):
        if s["task"] == task and (not states or states[-1] != s["state"]):
            states.append(s["state"])
            print("      STATUS state=%d done=%d/%d front=%d ms/px=%s"
                  % (s["state"], s["done"], s["total"], s["front"],
                     ("%.3f" % s["ms"]) if math.isfinite(s["ms"]) else "NaN"))

    got_ack, final = board.drain(1.0, on_row=on_row, on_status=on_status)
    if not got_ack:
        print("      还没收到 START 的 ACK，再等一会儿（板卡主循环要跑到包边界）")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        board.ping()
        _a, s = board.drain(0.4, on_row=on_row, on_status=on_status)
        if s and s["task"] == task:
            final = s
            if s["state"] == 3:
                break
    else:
        print("      超时：没等到 DONE")
        return 1
    # DONE 表示算完，ROW 可能还在队列里没发完，再收一小段
    for _ in range(3):
        if len(rows) >= args.rows:
            break
        board.ping()
        _a, s = board.drain(0.6, on_row=on_row, on_status=on_status)
        if s and s["task"] == task:
            final = s

    print("[4/4] 结果")
    if not rows:
        print("      一个像素也没收到（看上面的拒绝码）")
        return 1
    for y in sorted(rows):
        for x, w in enumerate(rows[y]):
            if not args.quiet:
                print("      (x=%d,y=%d) 类别=%-2d 置信度=%.3f  字=%08X"
                      % (x, y, w & 0xFF, (w >> 16) / 65536.0, w))
    ok = final["state"] == 3 and final["done"] == final["total"]
    if len(rows) != args.rows:
        print("      注意：%d 行结果里只收到 %d 行的 UDP（缺的行可在 DP 上直接看，板端已算完）"
              % (args.rows, len(rows)))
    counters = "tx_fail=%d tx_retx=%d rx_bad=%d rx_gap=%d rx_dup=%d" % (
        final["tx_fail"], final["tx_retx"], final["rx_bad"], final["rx_gap"], final["rx_dup"])
    print("      %s  done=%d/%d  %s" % ("DONE" if ok else "INCOMPLETE",
                                        final["done"], final["total"], counters))
    print()
    print("现在看板卡接的显示器：")
    print("  · 任务卡应为「已完成」，图上是 %d×%d 的小块结果" % (args.cols, args.rows))
    print("  · 模型/权重那一行应显示已选中的版本，不再是「尚未选择模型」")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
