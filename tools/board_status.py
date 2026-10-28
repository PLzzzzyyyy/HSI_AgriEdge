# -*- coding: utf-8 -*-
"""打印板端 STATUS 的计数器与当前任务状态（排查用）。

D:\\Anaconda\\python.exe tools\\board_status.py --session 5a5a0001
"""
import argparse, socket, struct, time, sys

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--session", default="5a5a0001")
    ap.add_argument("--seconds", type=float, default=1.2)
    args = ap.parse_args(argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(0.2)
    t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
    sock.sendto(HDR.pack(MAGIC, 5, 1, 0, 1, t) + struct.pack("<I", int(args.session, 16)),
                (args.board, args.port))

    end = time.monotonic() + args.seconds
    shown = 0
    while time.monotonic() < end and shown < 3:
        try:
            d, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        if d[2] != 0x82 or len(d) != 92:
            continue
        shown += 1
        done, total, ms, temp, power, state, flags, pad = struct.unpack_from("<IIfffBBH", d, 12)
        (boot, session, wcrc, front, link, _o5, tx_pkts, tx_bytes, tx_fail, tx_retx,
         rx_pkts, rx_bad, rx_gap, rx_dup, down_cnt, _o15, down_ms, _o17) = \
            struct.unpack_from("<IIIHBB8IHHI", d, 36) + (None,)
        print("boot=%08x session=%08x wcrc=%08x state=%d task=%d front=%d done=%d/%d"
              % (boot, session, wcrc, state, struct.unpack_from("<H", d, 8)[0], front, done, total))
        print("  tx=%d pkts/%d B fail=%d retx=%d   rx=%d pkts bad=%d gap=%d dup=%d   down=%d/%d ms  link=%d"
              % (tx_pkts, tx_bytes, tx_fail, tx_retx, rx_pkts, rx_bad, rx_gap, rx_dup, down_cnt, down_ms, link))
    if not shown:
        print("没有收到 STATUS：会话号不对或板卡没在回包")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
