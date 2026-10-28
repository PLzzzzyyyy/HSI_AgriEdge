"""C3 外设测试的 PC 端：UDP 收发测试（对板上 src/ps/periph/periph_net.cpp，报文格式见该文件头）与 SD 文件 CRC32。

  python tools/periph_pc.py all                     # 往返 + 两个方向各两档（限速 100 Mbps、不限速），给 PASS/FAIL，结果写 board/periph/
  python tools/periph_pc.py ping [-n 1000]
  python tools/periph_pc.py tx [-n 20000] [--size 1412] [--rate 0]    # 板 -> PC，--rate 单位 kbps（UDP 载荷），0 = 不限速
  python tools/periph_pc.py rx [-n 20000] [--size 1412] [--rate 0]    # PC -> 板
  python tools/periph_pc.py crc [--root E:/scenes]  # SD 测试文件的大小与 CRC32，对照 periph_sd.cpp 里的表（拷卡后查卡上文件）

PC 网卡设静态 192.168.1.102/24（板 192.168.1.10）；本机端口 5011 与地面站相同，Windows 防火墙对 python 放行一次即可。
PASS（C3b）：往返回包 >= 99.9% 且内容一致；两个方向在 100 Mbps 限速下丢包 <= 0.1%、数据校验 0 错。
不限速两档只记录：Windows 收包和 Python 发包本身可能是瓶颈，那里的丢包不说明板子有问题。
包长默认 1412 B（docs/protocol.md 的 UDP 载荷上限，不分片），--size 最大 1472。
"""
import argparse
import json
import os
import re
import socket
import struct
import time
import zlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAGIC = 0x54553343                      # 字节序列 "C3UT"
HDR = struct.Struct('<IHHII')           # magic, cmd, flags, seq, arg
REPORT = struct.Struct('<8I')           # packets, bytes, elapsed_us, errors, extra, seq_max, link_mbps, reserved
PING, PONG, TXREQ, TXDATA, RXDATA, RXSTAT, REPORT_CMD, RXRESET = 1, 2, 3, 4, 5, 6, 7, 8
PATTERN = bytes(range(256)) * 8         # 序号 seq 的数据 = PATTERN[seq & 255:][:size - 16]
LOSS_MAX = 0.001
resets = 0                              # Windows 10054 次数（多半是板上程序没在跑）


def recv(sock, board_ip, deadline):
    """收一个本测试的包，返回 (cmd, seq, arg, data)，超时返回 None。"""
    global resets
    while True:
        left = deadline - time.perf_counter()
        if left <= 0:
            return None
        sock.settimeout(left)
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            return None
        except ConnectionResetError:
            resets += 1
            continue
        if addr[0] != board_ip or len(data) < HDR.size:
            continue
        magic, cmd, _, seq, arg = HDR.unpack_from(data)
        if magic == MAGIC:
            return cmd, seq, arg, data


def drain(sock):
    sock.settimeout(0)
    try:
        while True:
            sock.recvfrom(2048)
    except (BlockingIOError, socket.timeout, ConnectionResetError, OSError):
        pass


def wait_report(sock, a, kind, timeout):
    deadline = time.perf_counter() + timeout
    while True:
        r = recv(sock, a.board, deadline)
        if r is None:
            return None
        cmd, _, arg, data = r
        if cmd == REPORT_CMD and arg == kind and len(data) >= HDR.size + REPORT.size:
            return dict(zip(('packets', 'bytes', 'elapsed_us', 'errors', 'extra', 'seq_max', 'link_mbps'),
                            REPORT.unpack_from(data, HDR.size)))


