# -*- coding: utf-8 -*-
"""板卡存活检查：给 GCS 正式固件发一个 UDP PING，收到 PONG 就说明它在跑、网络通。

GCS 版固件的串口是静默的（SERIAL_DEBUG=false），所以上电下载后用这个脚本代替"看串口"。

用法：
    D:\\Anaconda\\python.exe tools\\ping_board.py
    D:\\Anaconda\\python.exe tools\\ping_board.py --board 192.168.1.10
"""

import argparse
import socket
import struct
import sys
import time

HDR = struct.Struct("<HBBHHI")          # magic, kind, ver, task, seq, t_us
MAGIC, PING, PONG, STATUS = 0x4548, 5, 0x84, 0x82


def main(argv=None):
    ap = argparse.ArgumentParser(description="GCS 固件 UDP PING 存活检查")
    ap.add_argument("--board", default="192.168.1.10", help="板卡 IP（默认 192.168.1.10）")
    ap.add_argument("--port", type=int, default=5010, help="板卡 UDP 端口（默认 5010）")
    ap.add_argument("--timeout", type=float, default=1.0, help="等待回包秒数（默认 1.0）")
    args = ap.parse_args(argv)

    board = (args.board, args.port)
    stamp = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
    session = 0x12345678
    pkt = HDR.pack(MAGIC, PING, 1, 0, 0, stamp) + struct.pack("<I", session)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))                  # 回包发回这个临时端口，不要占用 5011
    sock.settimeout(args.timeout)

    print("PING -> %s:%d" % board)
    try:
        sock.sendto(pkt, board)
        data, peer = sock.recvfrom(2048)
    except socket.timeout:
        print("没有回包。逐项查：网线 / 板卡 IP 192.168.1.10 / PC 是否 192.168.1.102 / "
              "防火墙 / 固件是否已经 READY")
        return 1
    except OSError as exc:
        print("发送失败：%s" % exc)
        return 1

    kind = data[2] if len(data) > 2 else -1
    print("收到 %d 字节，来自 %s:%d，kind=0x%02x" % (len(data), peer[0], peer[1], kind))
    if kind == PONG:
        print("PONG：板卡固件在跑，网络可达。")
        return 0
    if kind == STATUS:
        print("收到 STATUS（不是 PONG，但说明它在跑）。")
        return 0
    print("回包类型不是 PONG/STATUS，检查报文版本或板端固件。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
