# -*- coding: utf-8 -*-
"""把板端已登记的某个模型「激活」，并读回当前激活的 wcrc。

为什么需要这一步：GCS 正式固件刚起来时 STATUS 里的 wcrc = 0（DP 上显示「尚未选择模型」），
任务要有模型才能跑。地面站里点选场景/模型发的是 WACT；这里用等价的最小工具做同一件事。

协议（docs/protocol.md §2.3 / §2.8）：
  0x05 PING  地→板 u32 session（板卡记下源地址；会话号只在没绑定时锁定）
  0x13 WACT  地→板 u8 scene, u8 when, u16 pad, u32 crc32
       when 0 = 下一任务起用（单库当前实现）；板卡在空闲时做 LOAD_W 再回 ACK，
       权重包 480 KB 从 SD 读入，可能要 1~3 s，所以这里等得久一点。
  0x82 STATUS v1 尾部 offset 44 = 当前 wcrc

序号注意：板卡按 seq 统计 rx_gap（前进跳跃会 +delta-1），所以本工具的 seq
从 --seq-start 起连续递增，跑完把基线留在最后一个 seq 上；随后的客户端从 0 开始
属于「后退」，不计 gap。

用法：
    D:\\Anaconda\\python.exe tools\\board_model.py --wcrc 27231983 --scene 0
"""

import argparse
import socket
import struct
import sys
import time

HDR = struct.Struct("<HBBHHI")
MAGIC = 0x4548
PING, WACT = 0x05, 0x13
STATUS, ACK, PONG = 0x82, 0x83, 0x84


def main(argv=None):
    ap = argparse.ArgumentParser(description="激活板端已登记的模型并读回 wcrc")
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--session", default="5a5a0001", help="会话号（8 位 hex）")
    ap.add_argument("--scene", type=int, default=0, help="场景号（LongKou=0）")
    ap.add_argument("--wcrc", default="27231983", help="权重包 CRC32（8 位 hex）")
    ap.add_argument("--when", type=int, default=0, choices=(0, 1))
    ap.add_argument("--seq-start", type=int, default=0)
    ap.add_argument("--wait", type=float, default=20.0, help="等 LOAD_W 完成的最长秒数")
    args = ap.parse_args(argv)

    session = int(args.session, 16)
    wcrc = int(args.wcrc, 16)
    board = (args.board, args.port)
    seq = args.seq_start

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(0.2)

    def send(kind, body=b""):
        nonlocal seq
        t = (time.perf_counter_ns() // 1000) & 0xFFFFFFFF
        sock.sendto(HDR.pack(MAGIC, kind, 1, 0, seq, t) + body, board)
        seq += 1

    boot = None
    counters = None
    last_wcrc = None

    def pump(seconds, until=None):
        """收包；返回是否达成 until(wcrc) 条件。"""
        nonlocal boot, counters, last_wcrc
        end = time.monotonic() + seconds
        hit = False
        while time.monotonic() < end:
            try:
                d, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            k = d[2]
            if k == STATUS and len(d) >= 92:
                f = struct.unpack_from("<IIIHBB8IHHI", d, 36)
                boot = f[0]
                last_wcrc = f[2]
                counters = dict(tx_pkts=f[6], tx_bytes=f[7], tx_fail=f[8], tx_retx=f[9],
                                rx_pkts=f[10], rx_bad=f[11], rx_gap=f[12], rx_dup=f[13])
                if until is not None and last_wcrc == until:
                    hit = True
            elif k == ACK and len(d) >= 20:
                typ, code, acked, value = struct.unpack_from("<BBHI", d, 12)
                print("  ACK type=0x%02x code=%d seq=%d value=0x%08x" % (typ, code, acked, value))
            elif k == PONG:
                pass
        return hit

    # 1) PING：登记回包地址；板卡未绑定会话时这里锁定
    send(PING, struct.pack("<I", session))
    if not pump(1.0) and boot is None:
        print("板卡不回包：会话号已被别的会话锁定，或网络/固件状态不对。")
        return 1
    print("boot_id=%08x  当前 wcrc=%s  计数=%s"
          % (boot or 0, ("%08x" % last_wcrc) if last_wcrc is not None else "无", counters))
    if last_wcrc == wcrc:
        print("已经是目标模型，无需切换。")
        print("客户端请用：--boot-id %08x --session %08x" % (boot, session))
        return 0

    # 2) WACT：板卡在空闲时做 LOAD_W，读完 SD 上的包才回 ACK
    send(WACT, struct.pack("<BBHI", args.scene, args.when, 0, wcrc))
    print("WACT scene=%d when=%d crc=%08x（LOAD_W 期间 DP 会短暂停顿，正常）"
          % (args.scene, args.when, wcrc))
    if pump(args.wait, until=wcrc):
        print("wcrc=%08x 已生效" % last_wcrc)
        print("客户端请用：--boot-id %08x --session %08x" % (boot, session))
        print("计数=%s（rx_bad/gap/dup 应全为 0）" % counters)
        return 0
    print("等了 %.0f s 仍未切换；最后 wcrc=%s 计数=%s"
          % (args.wait, ("%08x" % last_wcrc) if last_wcrc is not None else "无", counters))
    return 1


if __name__ == "__main__":
    sys.exit(main())
