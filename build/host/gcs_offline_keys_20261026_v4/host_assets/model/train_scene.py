"""按景训练 Tensor Transformer（PLAN §17 B2），用 WHU-Hi 官方固定划分。

划分：官方 Train<per_class>.mat 里每类 per_class 个像素，其中每类固定抽 val_per_class 个做验证选 checkpoint，其余训练；
      官方 Test<per_class>.mat 只在最后评一次，训练与选模全程不碰。划分坐标写 data/splits/<scene>_train<per_class>_seed<seed>.json（入库）。
预处理与部署一致（preprocess.Scene：高斯 + 全景归一化 + 零边，patch 级无偏归一化）；HanChuan 去末 4 波段。
上游仓库没有训练脚本，超参取 config.py 的 batch 128 / 500 epoch，优化器与初始化自定（Adam + 余弦，因子 trunc_normal 0.05；
上游 checkpoint 的因子 std 约 0.06～0.08，不是单位阵）。模型类与 tt_model.py 相同，state_dict 可直接 strict 载入。

用法：D:/pytorch/python.exe model/train_scene.py --scene honghu [--per-class 100] [--epochs 500] [--seed 0]
      D:/pytorch/python.exe model/train_scene.py --scene longkou --eval-only --ckpt <pth>   # 只评测
      D:/pytorch/python.exe model/train_scene.py --scene longkou --qat --epochs 50 --lr 1e-4     # int8 QAT（B5），评测见 qat_eval.py
输出：data/ckpt/<scene>_<model>_s<seed>.pth、同名 _metrics.json；report/accuracy_pc.md 追加一行。
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess
import qat
import scenes
import tt_model

ROOT = scenes.ROOT
WIN = preprocess.WIN


class Windows:
    """整景 7×7 窗视图：[i, j] → (270,7,7)，与 preprocess.patch_tensor 同内存序；归一化在 torch 里做。"""

    def __init__(self, padded):
        self.view = np.lib.stride_tricks.sliding_window_view(padded.astype(np.float32), (WIN, WIN), axis=(0, 1))

    def batch(self, coords, device):
        p = torch.from_numpy(np.ascontiguousarray(self.view[coords[:, 0], coords[:, 1]])).to(device)   # (B,270,7,7)
        flat = p.reshape(p.shape[0], -1)
        mean = flat.mean(1, keepdim=True)
        std = flat.std(1, unbiased=True, keepdim=True)
        return ((flat - mean) / std).reshape(p.shape)


def split_train_val(train_mask, val_per_class, seed):
    rng = np.random.default_rng(seed)
    tr, va = [], []
    for c in range(1, int(train_mask.max()) + 1):
        pts = np.argwhere(train_mask == c)
        rng.shuffle(pts)
        va.append(pts[:val_per_class]); tr.append(pts[val_per_class:])
    return np.concatenate(tr), np.concatenate(va)


@torch.no_grad()
def predict(model, win, coords, device, bs=1024):
    model.eval()
    out = []
    for i in range(0, len(coords), bs):
        out.append(model(win.batch(coords[i:i + bs], device)).argmax(1).cpu().numpy())
    return np.concatenate(out) + 1


def metrics(pred, gt, ncls):
    cm = np.zeros((ncls, ncls), np.int64)
    np.add.at(cm, (gt - 1, pred - 1), 1)
    oa = np.trace(cm) / cm.sum()
    per = np.diag(cm) / np.maximum(cm.sum(1), 1)
    pe = (cm.sum(0) * cm.sum(1)).sum() / cm.sum() ** 2
    return dict(OA=float(oa), AA=float(per.mean()), Kappa=float((oa - pe) / (1 - pe)), per_class=per.round(4).tolist())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', required=True, choices=list(scenes.SCENES))
    ap.add_argument('--model', default='unoverlapping', choices=list(tt_model.MODELS))
    ap.add_argument('--per-class', type=int, default=100)
    ap.add_argument('--val-per-class', type=int, default=10)
    ap.add_argument('--epochs', type=int, default=500)
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--eval-only', action='store_true')
    ap.add_argument('--ckpt', help='eval-only 时评测的 checkpoint')
    ap.add_argument('--qat', action='store_true', help='int8 QAT（qat.py），从 --init-ckpt 续训，存 <scene>_qat8_s<seed>.pth')
    ap.add_argument('--init-ckpt', help='QAT 起点，默认 data/ckpt/<scene>_<model>_s<seed>.pth')
    args = ap.parse_args()
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    spec = scenes.SCENES[args.scene]
    ncls = len(spec['classes'])
    cube, gtp = scenes.raw_paths(args.scene)
    scene = preprocess.Scene(cube, gtp, spec['band_drop'])
    train_p, test_p = scenes.split_paths(args.scene, args.per_class)
    train_mask = preprocess.load_mat(train_p).astype(np.int64)
    test_mask = preprocess.load_mat(test_p).astype(np.int64)
    assert train_mask.max() == ncls and np.array_equal(train_mask[train_mask > 0], scene.gt[train_mask > 0])
    assert not np.any((train_mask > 0) & (test_mask > 0))
    win = Windows(scene.padded)
    test_c = np.argwhere(test_mask > 0)
    test_y = test_mask[test_c[:, 0], test_c[:, 1]]

    ckdir = ROOT / 'data' / 'ckpt'; ckdir.mkdir(parents=True, exist_ok=True)
    tag = f'{args.scene}_{args.model}_s{args.seed}'
    model = tt_model.MODELS[args.model](ncls).to(device)
    if args.qat:
        init = Path(args.init_ckpt) if args.init_ckpt else ckdir / f'{tag}.pth'
        tag = f'{args.scene}_qat8_s{args.seed}'
        if not args.eval_only:
            model.load_state_dict(torch.load(init, map_location=device, weights_only=True), strict=True)
        qat.enable(model)
    t0 = time.time()
    if args.eval_only:
        ckpt = Path(args.ckpt)
        model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True), strict=True)
        split_note = 'eval only'
    else:
        tr_c, va_c = split_train_val(train_mask, args.val_per_class, args.seed)
        tr_y = torch.from_numpy(train_mask[tr_c[:, 0], tr_c[:, 1]] - 1).to(device)
        va_y = train_mask[va_c[:, 0], va_c[:, 1]]
        (ROOT / 'data' / 'splits').mkdir(parents=True, exist_ok=True)
        split_file = ROOT / 'data' / 'splits' / f'{args.scene}_train{args.per_class}_seed{args.seed}.json'
        split_file.write_text(json.dumps(dict(scene=args.scene, official_train=train_p.name, official_test=test_p.name,
                                              val_per_class=args.val_per_class, seed=args.seed,
                                              train=tr_c.tolist(), val=va_c.tolist())), encoding='utf-8')
        if not args.qat:
            for name, p in model.named_parameters():
                if p.dim() == 2 and 'classifier' not in name:
                    nn.init.trunc_normal_(p, std=0.05)
            nn.init.trunc_normal_(model.encoder.cls_token, std=0.02)     # 上游同值；全零 token 归一化会 0/0
            nn.init.trunc_normal_(model.encoder.pos_embed, std=0.02)
        opt = torch.optim.Adam(model.parameters(), lr=args.lr)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
        ckpt = ckdir / f'{tag}.pth'
        best, best_ep = -1.0, -1
        n = len(tr_c)
        for ep in range(args.epochs):
            model.train()
            perm = torch.randperm(n)
            tot = 0.0
            for i in range(0, n, args.batch):
                idx = perm[i:i + args.batch].numpy()
                x = win.batch(tr_c[idx], device)
                loss = F.cross_entropy(model(x), tr_y[idx])
                opt.zero_grad(); loss.backward(); opt.step()
                tot += loss.item() * len(idx)
            sched.step()
            if ep % 5 == 4 or ep == args.epochs - 1:
                va_oa = float(np.mean(predict(model, win, va_c, device) == va_y))
                if va_oa > best:
                    best, best_ep = va_oa, ep
                    torch.save(model.state_dict(), ckpt)
                print(f'ep {ep + 1:4d} loss {tot / n:.4f} val_oa {va_oa:.4f} best {best:.4f}@{best_ep + 1} {time.time() - t0:.0f}s', flush=True)
        model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True))
        split_note = f'train {len(tr_c)} / val {len(va_c)} (seed {args.seed}), best val OA {best:.4f} at epoch {best_ep + 1}'
        if args.qat:
            split_note += f', QAT int8 from {init.name}, lr {args.lr:g}, fake-quant eval'

    pred = predict(model, win, test_c, device)
    m = metrics(pred, test_y, ncls)
    m.update(scene=args.scene, model=args.model, classes=ncls, per_class=args.per_class, test_pixels=int(len(test_c)),
             official_test=test_p.name, split=split_note, epochs=None if args.eval_only else args.epochs,
             ckpt=str(ckpt), ckpt_sha256=hashlib.sha256(ckpt.read_bytes()).hexdigest(), seconds=int(time.time() - t0))
    (ckdir / f'{tag}_metrics.json' if not args.eval_only else ckdir / f'{tag}_evalonly_metrics.json').write_text(json.dumps(m, indent=1), encoding='utf-8')
    rep = ROOT / 'report' / 'accuracy_pc.md'
    if not rep.exists():
        rep.write_text('# PC 浮点精度（官方 WHU-Hi 固定划分，Test 只评一次）\n\n由 model/train_scene.py 追加，勿手改。\n\n'
                       '| 日期 | 景 | 模型 | 类别 | 测试像素 | OA | AA | Kappa | 划分 | ckpt sha256[:12] |\n|---|---|---|---|---|---|---|---|---|---|\n', encoding='utf-8')
    with rep.open('a', encoding='utf-8') as f:
        f.write(f"| {time.strftime('%Y-%m-%d')} | {args.scene} | {args.model}{' qat8' if args.qat else ''} | {ncls} | {len(test_c)} | {m['OA']:.4f} | {m['AA']:.4f} | "
                f"{m['Kappa']:.4f} | {split_note} | {m['ckpt_sha256'][:12]} |\n")
    print(json.dumps(m, indent=1))


if __name__ == '__main__':
    main()
