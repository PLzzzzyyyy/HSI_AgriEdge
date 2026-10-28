"""模拟板卡：按 protocol.py 草案收命令、用 PC 推理出结果、以 UDP 回 ROW / STATUS / ACK。只用于在没有板子时验证地面站的板卡链路。

    D:/pytorch/python.exe gcs/fake_board.py [--gcs 127.0.0.1]
地面站"链路与下发"里选板卡 UDP、地址填 127.0.0.1。STATUS 的 flags bit0 置 1，界面标"模拟板"；ms_per_px 是本机 GPU 计时，不是板上数字。
"""
import argparse
import socket
import threading
import time
import zlib

import numpy as np

import engine as E
import protocol as P
import scenes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gcs', default='127.0.0.1')
    a = ap.parse_args()
    eng = E.Engine()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', P.BOARD_PORT))
    gcs = (a.gcs, P.GCS_PORT)
    st = dict(seq=0, task=0, state=0, done=0, total=0, ms=0.0, stop=threading.Event(), go=threading.Event(), wbuf=None)
    st['go'].set()

    def tx(t, body=b''):
        st['seq'] += 1
        sock.sendto(P.pack(t, st['task'], st['seq'], body), gcs)

    def status():
        tx(P.STATUS, P.STATUS_B.pack(st['done'], st['total'], st['ms'], 45.0, 0.0, st['state'], 1, 0))

    def job(mode, scene, ver, rect):
        sc = eng.get_scene(scene)
        if mode == P.MODES['eval']:
            coords = np.argwhere(sc.test_mask > 0)
        else:
            r0, c0, h, w = (0, 0, sc.H, sc.W) if mode == P.MODES['scan'] else rect
            rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
            coords = np.stack([rr.ravel(), cc.ravel()], 1)
        st.update(done=0, total=len(coords), state=1)
        t_last, t_comp = 0.0, 0.0
        for i in range(0, len(coords), 1024):
            st['go'].wait()
            if st['stop'].is_set():
                st['state'] = 0; status(); return
            c = coords[i:i + 1024]
            t0 = time.perf_counter()
            lab, conf, _ = eng.infer(scene, ver, c)
            t_comp += time.perf_counter() - t0
            words = P.encode_class(lab.astype(np.int64) - 1, conf)
            # 按连续行段切包
            brk = np.nonzero((np.diff(c[:, 0]) != 0) | (np.diff(c[:, 1]) != 1))[0] + 1
            for s, e in zip(np.r_[0, brk], np.r_[brk, len(c)]):
                for k in range(s, e, P.ROW_MAX):
                    n = min(P.ROW_MAX, e - k)
                    tx(P.ROW, P.ROW_B.pack(int(c[k, 0]), int(c[k, 1]), n, 0) + words[k:k + n].astype('<u4').tobytes())
            st['done'] += len(c)
            st['ms'] = 1000 * t_comp / st['done']
            if time.time() - t_last > 0.25:
                status(); t_last = time.time()
        st['state'] = 3
        status()

    print(f'模拟板卡监听 {P.BOARD_PORT}，结果发往 {gcs}')
    last_status = 0
    sock.settimeout(0.5)
    while True:
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            if time.time() - last_status > 1:
                status(); last_status = time.time()
            continue
        except ConnectionResetError:     # Windows：地面站未开板卡源时，发出的 STATUS 回 ICMP 不可达，下一次 recvfrom 报 10054
            continue
        u = P.unpack(data)
        if not u:
            continue
        t, task, seq, body = u
        if t == P.START:
            mode, si, vi, _, r0, c0, h, w = P.START_B.unpack_from(body)
            st['stop'].set(); st['go'].set(); time.sleep(0.05)
            st['stop'] = threading.Event(); st['task'] = task
            st.update(done=0, total=0, state=1)      # 换任务号的同时清掉上个任务的"完成"，否则加载场景期间的 STATUS 会让新任务被判完成
            scene = list(scenes.SCENES)[si]
            ver = E.VERSIONS[scene][vi]['id']
            print(f'START task {task} mode {mode} {scene} {ver} rect {(r0, c0, h, w)}')
            threading.Thread(target=job, args=(mode, scene, ver, (r0, c0, h, w)), daemon=True).start()
        elif t == P.STOP:
            st['stop'].set(); st['go'].set()
        elif t == P.PAUSE:
            st['go'].clear(); st['state'] = 2
        elif t == P.RESUME:
            st['go'].set(); st['state'] = 1
        elif t == P.WCHUNK:
            sidx, slot, _, off, total, crc = P.WCHUNK_B.unpack_from(body)
            part = body[P.WCHUNK_B.size:]
            if off == 0 or st['wbuf'] is None or len(st['wbuf']) != total:
                st['wbuf'] = bytearray(total)
            st['wbuf'][off:off + len(part)] = part
            code = 0
            if off + len(part) >= total and (zlib.crc32(bytes(st['wbuf'])) & 0xFFFFFFFF) != crc:
                code = 1
            st['task'] = task
            tx(P.ACK, P.ACK_B.pack(P.WCHUNK, code, 0, off + len(part)))


if __name__ == '__main__':
    main()
