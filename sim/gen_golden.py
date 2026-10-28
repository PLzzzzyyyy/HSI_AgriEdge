"""一键生成 sim/golden/：整网引擎（D 阶段）逐层对拍的黄金向量（PLAN §17 B3）。

数值路径 = 板上路径：tt_net.cpp float32 胶水 + tt_hw_sim.cpp 整数投影（同 HLS tucker_proj v1.4），层间 int16 Q3.12。
  sim/golden/n6_real/    LongKou 黄金像素（model/data/golden/patch_f32.bin），真实权重
  sim/golden/n10_synth/  合成 token（同 test_block_pipeline.cpp），验证 N=10 调度；权重仍是 12 层真实权重
每套：x_embed、每层 stats/q/k/v/attn/x_mid/stats/mlp/x_out、logits，文件清单见 sim/host/dump_golden.cpp。
交叉核对：n6_real 的每层 x_out 与 model/fixed_point_sim.py 的 double 定点路径比较（预期 1e-4 量级缓慢累积），
logits 与 model/data/golden/logits_fixed.bin 比较（阈值 TT_LOGIT_TOL=1e-2），结果写进 sim/golden/README_generated.md。

用法：D:/pytorch/python.exe sim/gen_golden.py [--compiler D:/mingw64/bin/g++.exe]
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'sim' / 'golden'
sys.path.insert(0, str(ROOT / 'model'))


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'{cmd}\n{r.stdout}\n{r.stderr}')
    return r.stdout


def cross_check(d):
    from fixed_point_sim import Net
    from quant import Fmt
    net = Net('unoverlapping', Fmt(DF=12, WF=14, MF=14))
    patch = np.fromfile(d / 'patch_f32.bin', dtype='<f4').reshape(270, 7, 7).astype(np.float64)
    trace = []
    lf = net.forward(patch, fixed=True, trace=trace)
    N = net.N
    rows = []
    for l, t in enumerate(trace):
        x = np.fromfile(d / f'L{l}_x_out_i16.bin', dtype='<i2').reshape(-1, N).T / 4096.0   # [p*N+n] -> (n,p)
        ref = t['x'].reshape(N, -1)
        rows.append((l, float(np.abs(x - ref).max()), float(np.abs(ref).max())))
    logits = np.fromfile(d / 'logits_f32.bin', dtype='<f4')
    ref_logits = np.fromfile(ROOT / 'model' / 'data' / 'golden' / 'logits_fixed.bin', dtype='<f8')
    dl = float(np.abs(logits - ref_logits).max())
    assert np.array_equal(lf, ref_logits), 'model/data/golden/logits_fixed.bin is stale'
    return rows, dl, int(logits.argmax()), int(ref_logits.argmax())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--compiler', default='D:/mingw64/bin/g++.exe')
    args = ap.parse_args()
    exe = ROOT / 'build' / 'host' / 'dump_golden.exe'
    exe.parent.mkdir(parents=True, exist_ok=True)
    srcs = [ROOT / 'sim/host/dump_golden.cpp', ROOT / 'src/ps/tt_net.cpp', ROOT / 'src/ps/tt_hw_sim.cpp']
    run([args.compiler, '-O2', '-std=c++11', '-ffp-contract=off', *srcs, '-o', exe])
    sets = {'n6_real': (6, ROOT / 'model/data/golden/patch_f32.bin'), 'n10_synth': (10, 'synthetic')}
    log = []
    for name, (N, src) in sets.items():
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob('*.bin'):
            old.unlink()
        log.append(run([exe, ROOT, d, N, src]).strip())
    rows, dl, am, ref_am = cross_check(OUT / 'n6_real')
    ok = am == ref_am and dl < 1e-2
    lines = ['# sim/golden 生成记录（由 sim/gen_golden.py 写，勿手改）', '',
             '数值路径：tt_net.cpp float32 + tt_hw_sim.cpp 整数投影，层间 int16 Q3.12（与板上相同）。主机 x86，`-ffp-contract=off`。', '',
             *log, '',
             '## n6_real 与 PC double 定点仿真（fixed_point_sim.py）的逐层差', '',
             '| 层 | max abs x_out - ref | max abs ref |', '|---|---|---|',
             *[f'| {l} | {e:.3e} | {m:.2f} |' for l, e, m in rows], '',
             f'logits vs model/data/golden/logits_fixed.bin: max abs dlogit = {dl:.3e}, argmax {am} vs {ref_am} -> {"PASS" if ok else "FAIL"}', '',
             '## 文件 sha256', '']
    head = len(lines)
    for d in sorted(OUT.iterdir()):
        if d.is_dir():
            for f in sorted(d.glob('*')):
                lines.append(f'- {d.name}/{f.name} {f.stat().st_size} {hashlib.sha256(f.read_bytes()).hexdigest()[:16]}')
    (OUT / 'README_generated.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:head]))
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
