"""Exactly the saved S1b 5x3 ROI: unchanged PS C++ + two entry-A references.

Default/--verify only hashes evidence (no builds, recompute, board or App/BSP).
--compute requires a NEW output directory. Never reads old golden pixels.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from types import SimpleNamespace
import zlib

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'report/system_s1b/20261009_numeric_r2'
BOARD = ROOT / 'report/system_s1b/20261009_app_board_r1'
SOURCES = ('sim/host/s1b_numeric_reference.cpp', 'sim/host/engine_ref.cpp',
           'src/ps/tt_net.cpp', 'src/ps/tt_net.h', 'src/ps/tt_hw.h',
           'src/ps/system/m3a_roi.cpp', 'src/hls/tt_engine_regs.h',
           'model/engine_ref.py', 'model/quant.py', 'tools/check_s1b_numeric_reference.py')
PROFILE = {'cube_f32.bin': (243794880, 'BF3B60C5'),
           'weights/v2/cls_token.bin': (10584, 'C85F498E'),
           'weights/v2/pos_embed.bin': (63504, 'F5113FAE'),
           'weights/v2/weights_engine.bin': (480576, '27231983')}


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def digest(path):
    h, crc, n = hashlib.sha256(), 0, 0
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
            crc = zlib.crc32(b, crc)
            n += len(b)
    return dict(bytes=n, sha256=h.hexdigest(), crc32=f'{crc:08X}')


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def verify(out):
    checks = json.loads((out / 'checksums.json').read_text(encoding='utf-8'))
    for name, expected in checks.items():
        require(digest(out / name) == expected, f'evidence changed: {name}')
    receipt = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    for name, expected in receipt['inputs'].items():
        require(digest(ROOT / name) == expected, f'input changed: {name}')
    require(receipt['status'] in ('PASS', 'NUMERIC_MISMATCH'), 'incomplete computation')
    print(f"VERIFY_PASS saved_status={receipt['status']} evidence={len(checks)} inputs={len(receipt['inputs'])}; no recompute")


def ps_patch(np, raw):
    """Exact eight-lane/tail float32 order, not np.std or torch preprocessing."""
    p = raw.transpose(2, 0, 1).copy().reshape(-1)
    def total(v, squared=False):
        a, b = np.zeros(4, np.float32), np.zeros(4, np.float32)
        end = len(v) // 8 * 8
        for j in range(0, end, 8):
            u, w = v[j:j+4], v[j+4:j+8]
            a = a + (u * u if squared else u)
            b = b + (w * w if squared else w)
        lane = a + b
        s = (lane[0] + lane[1]) + (lane[2] + lane[3])
        for u in v[end:]:
            s = s + (u * u if squared else u)
        return s
    mean = total(p) / np.float32(13230)
    d = p - mean
    inv = np.float32(1) / np.sqrt(total(d, True) / np.float32(13229))
    return d * inv, mean, inv


def python_engine(np, er, package):
    # Same verified SD package, not a re-exported checkpoint. No Net constructor.
    e = er.Engine.__new__(er.Engine)
    e.cfg, e.ncls = er.Cfg(16), 9
    e.hw = (np.ndarray((9, 2646), '<i2', package, 63744, (5312, 2)).astype(np.int64),
            np.frombuffer(package, 'i1', 9, 32).astype(np.int64),
            np.frombuffer(package, '<i4', 9, 63616).astype(np.int64))
    factors = np.frombuffer(package, '<i2', 12 * 4 * 3014, 191232).reshape(12, 4, 3014)
    e.wp = [[(q[:49].reshape(7, 7).astype(np.int64),
              q[49:98].reshape(7, 7).astype(np.int64),
              q[98:].reshape(54, 54).astype(np.int64), (14, 14, 14))
             for q in layer] for layer in factors]
    return e


def compute(out, cxx, objdump, finish_existing=False):
    if finish_existing:
        prefix = json.loads((out / 'cpp_completed_prefix.json').read_text(encoding='utf-8'))
        for name, expected in prefix['inputs'].items():
            require(digest(ROOT / name) == expected, f'completed C++ input changed: {name}')
        for name, expected in prefix['files'].items():
            require(digest(out / name) == expected, f'completed C++ file changed: {name}')
        require('REFERENCE_15_DONE' in (out / 'cpp_reference.txt').read_text(), 'C++ incomplete')
    else:
        require(not out.exists(), 'refuse to overwrite completed evidence; use --verify')
        out.mkdir(parents=True)
    receipt = dict(status='RUNNING', started=datetime.now().astimezone().isoformat(),
                   scope='15 original ROI pixels only; offline reference, no board replay',
                   base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                   inputs={}, commands=[], reused_commands=[], finish_existing=finish_existing)
    write_json(out / 'result.json', receipt)
    scene = ROOT / 'data/scenes/longkou'
    for rel, (size, crc) in PROFILE.items():
        p = scene / rel
        d = digest(p)
        require((d['bytes'], d['crc32']) == (size, crc), f'profile mismatch: {rel}')
        receipt['inputs'][p.relative_to(ROOT).as_posix()] = d
    for rel in SOURCES:
        receipt['inputs'][rel] = digest(ROOT / rel)
    audit = json.loads((BOARD / 'audit.json').read_text(encoding='utf-8'))
    for item in audit['imported_sources']:
        p = ROOT / 'vitis/s1b_roi_app/src' / item['name']
        require(digest(p)['sha256'] == item['sha256'], f'App source drift: {p}')
        receipt['inputs'][p.relative_to(ROOT).as_posix()] = digest(p)
    for rel in ('src/ps/tt_net.cpp', 'src/ps/tt_net.h', 'src/ps/tt_hw.h',
                'src/ps/system/m3a_roi.cpp', 'src/hls/tt_engine_regs.h'):
        require(digest(ROOT / rel) == digest(ROOT / 'vitis/s1b_roi_app/src' / Path(rel).name),
                f'PS source differs from built App: {rel}')
    for rel in ('report/system_s1b/20261009_app_board_r1/audit.json',
                'report/system_s1b/20261009_app_board_r1/uart_attempt_03_user.txt',
                'vitis/s1b_roi_app/Debug/src/tt_net.o', 'vitis/s1b_roi_app/Debug/s1b_roi_app.elf',
                'build/vivado/tt_m3a_zu5ev.xsa'):
        receipt['inputs'][rel] = digest(ROOT / rel)
    require(receipt['inputs']['build/vivado/tt_m3a_zu5ev.xsa']['sha256'] ==
            '9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652', 'frozen XSA drift')
    require(receipt['inputs']['vitis/s1b_roi_app/Debug/s1b_roi_app.elf']['sha256'] ==
            '2f899ec02cc4263dd54c91720fb0e128a05cfca25044535ad4e405165fada489', 'built ELF drift')
    def command(name, args):
        if finish_existing:
            require((out / name).is_file(), f'missing completed C++ artifact: {name}')
            receipt['reused_commands'].append([str(v) for v in args])
            return (out / name).read_text(encoding='utf-8', errors='replace')
        receipt['commands'].append([str(v) for v in args])
        write_json(out / 'result.json', receipt)
        p = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / name).write_bytes(p.stdout)
        require(p.returncode == 0, f'{name}: exit {p.returncode}')
        return p.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n')
    asm = command('a53_tt_net_disassembly.txt', [objdump, '-d', '-C',
                  str(ROOT / 'vitis/s1b_roi_app/Debug/src/tt_net.o')])
    for name in ('tt_patch_extract', 'tt_embed'):
        match = re.search(r'^[0-9a-f]+ <' + name + r'\([^\n]*\)>:\n(.*?)(?=\nDisassembly|\n[0-9a-f]+ <|\Z)', asm, re.M | re.S)
        require(match is not None, f'missing A53 function: {name}')
        require(not re.search(r'\b(?:fmla|fmadd|fmls|fmsub)\b', match.group(1)), f'fused operation in {name}')
    receipt['a53_no_fma_in_patch_embed'] = True
    command('compiler_version.txt', [cxx, '--version'])
    build = ROOT / 'build/host' / ('s1b_numeric_' + out.name)
    if not finish_existing:
        require(not build.exists(), 'refuse existing offline build directory')
        build.mkdir(parents=True)
    exe = build / 'reference.exe'
    command('compile.txt', [cxx, '-std=c++14', '-O2', '-ffp-contract=off',
                          '-ffunction-sections', '-fdata-sections', '-Wall', '-Wextra',
                          str(ROOT / SOURCES[0]), str(ROOT / 'src/ps/tt_net.cpp'),
                          '-Wl,--gc-sections', '-o', str(exe)])
    receipt['offline_executable'] = dict(path=exe.relative_to(ROOT).as_posix(), **digest(exe))
    text = command('cpp_reference.txt', [str(exe), str(scene), str(out)])
    require('REFERENCE_15_DONE' in text, 'incomplete C++ reference')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / 'model'))
    import numpy as np
    import engine_ref as er
    receipt['environment'] = dict(python=sys.version, numpy=np.__version__, platform=sys.platform)
    package = (scene / 'weights/v2/weights_engine.bin').read_bytes()
    require(struct.unpack_from('<4I', package) == (0x32455454, 2, 9, 16), 'weight header v2 (not return contract v3)')
    header = (ROOT / 'src/hls/tt_engine_regs.h').read_text(encoding='utf-8')
    for name, value in [('HBIAS', 63616), ('HW', 63744), ('HW_ROW', 5312), ('PROJ', 191232)]:
        require(re.search(r'#define TT_ENGINE_WPKG_' + name + r'\s+' + str(value) + r'\b', header), name)
    engine = python_engine(np, er, package)
    cube = np.memmap(scene / 'cube_f32.bin', dtype='<f4', mode='r', shape=(556, 406, 270))
    cls = np.fromfile(scene / 'weights/v2/cls_token.bin', '<f4')
    pos = np.fromfile(scene / 'weights/v2/pos_embed.bin', '<f4').reshape(2646, 6)
    patches = np.fromfile(out / 'patches_f32.bin', '<f4').reshape(15, 13230)
    inputs = np.fromfile(out / 'inputs_q312_stride31808.bin', '<i2').reshape(15, 15904)
    logits = np.fromfile(out / 'logits_q16_i32.bin', '<i4').reshape(15, 32)
    words = np.fromfile(out / 'class_u32.bin', '<u4')
    require(np.all(inputs[:, 15876:] == 0), 'input stride padding')
    uart = (BOARD / 'uart_attempt_03_user.txt').read_text(encoding='utf-8')
    require('completed=15 halted=0' in uart and 'S1B rc=0 sd_loaded=1' in uart, 'UART success prefix')
    board = [(int(x), int(y), int(w, 16)) for x, y, w in re.findall(
        r'^ROI x=(\d+) y=(\d+) class_word=([0-9A-Fa-f]{8})$', uart, re.M)]
    require([(x, y) for x, y, _ in board] == [(i % 5, i // 5) for i in range(15)], 'exact 5x3 UART coordinates')
    rows = []
    for i, (x, y, board_word) in enumerate(board):
        patch, mean, inv = ps_patch(np, cube[y:y+7, x:x+7, :])
        require(patch.tobytes() == patches[i].tobytes(), f'PS float32 patch mismatch at {x},{y}')
        q, saturated = er.ps_embed_q312(SimpleNamespace(cls=cls, pos=pos), patch)
        require(np.array_equal(q.reshape(-1), inputs[i, :15876]), f'PS Q3.12 mismatch at {x},{y}')
        result = engine.forward(engine.entry_a(q))
        pw = (result['conf'] << 16) | result['label']
        require(np.array_equal(result['logits'], logits[i, :9]) and np.all(logits[i, 9:] == 0),
                f'C++/Python logits mismatch at {x},{y}')
        require(pw == int(words[i]), f'C++/Python packed word mismatch at {x},{y}')
        rows.append(dict(x=x, y=y, board_word=f'{board_word:08X}', reference_word=f'{pw:08X}',
                         match=board_word == pw, label=pw & 255, confidence_q016=pw >> 16,
                         ps_saturated_elements=saturated, patch_mean=float(mean), patch_inv_std=float(inv),
                         input_sha256=hashlib.sha256(inputs[i].tobytes()).hexdigest()))
        print(f'COMPARE ({x},{y}) board={board_word:08X} ref={pw:08X} match={board_word == pw}', flush=True)
    receipt.update(status='PASS' if all(r['match'] for r in rows) else 'NUMERIC_MISMATCH',
                   finished=datetime.now().astimezone().isoformat(), pixels=15,
                   board_exact_matches=sum(r['match'] for r in rows),
                   cpp_python_patch_elements=15*13230, cpp_python_input_elements=15*15876,
                   cpp_python_logit_elements=15*9, rows=rows)
    write_json(out / 'result.json', receipt)
    write_json(out / 'checksums.json', {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    print(f"{receipt['status']} exact CLASS words {receipt['board_exact_matches']}/15; offline only")
    if receipt['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--compute', action='store_true')
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--finish-existing', action='store_true', help='resume Python only from hashed completed C++ prefix')
    ap.add_argument('--out', type=Path, default=DEFAULT)
    ap.add_argument('--cxx', default='D:/mingw64/bin/g++.exe')
    ap.add_argument('--objdump', default='D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin/aarch64-none-elf-objdump.exe')
    args = ap.parse_args()
    if args.compute or args.finish_existing:
        compute(args.out.resolve(), args.cxx, args.objdump, args.finish_existing)
    else:
        verify(args.out.resolve())