def pct(v, q):
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def do_ping(sock, a, n, size, timeout=0.2):
    rtts, lost, bad = [], 0, 0
    for i in range(n):
        body = os.urandom(size - HDR.size)
        t0 = time.perf_counter()
        sock.sendto(HDR.pack(MAGIC, PING, 0, i, 0) + body, (a.board, a.board_port))
        deadline = t0 + timeout
        while True:
            r = recv(sock, a.board, deadline)
            if r is None:
                lost += 1
                break
            cmd, seq, _, data = r
            if cmd == PONG and seq == i:            # 超时后迟到的旧 PONG 序号不对，跳过
                rtts.append((time.perf_counter() - t0) * 1e6)
                bad += data[HDR.size:] != body
                break
    rtts.sort()
    res = {'sent': n, 'size': size, 'replies': len(rtts), 'lost': lost, 'payload_mismatch': bad,
           'rtt_us': {'min': rtts[0] if rtts else None, 'mean': sum(rtts) / len(rtts) if rtts else None,
                      'p50': pct(rtts, 0.5), 'p99': pct(rtts, 0.99), 'max': rtts[-1] if rtts else None}}
    res['pass'] = len(rtts) >= n - n // 1000 and bad == 0
    return res


def warm_up(sock, a):
    r = do_ping(sock, a, 3, 64, timeout=0.5)
    if r['replies'] == 0:
        raise SystemExit(f'board {a.board}:{a.board_port} not answering (menu key u pressed? cable? PC IP 192.168.1.102/24?'
                         f' 10054 resets seen: {resets})')


def do_tx(sock, a, n, size, rate_kbps):
    """板 -> PC：请板发 n 个包，PC 逐包核对序号与数据，最后收板上 REPORT。"""
    drain(sock)
    expect = [PATTERN[k:k + size - HDR.size] for k in range(256)]
    got = bytearray(n)
    uniq = dup = bad = reorder = rx_bytes = 0
    last_seq, first_t, last_t, report = -1, None, None, None
    sock.sendto(HDR.pack(MAGIC, TXREQ, 0, 0, 0) + struct.pack('<3I', n, size, rate_kbps), (a.board, a.board_port))
    wire = n * size * 8 / (rate_kbps * 1e3 if rate_kbps else 5e8)
    deadline, stop = time.perf_counter() + 3 + 2 * wire, None
    while True:
        now = time.perf_counter()
        end = min(deadline, stop) if stop else deadline
        if last_t is not None:
            end = min(end, last_t + 2.0)                # 2 s 没新包就结束
        r = recv(sock, a.board, end)
        if r is None:
            break
        cmd, seq, arg, data = r
        if cmd == TXDATA:
            t = time.perf_counter()
            first_t = first_t if first_t is not None else t
            last_t = t
            if seq >= n:
                bad += 1
                continue
            if got[seq]:
                dup += 1
            else:
                got[seq] = 1
                uniq += 1
                rx_bytes += len(data)
            reorder += seq < last_seq
            last_seq = max(last_seq, seq)
            bad += len(data) != size or data[HDR.size:] != expect[seq & 255]
        elif cmd == REPORT_CMD and arg == TXREQ and len(data) >= HDR.size + REPORT.size:
            report = dict(zip(('packets', 'bytes', 'elapsed_us', 'errors', 'extra', 'seq_max', 'link_mbps'),
                              REPORT.unpack_from(data, HDR.size)))
            stop = now + 0.3                            # REPORT 在最后一个数据包之后发，再等 0.3 s 收尾
    span = (last_t - first_t) if uniq > 1 else 0
    res = {'count': n, 'size': size, 'rate_cap_kbps': rate_kbps, 'received_unique': uniq, 'duplicates': dup,
           'lost': n - uniq, 'loss': (n - uniq) / n, 'payload_errors': bad, 'out_of_order': reorder,
           'pc_mbps': rx_bytes * 8 / span / 1e6 if span else None, 'board': report}
    if report:
        res['board_mbps'] = report['bytes'] * 8 / report['elapsed_us'] if report['elapsed_us'] else None
    res['pass'] = bool(report) and report['errors'] == 0 and res['loss'] <= LOSS_MAX and bad == 0
    return res


