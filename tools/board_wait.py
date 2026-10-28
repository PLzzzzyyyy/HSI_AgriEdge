# -*- coding: utf-8 -*-
"""等板卡 READY：一直 PING，直到收到 STATUS 或超时。

    D:\\Anaconda\\python.exe tools\\board_wait.py --timeout 90
    ... --session 5a5a0001

退出码：0 收到 STATUS；1 超时。
"""

import argparse
import socket
import struct
import sys
import time

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548


def main(argv=None):
    ap = argparse.ArgumentParser(description="等板卡回 STATUS")
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--session", default="5a5a0001")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(0.2)
    session = int(args.session, 16)
    deadline = time.monotonic() + args.timeout
    seq = 0
    last_note = 0.0
    while time.monotonic() < deadline:
        t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
        sock.sendto(HDR.pack(MAGIC, 5, 1, 0, seq, t) + struct.pack("<I", session),
                    (args.board, args.port))
        seq = (seq + 1) & 0xFFFF
        end = time.monotonic() + 0.25
        while time.monotonic() < end:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            if len(data) >= 92 and data[2] == 0x82:
                boot = struct.unpack_from("<I", data, 36)[0]
                wcrc = struct.unpack_from("<I", data, 44)[0]
                state = data[32]
                task = struct.unpack_from("<H", data, 4)[0]
                if not args.quiet:
                    print("板卡在线：boot_id=%08x  模型=%08x  state=%d  任务=%d"
                          % (boot, wcrc, state, task))
                return 0
        if not args.quiet and time.monotonic() - last_note > 5:
            last_note = time.monotonic()
            print("  还在等板卡回包…（检查：板卡上电了吗？网线接了吗？本机 IP 是否 192.168.1.102/24）")
    if not args.quiet:
        print("超时：%d 秒内没有收到 STATUS" % int(args.timeout))
    return 1


if __name__ == "__main__":
    sys.exit(main())
