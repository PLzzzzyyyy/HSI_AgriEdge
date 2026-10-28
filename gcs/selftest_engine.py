"""engine.py 自检：GPU 取窗与 train_scene.Windows 逐位一致、标签一致，并测整景吞吐。"""
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402
from train_scene import Windows  # noqa: E402  (engine 已把 model/ 加进 sys.path)


def main():
    eng = engine.Engine()
    sc = eng.get_scene('longkou')
    rng = np.random.default_rng(0)
    coords = np.stack([rng.integers(0, sc.H, 512), rng.integers(0, sc.W, 512)], 1)
    padded = sc.cube.cpu().numpy()
    ref = Windows(padded).batch(coords, eng.device)
    got = sc.windows(torch.from_numpy(coords).to(eng.device))
    d = float((ref - got).abs().max())
    print('window max|diff|', d)
    assert d == 0.0
    m = eng.get_model('longkou', 'v2')
    with torch.no_grad():
        lab_ref = m(ref).argmax(1).cpu().numpy() + 1
    lab, conf, _ = eng.infer('longkou', 'v2', coords)
    assert (lab == lab_ref).all()
    print('labels match', len(coords))
    p = eng.probe('longkou', 'v2', int(coords[0, 0]), int(coords[0, 1]))
    assert p['label'] == lab[0] and abs(p['conf'] - conf[0]) < 1e-5, (p['label'], lab[0], p['conf'], conf[0])
    print('probe matches, attn', np.array(p['attn']).shape)

    allc = np.array([(r, c) for r in range(sc.H) for c in range(sc.W)])
    for bs in (1024, 2048, 4096):
        t0 = time.time()
        n = 0
        for i in range(0, 40 * sc.W, bs):
            eng.infer('longkou', 'v2', allc[i:i + bs]); n += len(allc[i:i + bs])
        dt = time.time() - t0
        print(f'bs {bs}: {n / dt:.0f} px/s ({1000 * dt / n:.4f} ms/px)')


if __name__ == '__main__':
    main()