def do_rx(sock, a, n, size, rate_kbps):
    """PC -> 板：清板上计数，发 n 个包（可限速），再取板上 REPORT。"""
    drain(sock)
    board = (a.board, a.board_port)
    for _ in range(3):
        sock.sendto(HDR.pack(MAGIC, RXRESET, 0, 0, 0), board)
        if wait_report(sock, a, RXRESET, 1.0) is not None:
            break
    else:
        return {'count': n, 'size': size, 'rate_cap_kbps': rate_kbps, 'error': 'no REPORT for RXRESET', 'pass': False}
    pkts = [HDR.pack(MAGIC, RXDATA, 0, i, n) + PATTERN[i & 255:(i & 255) + size - HDR.size] for i in range(n)]
    gap = size * 8 / (rate_kbps * 1e3) if rate_kbps else 0
    sock.settimeout(None)                               # 发送缓冲满时阻塞等待，不要因超时抛异常
    t0 = time.perf_counter()
    nxt = t0
    for p in pkts:
        if gap:
            while time.perf_counter() < nxt:
                pass
            nxt += gap
        sock.sendto(p, board)
    send_s = time.perf_counter() - t0
    time.sleep(0.3)
    report = None
    for _ in range(3):
        sock.sendto(HDR.pack(MAGIC, RXSTAT, 0, 0, 0), board)
        report = wait_report(sock, a, RXSTAT, 1.0)
        if report is not None:
            break
    res = {'count': n, 'size': size, 'rate_cap_kbps': rate_kbps, 'pc_send_s': send_s,
           'pc_send_mbps': n * size * 8 / send_s / 1e6 if send_s else None, 'board': report}
    if report:
        res['lost'] = n - report['packets']
        res['loss'] = res['lost'] / n
        res['board_mbps'] = report['bytes'] * 8 / report['elapsed_us'] if report['elapsed_us'] else None
    res['pass'] = (bool(report) and report['errors'] == 0 and 0 <= res['loss'] <= LOSS_MAX
                   and report['bytes'] == report['packets'] * size)
    return res


def fmt_ping(r):
    t = r['rtt_us']
    rtt = (f"RTT us min {t['min']:.0f} mean {t['mean']:.0f} p50 {t['p50']:.0f} p99 {t['p99']:.0f} max {t['max']:.0f}"
           if r['replies'] else 'no replies')
    return f"ping  {r['replies']}/{r['sent']} x {r['size']} B, payload mismatch {r['payload_mismatch']}, {rtt}"


def fmt_dir(name, r):
    cap = f"{r['rate_cap_kbps'] / 1000:g} Mbps cap" if r['rate_cap_kbps'] else 'no cap'
    if r.get('error') or not r.get('board'):
        return f"{name} {cap}: {r.get('error', 'no REPORT from board')}"
    b = r['board']
    s = f"{name} {cap}: {r['count']} x {r['size']} B, lost {r['lost']} ({r['loss'] * 100:.3f}%), board errors {b['errors']}"
    if name == 'tx':
        pc = f"{r['pc_mbps']:.1f}" if r['pc_mbps'] else '-'
        s += (f", payload errors {r['payload_errors']}, out-of-order {r['out_of_order']}; board sent {r.get('board_mbps') or 0:.1f} Mbps"
              f" (ring waits {b['extra']}), PC received {pc} Mbps")
    else:
        s += (f", out-of-order {b['extra']}; PC sent {r['pc_send_mbps']:.1f} Mbps, board received "
              f"{r.get('board_mbps') or 0:.1f} Mbps")
    return s + f", link {b['link_mbps']} Mbps"


