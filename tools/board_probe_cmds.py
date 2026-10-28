# -*- coding: utf-8 -*-
"""探测板端固件到底支持哪些命令：对每个命令发一包，看回 ACK / 不回。"""
import socket, struct, time, sys

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548
SESS = 0x5a5a0001
BOARD = ("192.168.1.10", 5010)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", 0))
sock.settimeout(0.2)
seq = [100]
t0 = time.perf_counter_ns()


def send(kind, body=b""):
    seq[0] += 1
    t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
    sock.sendto(HDR.pack(MAGIC, kind, 1, 0, seq[0], t) + body, BOARD)
    return seq[0]


def drain(sec):
    out = []
    end = time.monotonic() + sec
    while time.monotonic() < end:
        try:
            d, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        k = d[2]
        if k == 0x83 and len(d) >= 20:
            at, code, aseq, val = struct.unpack_from("<BBHI", d, 12)
            out.append("ACK(type=0x%02x code=%d seq=%d val=0x%08x)" % (at, code, aseq, val))
        elif k == 0x82:
            out.append("STATUS(wcrc=%08x)" % struct.unpack_from("<I", d, 44)[0])
        elif k == 0x84:
            out.append("PONG")
        elif k == 0x86:
            out.append("INFO_R")
        else:
            out.append("0x%02x" % k)
    return out


print("PING:", end=" ")
send(0x05, struct.pack("<I", SESS))
print(drain(0.5))

tests = [
    ("WACT 正确 crc scene0", 0x13, struct.pack("<BBHI", 0, 0, 0, 0x27231983)),
    ("WACT 错误 crc", 0x13, struct.pack("<BBHI", 0, 0, 0, 0xDEADBEEF)),
    ("WACT when=1", 0x13, struct.pack("<BBHI", 0, 1, 0, 0x27231983)),
    ("WCOMMIT 错误 crc", 0x12, struct.pack("<I", 0xDEADBEEF)),
    ("WBEGIN 非法 scene=9", 0x11, struct.pack("<BBHII16s", 9, 1, 0, 480576, 0x27231983, b"probe")),
    ("PROBE 点", 0x09, struct.pack("<BBHHHI", 0, 0, 10, 10, 0, 0)),
]
for name, kind, body in tests:
    s = send(kind, body)
    print("%-24s n=%2d -> %s" % (name, 12 + len(body), drain(0.8)))
