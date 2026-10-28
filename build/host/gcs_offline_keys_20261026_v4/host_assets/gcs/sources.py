"""数据源：PC 推理（GPU 浮点参考）与板卡 UDP（协议草案 protocol.py）。界面不区分来源，只收"像素块"。

回调约定（都在工作线程里调用，server 负责转回事件循环）：
    on_chunk(coords (n,2) int, labels (n,) uint8 1 起, conf (n,) float32)
    on_done(reason)   reason ∈ 'done' / 'stopped' / 'error:<msg>'
"""
import socket
import subprocess
import threading
import time

import numpy as np

import protocol as P
from engine import VERSIONS, package_bytes
import scenes

BATCH = 1024


class Control:
    def __init__(self):
        self.stop = threading.Event()
        self.go = threading.Event()
        self.go.set()


class GpuMonitor:
    """nvidia-smi 每秒一次：整卡功耗、温度、利用率（功耗是整张显卡，不只是推理）。"""

    def __init__(self):
        self.data = dict(power_w=None, temp_c=None, util=None)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        q = ['nvidia-smi', '--query-gpu=power.draw,temperature.gpu,utilization.gpu', '--format=csv,noheader,nounits']
        while True:
            try:
                out = subprocess.run(q, capture_output=True, text=True, timeout=3,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
                p, t, u = [x.strip() for x in out.strip().splitlines()[0].split(',')]
                self.data = dict(power_w=float(p), temp_c=float(t), util=float(u))
            except Exception:
                self.data = dict(power_w=None, temp_c=None, util=None)
                time.sleep(4)
            time.sleep(1)


class PcSource:
    name = 'pc'

    def __init__(self, engine):
        self.engine = engine
        self.gpu = GpuMonitor()
        self.ctl = None

    def describe(self):
        return dict(source='pc', label=f'PC 推理 · {self.engine.device_name}', link='local', board_ip=None)

    def telemetry(self):
        return dict(self.gpu.data, device=self.engine.device_name)

    def start(self, run, on_chunk, on_done, pace_rows=0.0):
        self.ctl = ctl = Control()

        def work():
            try:
                coords = run.coords
                t_row = 1.0 / pace_rows if pace_rows > 0 else 0.0
                for i in range(0, len(coords), BATCH):
                    ctl.go.wait()
                    if ctl.stop.is_set():
                        return on_done('stopped')
                    c = coords[i:i + BATCH]
                    t0 = time.perf_counter()
                    lab, conf, _ = self.engine.infer(run.scene, run.version, c)
                    dt = time.perf_counter() - t0
                    run.compute_s += dt
                    p = self.gpu.data.get('power_w')
                    if p:
                        run.energy_j += p * dt
                    on_chunk(c, lab, conf)
                    if t_row:        # 回放限速：只影响显示节奏，计算时间单独计
                        rows = len(np.unique(c[:, 0]))
                        time.sleep(max(0.0, rows * t_row - dt))
                on_done('done')
            except Exception as e:     # noqa: BLE001
                on_done(f'error:{e}')

        threading.Thread(target=work, daemon=True).start()

    def pause(self):
        if self.ctl:
            self.ctl.go.clear()

    def resume(self):
        if self.ctl:
            self.ctl.go.set()

    def stop(self):
        if self.ctl:
            self.ctl.stop.set()
            self.ctl.go.set()

    def upload_weights(self, scene, vid, progress):
        """PC 源：权重包"下发"就是切换本地模型，字节数照实报告。"""
        pkg = package_bytes(scene, vid)
        self.engine.get_model(scene, vid)
        progress(len(pkg or b''), len(pkg or b''))
        return dict(ok=True, bytes=len(pkg or b''), note='PC 源：本地切换模型')


class BoardSource:
    name = 'board'

    def __init__(self, board_ip='192.168.1.10', board_port=P.BOARD_PORT, gcs_port=P.GCS_PORT):
        self.addr = (board_ip, board_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        self.sock.bind(('0.0.0.0', gcs_port))
        self.sock.settimeout(0.5)
        self.task = 0
        self.seq = 0
        self.run = None
        self.cb = None
        self.acks = {}
        self.ack_ev = threading.Event()
        self.last_rx = 0.0
        self.stat = dict(rx_bytes=0, rx_pkts=0, tx_bytes=0, tx_pkts=0, lost=0, board=None)
        self.board_seq = None
        self.closed = False
        threading.Thread(target=self._rx, daemon=True).start()

    def close(self):
        self.closed = True
        self.sock.close()

    def describe(self):
        sim = bool(self.stat['board'] and self.stat['board'].get('simulated'))
        return dict(source='board', label='板卡 UDP' + ('（模拟板）' if sim else ''), link=self.link(),
                    board_ip=self.addr[0])

    def link(self):
        return 'up' if time.time() - self.last_rx < 2.0 else 'down'

    def telemetry(self):
        b = self.stat['board'] or {}
        return dict(power_w=b.get('power_w'), temp_c=b.get('temp_c'), util=None,
                    ms_per_px=b.get('ms_per_px'), device='AXU5EV-E' + ('（模拟）' if b.get('simulated') else ''),
                    link=self.link(), **{k: self.stat[k] for k in ('rx_bytes', 'rx_pkts', 'tx_bytes', 'tx_pkts', 'lost')})

    def _send(self, t, body=b''):
        self.seq += 1
        pkt = P.pack(t, self.task, self.seq, body)
        self.sock.sendto(pkt, self.addr)
        self.stat['tx_bytes'] += len(pkt)
        self.stat['tx_pkts'] += 1

    def _rx(self):
        while not self.closed:
            try:
                data, _ = self.sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            u = P.unpack(data)
            if not u:
                continue
            t, task, seq, body = u
            self.last_rx = time.time()
            self.stat['rx_bytes'] += len(data)
            self.stat['rx_pkts'] += 1
            if self.board_seq is not None and task == self.task:
                gap = (seq - self.board_seq - 1) & 0xFFFF
                if 0 < gap < 1000:
                    self.stat['lost'] += gap
            self.board_seq = seq
            if t == P.ROW and self.run is not None and task == self.task:
                row, col0, n, _ = P.ROW_B.unpack_from(body)
                lab0, conf = P.decode_class(body[P.ROW_B.size:P.ROW_B.size + 4 * n])
                coords = np.stack([np.full(n, row), np.arange(col0, col0 + n)], 1)
                self.cb[0](coords, lab0 + 1, conf)
            elif t == P.STATUS:
                done, total, ms, temp, pw, state, flags, _ = P.STATUS_B.unpack_from(body)
                self.stat['board'] = dict(done=done, total=total, ms_per_px=ms, temp_c=temp, power_w=pw,
                                          state=state, simulated=bool(flags & 1))
                if self.run is not None and task == self.task:
                    self.run.board_ms_per_px = ms
                    if state == 3:
                        run, self.run = self.run, None
                        self.cb[1]('done')
            elif t == P.ACK:
                acked, code, _, value = P.ACK_B.unpack_from(body)
                self.acks[acked] = (code, value)
                self.ack_ev.set()

    def start(self, run, on_chunk, on_done, pace_rows=0.0):
        self.task = (self.task + 1) & 0xFFFF
        self.board_seq = None
        self.run, self.cb = run, (on_chunk, on_done)
        r0, c0, rows, cols = run.rect or (0, 0, 0, 0)
        scene_idx = list(scenes.SCENES).index(run.scene)
        ver_idx = [v['id'] for v in VERSIONS[run.scene]].index(run.version)
        self._send(P.START, P.START_B.pack(P.MODES[run.kind], scene_idx, ver_idx, 0, r0, c0, rows, cols))

    def pause(self):
        self._send(P.PAUSE)

    def resume(self):
        self._send(P.RESUME)

    def stop(self):
        self._send(P.STOP)
        if self.run is not None:
            self.run = None
            self.cb[1]('stopped')

    def upload_weights(self, scene, vid, progress):
        """停等发送：每块等 ACK，超时重发 3 次。"""
        pkg = package_bytes(scene, vid)
        if pkg is None:
            return dict(ok=False, note='该版本没有导出权重包')
        slot = [v['id'] for v in VERSIONS[scene]].index(vid)
        sidx = list(scenes.SCENES).index(scene)
        for off, body in P.weight_chunks(pkg, sidx, slot):
            for _ in range(4):
                self.ack_ev.clear()
                self.acks.pop(P.WCHUNK, None)
                self._send(P.WCHUNK, body)
                if self.ack_ev.wait(0.5) and P.WCHUNK in self.acks:
                    break
            else:
                return dict(ok=False, bytes=off, note='板卡无应答')
            code, value = self.acks[P.WCHUNK]
            if code != 0:
                return dict(ok=False, bytes=off, note=f'板卡拒收 code={code}')
            progress(value, len(pkg))
        return dict(ok=True, bytes=len(pkg), note='CRC32 校验通过')