def cmd_crc(a):
    src = (ROOT / 'src/ps/periph/periph_sd.cpp').read_text(encoding='utf-8')
    table = {m[0]: (int(m[1]), int(m[2], 16)) for m in re.findall(r'"1:/scenes/([^"]+)", (\d+)u, 0x([0-9A-Fa-f]+)u', src)}
    root = Path(a.root)
    ok_all = bool(table)
    for rel, (size0, crc0) in table.items():
        p = root / rel
        if not p.exists():
            print(f'{rel:45s} missing under {root}')
            ok_all = ok_all and rel != 'longkou/cube_i16.bin'
            continue
        c = 0
        with open(p, 'rb') as fh:
            while True:
                b = fh.read(1 << 24)
                if not b:
                    break
                c = zlib.crc32(b, c)
        ok = p.stat().st_size == size0 and c == crc0
        ok_all = ok_all and ok
        print(f'{rel:45s} {p.stat().st_size:11d} B crc32 0x{c:08X}  table {size0} 0x{crc0:08X}  {"OK" if ok else "MISMATCH"}')
    print('CRC table', 'MATCHES' if ok_all else 'DIFFERS (re-exported data? update FILES in periph_sd.cpp, or re-copy the card)')

    return 0 if ok_all else 1

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['all', 'ping', 'tx', 'rx', 'crc'])
    ap.add_argument('-n', type=int, default=None, help='packets (ping 1000, tx/rx 20000)')
    ap.add_argument('--size', type=int, default=1412, help='UDP payload bytes incl. 16 B header, 64..1472')
    ap.add_argument('--rate', type=int, default=0, help='kbps cap of UDP payload, 0 = none')
    ap.add_argument('--board', default='192.168.1.10')
    ap.add_argument('--board-port', type=int, default=5010)
    ap.add_argument('--port', type=int, default=5011, help='local UDP port')
    ap.add_argument('--root', default=str(ROOT / 'data/scenes'), help='crc: folder holding <scene>/... (SD card: E:/scenes)')
    ap.add_argument('--out', default=str(ROOT / 'board/periph'), help='all: folder for the JSON result')
    a = ap.parse_args()
    if a.cmd == 'crc':
        return cmd_crc(a)
    if not 64 <= a.size <= 1472:
        raise SystemExit('--size must be 64..1472')
    if a.n is not None and not 1 <= a.n <= 2000000:
        ap.error('-n must be 1..2000000')
    if not 0 <= a.rate <= 1000000:
        ap.error('--rate must be 0..1000000 kbps')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 << 20)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 << 20)
    sock.bind(('0.0.0.0', a.port))
    if a.cmd == 'ping':
        result = do_ping(sock, a, a.n or 1000, a.size)
        print(fmt_ping(result), 'PASS' if result['pass'] else 'FAIL')
        return 0 if result['pass'] else 1
    warm_up(sock, a)
    if a.cmd == 'tx':
        result = do_tx(sock, a, a.n or 20000, a.size, a.rate)
        print(fmt_dir('tx', result), 'PASS' if result['pass'] else 'FAIL')
        return 0 if result['pass'] else 1
    if a.cmd == 'rx':
        result = do_rx(sock, a, a.n or 20000, a.size, a.rate)
        print(fmt_dir('rx', result), 'PASS' if result['pass'] else 'FAIL')
        return 0 if result['pass'] else 1
    res = {'time': datetime.now().isoformat(timespec='seconds'), 'board': f'{a.board}:{a.board_port}', 'size': a.size}
    res['ping'] = do_ping(sock, a, 1000, a.size)
    print(fmt_ping(res['ping']))
    for key, fn, n, rate in (('tx_100M', do_tx, 20000, 100000), ('tx_max', do_tx, 50000, 0),
                             ('rx_100M', do_rx, 20000, 100000), ('rx_max', do_rx, 50000, 0)):
        res[key] = fn(sock, a, n, a.size, rate)
        print(fmt_dir(key[:2], res[key]))
    res['windows_10054'] = resets
    res['pass'] = res['ping']['pass'] and res['tx_100M']['pass'] and res['rx_100M']['pass']
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"pc_udp_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(res, indent=1), encoding='utf-8')
    print(f"C3b UDP {'PASS' if res['pass'] else 'FAIL'} (ping + tx/rx at 100 Mbps; no-cap rows are recorded only) -> {path}")

    return 0 if res['pass'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
