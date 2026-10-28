#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC 单点探查 → DP 联动复核（接手 GPT 修复后的独立验证，不改任何发布身份）。

流程：复位下载 linked 固件 → 起原版控制台(本地演示身份) → 连接板卡 →
下发 5x3 任务 → 经 JTAG 读回 DP 帧缓存探针卡区域(前) → 网页同一接口发单点探查 →
再读回(后) → 回读板端记录核对 S2C PROBE 行 → 逐像素断言探针卡确实被画进 DP 帧。

每步单独一个 stage，可分开执行；中间态写在 --dir 的 state.json：
  python tools/recheck_pc_dp_probe.py all            # 一条命令跑全流程
  ... dl | serve | connect | task | dump --tag before | probe | dump --tag after | log | check

只读硬件动作：xsdb `connect` + `mrd`（不 reset、不 stop）；唯一的写动作是
dl stage 的复位下载（等价于 START_DEMO.bat 第 2 步，会替换板上固件）。
"""
import argparse
import asyncio
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'build/host/gcs_pc_dp_link_20261017'
CONSOLE = 'http://127.0.0.1:8765'
XSD_CANDIDATES = [Path('D:/AMD/2026.1/Vitis/bin/xsdb.bat'),
                  Path('C:/Xilinx/Vitis/2026.1/bin/xsdb.bat')]
VITIS_DIRS = [Path('D:/AMD/2026.1/Vitis'), Path('C:/Xilinx/Vitis/2026.1')]
ELF = ROOT / 'firmware/gcs_r1_abi4_app_linked.elf'
DISPLAY_W = 1920
# 探针卡几何（roi_canvas.h）：x 88..400, y 100..400
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 88, 100, 312, 300
COLORS = [(255, 0, 0), (238, 154, 0), (255, 255, 0), (0, 255, 0), (0, 255, 207),
          (0, 160, 255), (0, 0, 255), (176, 0, 255), (255, 182, 193), (139, 69, 19),
          (127, 255, 0), (255, 20, 147), (64, 224, 208), (255, 215, 0), (173, 255, 47),
          (220, 20, 60), (0, 206, 209), (147, 112, 219), (240, 230, 140), (255, 127, 80),
          (46, 139, 87), (192, 192, 192)]


def rgba(r, g, b):
    return 0xff000000 | (b << 16) | (g << 8) | r


BG = rgba(11, 16, 22)
LINE = rgba(32, 48, 65)
PANEL = rgba(17, 25, 35)
# 采样点：名称 -> (x, y)；前=开始探查前的期望值，后=探查后的期望值
POINTS = {
    'swatch_center': (112, 216),   # 类别色块中心：前 BG，后 class_color
    'card_border':   (88, 100),    # 卡边框左上角：前 BG，后 LINE
    'card_inner':    (89, 101),    # 边框内一格：前 BG，后 PANEL
    'below_card':    (112, 410),   # 卡下方：前后都应保持 BG
    'left_of_card':  (80, 110),    # 卡左侧：前后都应保持 BG
}


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def evidence_dir(args):
    if args.dir:
        d = Path(args.dir).resolve()
    else:
        d = (ROOT / 'build/host' / time.strftime('pc_dp_probe_recheck_%Y%m%d_%H%M%S')).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(ev):
    p = ev / 'state.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def save_state(ev, st):
    (ev / 'state.json').write_text(json.dumps(st, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def api(path, data=None, timeout=30):
    req = urllib.request.Request(CONSOLE + path,
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise RuntimeError('%s %s -> HTTP %d %s' % (req.get_method(), path, exc.code, detail))


# ---------- ELF 符号：纯 Python 解析 .symtab，找 g_frame 运行时地址 ----------
def elf_symbol(path, want):
    raw = Path(path).read_bytes()
    if raw[:4] != b'\x7fELF' or raw[4] != 2 or raw[5] != 1:
        raise ValueError('not a little-endian ELF64: %s' % path)
    (e_shoff,) = struct.unpack_from('<Q', raw, 0x28)
    (e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from('<HHH', raw, 0x3A)
    secs = [struct.unpack_from('<IIQQQQIIQQ', raw, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    def name_of(sec):
        off = secs[e_shstrndx][4] + sec[0]
        return raw[off:raw.index(b'\0', off)].decode('utf-8', 'replace')
    for sec in secs:
        if sec[1] != 2:  # SHT_SYMTAB
            continue
        strtab = secs[sec[6]][4]
        count = sec[5] // 24
        for i in range(count):
            st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(
                '<IBBHQQ', raw, sec[4] + i * 24)
            name = raw[strtab + st_name:raw.index(b'\0', strtab + st_name)].decode('utf-8', 'replace')
            if want in name:
                return dict(symbol=name, address=st_value, size=st_size)
    raise ValueError('symbol %r not found in %s' % (want, path))


# ---------- xsdb 单字读取（只读） ----------
def xsdb_read_words(addr_offsets, ev, tag):
    xsdb = next((p for p in XSD_CANDIDATES if p.exists()), None)
    if xsdb is None:
        raise RuntimeError('xsdb.bat not found: %s' % [str(p) for p in XSD_CANDIDATES])
    lines = ['connect', 'targets -set -nocase -filter {name =~"APU*"}']
    for name, (off, _) in addr_offsets.items():
        lines.append('mrd -force 0x%08x 1' % off)
    lines.append('disconnect')
    tcl = ev / ('read_%s.tcl' % tag)
    tcl.write_text('\n'.join(lines) + '\n', encoding='ascii')
    proc = subprocess.run(['cmd', '/c', str(xsdb), str(tcl)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=240)
    out = (proc.stdout or '') + (proc.stderr or '')
    (ev / ('read_%s.log' % tag)).write_text(out, encoding='utf-8')
    words = {}
    lines_out = [l for l in out.splitlines() if re.search(r'0x[0-9a-fA-F]{1,8}\s*$', l)]
    i = 0
    for name in addr_offsets:
        if i >= len(lines_out):
            words[name] = None
            continue
        toks = re.findall(r'0x[0-9a-fA-F]{1,8}', lines_out[i])
        words[name] = int(toks[-1], 16) if toks else None
        i += 1
    return words


# ---------- stage 实现 ----------
def stage_dl(args, ev, st):
    xsdb = next((p for p in XSD_CANDIDATES if p.exists()), None)
    if xsdb is None:
        raise RuntimeError('xsdb.bat not found')
    receipt = ev / 'download.ok'
    receipt.unlink(missing_ok=True)
    env = dict(os.environ)
    env['HSI_DOWNLOAD_RESULT'] = str(receipt)
    vitis = next((p for p in VITIS_DIRS if p.exists()), None)
    if vitis:
        env['HSI_VITIS'] = str(vitis)
    tcl = ROOT / 'tools/launcher/dl_gcs_demo.tcl'
    log('复位并下载 %s（firmware 优先 linked）' % tcl)
    proc = subprocess.run(['cmd', '/c', str(xsdb), str(tcl)], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=420)
    (ev / 'download.log').write_text((proc.stdout or '') + (proc.stderr or ''), encoding='utf-8', errors='replace')
    tail = ((proc.stdout or '') + (proc.stderr or '')).strip().splitlines()[-8:]
    for l in tail:
        log('  dl| ' + l)
    if not receipt.exists():
        raise RuntimeError('未收到下载成功回执（见 download.log）')
    log('下载完成回执 OK')
    st['downloaded'] = True
    save_state(ev, st)


def pick_python():
    for cand in [ROOT / '.venv/Scripts/python.exe', Path('D:/Anaconda/python.exe')]:
        if not cand.exists():
            continue
        probe = subprocess.run([str(cand), '-c', 'import fastapi,uvicorn,websockets,numpy'],
                               capture_output=True, text=True)
        if probe.returncode == 0:
            return str(cand)
    raise RuntimeError('没有找到含 fastapi/uvicorn/websockets/numpy 的 Python（试过 .venv 与 Anaconda）')


def stage_serve(args, ev, st):
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8765)) == 0:
            raise RuntimeError('端口 8765 已被占用：先关闭旧控制台窗口再跑本阶段（避免连到旧身份会话）')
    py = pick_python()
    st['python'] = py
    log('控制台 Python: %s' % py)
    env = dict(os.environ)
    env['GCS_LOCAL_DEMO'] = '1'
    env['GCS_LOCAL_DEMO_BUNDLE'] = str(BUNDLE)
    out = (ev / 'console.out').open('wb')
    flags = 0
    if os.name == 'nt':
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen([py, '-u', str(ROOT / 'tools/gcs_roi.py'), 'serve', '--port', '8765'],
                            cwd=str(ROOT), env=env, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=flags)
    st['console_pid'] = proc.pid
    save_state(ev, st)
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            api('/api/state', timeout=3)
            log('控制台就绪 http://127.0.0.1:8765 (pid=%d)' % proc.pid)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError('控制台 40 秒内未就绪（看 console.out）')


def stage_connect(args, ev, st):
    res = None
    for attempt in range(5):
        res = api('/api/board/connect', dict(confirmed=True, boot_method='jtag'), timeout=60)
        (ev / 'connect.json').write_text(json.dumps(res, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if res.get('ready'):
            break
        log('连接未就绪（第 %d 次）：%s' % (
            attempt + 1, json.dumps(res.get('discovery', res), ensure_ascii=False)[:260]))
        time.sleep(12)
    if not res or not res.get('ready'):
        raise RuntimeError('连接多次未就绪（看 connect.json / console.out）')
    src = res['source']
    log('板卡已连接: boot=%s authorized=%s caps=%s' % (src.get('boot_id'), src.get('authorized'), src.get('capabilities')))
    st['boot_id'] = src.get('boot_id')
    save_state(ev, st)


async def _ws_start_and_wait(rect, timeout):
    import websockets
    rid = None
    async with websockets.connect('ws://127.0.0.1:8765/ws', max_size=2 ** 26) as ws:
        hello = json.loads(await ws.recv())
        src = hello.get('source') or {}
        if not src.get('authorized'):
            raise RuntimeError('板卡未授权，先执行 connect stage')
        cmd = dict(cmd='start', kind='region', scene='longkou', version='v2',
                   rect=[rect[0], rect[1], rect[2], rect[3]], pace_rows=0)
        await ws.send(json.dumps(cmd))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                continue
            ev = json.loads(msg)
            t = ev.get('type')
            if t == 'command_error':
                raise RuntimeError('start 被拒: %s' % json.dumps(ev, ensure_ascii=False)[:400])
            if t in ('run_start', 'run_end', 'run') and ev.get('run'):
                r = ev['run']
                rid = r['id']
                if r['status'] in ('done', 'error', 'stopped', 'cancelled') and t != 'run_start':
                    if r['status'] != 'done':
                        raise RuntimeError('任务未完成: %s' % json.dumps(r, ensure_ascii=False)[:300])
                    return rid, r.get('done'), r.get('total')
        raise RuntimeError('任务超时（%ss）未结束，rid=%s' % (timeout, rid))


def stage_task(args, ev, st):
    rid, done, total = asyncio.run(_ws_start_and_wait([0, 0, 3, 5], 180))
    log('5x3 任务完成 rid=%s done=%s/%s' % (rid, done, total))
    st['rid'] = rid
    save_state(ev, st)


def stage_dump(args, ev, st):
    if 'g_frame' not in st:
        sym = elf_symbol(ELF, 'g_frame')
        st['g_frame'] = sym
        save_state(ev, st)
        log('g_frame: %s @ 0x%08x (%d B)' % (sym['symbol'], sym['address'], sym['size']))
    base = st['g_frame']['address']
    offsets = {name: (base + (y * DISPLAY_W + x) * 4, None) for name, (x, y) in POINTS.items()}
    words = xsdb_read_words(offsets, ev, args.tag)
    res = {name: (None if words[name] is None else '%08x' % words[name]) for name in POINTS}
    (ev / ('fs_%s.json' % args.tag)).write_text(json.dumps(res, indent=2) + '\n', encoding='utf-8')
    for name in POINTS:
        log('  %-14s = %s' % (name, res[name]))


def stage_probe(args, ev, st):
    rid = st.get('rid')
    if not rid:
        raise RuntimeError('先跑 task stage 拿 rid')
    req = dict(row=args.row, col=args.col)
    res = api('/api/run/%d/board/probe' % rid, req)
    log('探查已提交: %s' % json.dumps(res, ensure_ascii=False)[:200])
    deadline = time.time() + 90
    while time.time() < deadline:
        snap = api('/api/run/%d/board' % rid)
        p = ((snap.get('interaction') or {}).get('probe')) or None
        if p and p.get('state') in ('done', 'error'):
            (ev / 'probe.json').write_text(json.dumps(p, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if p['state'] != 'done':
                raise RuntimeError('探查失败: %s' % p.get('error'))
            st['probe_class'] = p.get('class_id')
            save_state(ev, st)
            log('探查完成: class=%s word=%s conf=%.4f attention=%s' % (
                p.get('class_id'), p.get('class_word'),
                (p.get('confidence_q16') or 0) / 65536.0, p.get('attention_crc32')))
            return
        time.sleep(0.5)
    raise RuntimeError('探查 90 秒未完成')


def stage_log(args, ev, st):
    rid = st.get('rid')
    deadline = time.time() + 60
    while time.time() < deadline:
        snap = api('/api/run/%d/board' % rid)
        bl = snap.get('board_log') or {}
        if bl.get('state') == 'ready' and bl.get('evidence'):
            txt = (Path(bl['evidence']) / 'board_log.txt')
            if txt.exists():
                text = txt.read_text(encoding='utf-8', errors='replace')
                lines = [l for l in text.splitlines() if 'S2C PROBE' in l]
                (ev / 'board_log_probe.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
                log('板端记录 S2C PROBE 行: %s' % (lines[-1] if lines else '(无)'))
                return
        elif bl.get('state') == 'error':
            raise RuntimeError('板端记录回读失败: %s' % bl.get('error'))
        time.sleep(1)
    raise RuntimeError('板端记录 60 秒未就绪')


def stage_check(args, ev, st):
    before = json.loads((ev / 'fs_before.json').read_text())
    after = json.loads((ev / 'fs_after.json').read_text())
    probe = json.loads((ev / 'probe.json').read_text())
    cls = probe.get('class_id')
    expect_swatch = rgba(*COLORS[cls]) if isinstance(cls, int) and cls < len(COLORS) else None
    checks = {
        'swatch_changed': before['swatch_center'] != after['swatch_center'],
        'swatch_class_color': after['swatch_center'] == '%08x' % expect_swatch,
        'border_line': after['card_border'] == '%08x' % LINE and before['card_border'] == '%08x' % BG,
        'inner_panel': after['card_inner'] == '%08x' % PANEL and before['card_inner'] == '%08x' % BG,
        'outside_untouched': after['below_card'] == before['below_card'] == '%08x' % BG
                             and after['left_of_card'] == before['left_of_card'] == '%08x' % BG,
        'pc_result_present': probe.get('state') == 'done' and probe.get('class_word'),
    }
    ok = all(checks.values())
    summary = dict(result='PASS' if ok else 'FAIL', checks=checks, before=before, after=after,
                   probe=dict(class_id=cls, class_word=probe.get('class_word'),
                              confidence=round((probe.get('confidence_q16') or 0) / 65536.0, 4),
                              attention_crc32=probe.get('attention_crc32')),
                   scope='PC UI 单点探查 -> DP 探针卡像素复核（真板，非整景/全功能验收）')
    (ev / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    log(json.dumps(checks, ensure_ascii=False))
    log('结论: %s（证据 %s）' % (summary['result'], ev))
    if not ok:
        raise SystemExit(2)


STAGES = dict(dl=stage_dl, serve=stage_serve, connect=stage_connect, task=stage_task,
              dump=stage_dump, probe=stage_probe, log=stage_log, check=stage_check)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=['all', *STAGES])
    ap.add_argument('--dir', help='证据目录（续跑时传入同一个）')
    ap.add_argument('--tag', default='before', help='dump stage 的标签')
    ap.add_argument('--row', type=int, default=1)
    ap.add_argument('--col', type=int, default=1)
    args = ap.parse_args()
    ev = evidence_dir(args)
    st = load_state(ev)
    log('证据目录: %s' % ev)
    seq = ['dl', 'serve', 'connect', 'task']
    if args.stage == 'all':
        for name in seq:
            log('=== stage %s ===' % name)
            STAGES[name](args, ev, st)
        args.tag = 'before'
        log('=== stage dump(before) ===')
        stage_dump(args, ev, st)
        log('=== stage probe ===')
        stage_probe(args, ev, st)
        args.tag = 'after'
        log('=== stage dump(after) ===')
        stage_dump(args, ev, st)
        log('=== stage log ===')
        stage_log(args, ev, st)
        log('=== stage check ===')
        stage_check(args, ev, st)
    else:
        log('=== stage %s ===' % args.stage)
        STAGES[args.stage](args, ev, st)
    return 0


if __name__ == '__main__':
    sys.exit(main())
