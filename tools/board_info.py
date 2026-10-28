# -*- coding: utf-8 -*-
"""读板卡身份（boot_id）与引擎信息：先 PING 登记回包地址，再发 INFO 收 INFO_R。

为什么需要它：GCS 正式固件串口是静默的，而最小任务客户端
（tools/s2c_roi_client.py）要一个 8 位十六进制的 boot-id 才能发 START。
这个脚本用一个标准 INFO 查询把 boot_id 读回来（不下载、不复位、不发业务命令）。

协议见 docs/protocol.md：
  公共头 12 B：magic(0x4548) u16, type u8, ver u8, task u16, seq u16, t_us u32
  0x05 PING    地→板  u32 session
  0x84 PONG    板→地  u16 ping_seq, u16 pad, u32 t1, u32 t2
  0x07 INFO    地→板  无
  0x86 INFO_R  板→地  u32 boot_id, u8 协议版本, u8 引擎契约版本, u8 片上位宽, u8 条目数, 当前任务 24 B …

用法：
    D:\\Anaconda\\python.exe tools\\board_info.py
    D:\\Anaconda\\python.exe tools\\board_info.py --board 192.168.1.10 --raw
"""

import argparse
import socket
import struct
import sys
import time

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548
PING, INFO = 0x05, 0x07
PONG, STATUS, INFO_R = 0x84, 0x82, 0x86


def pkt(kind, payload=b"", task=0, seq=0):
    t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
    return HDR.pack(MAGIC, kind, 1, task, seq, t) + payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="读板卡 boot_id / 引擎信息（只发 PING + INFO）")
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--raw", action="store_true", help="把 INFO_R 原始字节也打出来")
    args = ap.parse_args(argv)

    board = (args.board, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(args.timeout)

    session = 0x5A5A0001
    print("PING -> %s:%d" % board)
    try:
        sock.sendto(pkt(PING, struct.pack("<I", session)), board)
        while True:
            data, peer = sock.recvfrom(4096)
            kind = data[2]
            if kind == PONG:
                print("PONG：板卡在线（回包地址已登记为 %s:%d）" % peer)
                break
            if kind == STATUS:
                print("收到 STATUS（板卡在线）")
                break
    except socket.timeout:
        print("没有回包。检查：网线接的是板子 PS 网口吗；PC 是否有 192.168.1.x 地址；"
              "板卡是否已经启动到 READY（看 DP 画面）；防火墙是否拦截")
        return 1

    print("INFO -> %s:%d" % board)
    try:
        sock.sendto(pkt(INFO), board)
        while True:
            data, peer = sock.recvfrom(4096)
            kind = data[2]
            if kind == INFO_R:
                break
    except socket.timeout:
        print("INFO 没有回 INFO_R（板卡可能还没 READY，或固件版本不支持 INFO）")
        return 1

    body = data[HDR.size:]
    if len(body) < 8:
        print("INFO_R 太短（%d B），协议可能不匹配" % len(body))
        return 1
    boot_id, proto, contract, width, entries = struct.unpack_from("<IBBBB", body, 0)
    print()
    print("boot_id      : %08x   （最小客户端 --boot-id 用这个）" % boot_id)
    print("协议版本     : %d" % proto)
    print("引擎契约版本 : %d" % contract)
    print("片上位宽     : %d bit" % width)
    print("模型登记条目 : %d" % entries)
    if args.raw:
        print("INFO_R 原始  : %s" % body.hex(" "))
        if len(body) > 8:
            print("后续字段     : %s" % body[8:8 + 24].hex(" "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
