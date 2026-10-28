"""闭环模拟（PLAN §17 B4，§15.2 第 4～6 步）：制造可复现的误分 → 标注 → 微调 → 验证 → 出权重包。

故事：新地块种了训练集没见过的作物。旧模型（官方 Train100 去掉该类训练）在这块地上必然误分；
农艺师核查后标注真实类别（标注点取自该类在官方 Train100 里的像素，不碰 Test100）；PC 用旧权重 + 基础训练集 + 标注点微调，
Test100 只评一次，导出新权重包。真值只用于评测与画对比图，不进入业务判断。

两步：
  make-old  D:/pytorch/python.exe model/finetune_region.py make-old --scene longkou --hold-class 3
            → data/ckpt/<scene>_<model>_s<seed>_hold<c>.pth、data/closed_loop/<scene>/region.json（自动选该类最密的 64×64 窗）
  finetune  D:/pytorch/python.exe model/finetune_region.py finetune --scene longkou --hold-class 3 --annotate 30
            → data/ckpt/<scene>_<model>_s<seed>_hold<c>_ft<n>.pth、data/scenes/<scene>/weights/<ver>/、
              data/closed_loop/<scene>/{pred_old,pred_new,gt}_region.bin、report/closed_loop_pc.md 追加一行
微调默认全参数、Adam 2e-4、30 轮、验证集与旧模型相同再加标注类的 val（来自 Train100 该类，与标注点不重叠）。
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
import scenes
import tt_model
from train_scene import Windows, split_train_val, predict, metrics

ROOT = scenes.ROOT
REGION = 64


def load_scene(args):
    spec = scenes.SCENES[args.scene]
    cube, gtp = scenes.raw_paths(args.scene)
    scene = preprocess.Scene(cube, gtp, spec['band_drop'])
    train_p, test_p = scenes.split_paths(args.scene, args.per_class)
    train_mask = preprocess.load_mat(train_p).astype(np.int64)
    test_mask = preprocess.load_mat(test_p).astype(np.int64)
    ncls = len(spec['classes'])
    assert train_mask.max() == ncls and 1 <= args.hold_class <= ncls
    return spec, scene, train_mask, test_mask, train_p, test_p, ncls


def pick_region(gt, cls, size=REGION, stride=4):
    """该类像素最多的 size×size 窗（积分图）。"""
    H, W = gt.shape
    integ = np.zeros((H + 1, W + 1), np.int64)
    integ[1:, 1:] = np.cumsum(np.cumsum(gt == cls, 0), 1)
    best = (-1, 0, 0)
    for r in range(0, H - size + 1, stride):
        for c in range(0, W - size + 1, stride):
            n = integ[r + size, c + size] - integ[r, c + size] - integ[r + size, c] + integ[r, c]
            if n > best[0]:
                best = (int(n), r, c)
    return best


def train(model, win, tr_c, tr_y, va_c, va_y, epochs, lr, batch, device, ckpt, log):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    best, best_ep, n, t0 = -1.0, -1, len(tr_c), time.time()
    tr_y = torch.from_numpy(tr_y).to(device)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, batch):
            idx = perm[i:i + batch].numpy()
            loss = F.cross_entropy(model(win.batch(tr_c[idx], device)), tr_y[idx])
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(idx)
        sched.step()
        if ep % 5 == 4 or ep == epochs - 1:
            va_oa = float(np.mean(predict(model, win, va_c, device) == va_y))
            if va_oa > best:
                best, best_ep = va_oa, ep
                torch.save(model.state_dict(), ckpt)
            log(f'ep {ep + 1:4d} loss {tot / n:.4f} val_oa {va_oa:.4f} best {best:.4f}@{best_ep + 1} {time.time() - t0:.0f}s')
    model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True))
    return best, best_ep + 1


def region_coords(r0, c0):
    return np.array([(r, c) for r in range(r0, r0 + REGION) for c in range(c0, c0 + REGION)])


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cmd_make_old(args):
    spec, scene, train_mask, test_mask, train_p, test_p, ncls = load_scene(args)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    hold = args.hold_class
    held_mask = train_mask.copy(); held_mask[held_mask == hold] = 0        # 旧模型完全没见过 hold 类
    tr_c, va_c = split_train_val(np.where(held_mask > 0, train_mask, 0), args.val_per_class, args.seed)
    tr_y = train_mask[tr_c[:, 0], tr_c[:, 1]] - 1
    va_y = train_mask[va_c[:, 0], va_c[:, 1]]
    win = Windows(scene.padded)
    model = tt_model.MODELS[args.model](ncls).to(device)
    for name, p in model.named_parameters():
        if p.dim() == 2 and 'classifier' not in name:
            nn.init.trunc_normal_(p, std=0.05)
    nn.init.trunc_normal_(model.encoder.cls_token, std=0.02)
    nn.init.trunc_normal_(model.encoder.pos_embed, std=0.02)
    tag = f'{args.scene}_{args.model}_s{args.seed}_hold{hold}'
    ckdir = ROOT / 'data' / 'ckpt'; ckdir.mkdir(parents=True, exist_ok=True)
    ckpt = ckdir / f'{tag}.pth'
    t0 = time.time()
    best, best_ep = train(model, win, tr_c, tr_y, va_c, va_y, args.epochs, args.lr, args.batch, device, ckpt, print)

    test_c = np.argwhere(test_mask > 0)
    test_y = test_mask[test_c[:, 0], test_c[:, 1]]
    m = metrics(predict(model, win, test_c, device), test_y, ncls)
    n_in, r0, c0 = pick_region(scene.gt, hold)
    out = ROOT / 'data' / 'closed_loop' / args.scene; out.mkdir(parents=True, exist_ok=True)
    rc = region_coords(r0, c0)
    pred_old = predict(model, win, rc, device).reshape(REGION, REGION).astype(np.uint8)
    gt_reg = scene.gt[r0:r0 + REGION, c0:c0 + REGION].astype(np.uint8)
    pred_old.tofile(out / 'pred_old_region.bin'); gt_reg.tofile(out / 'gt_region.bin')
    lab = gt_reg > 0
    info = dict(scene=args.scene, model=args.model, seed=args.seed, hold_class=hold, hold_name=spec['classes'][hold - 1],
                official_train=train_p.name, official_test=test_p.name, region=dict(row0=r0, col0=c0, size=REGION, hold_pixels=n_in),
                old_ckpt=str(ckpt), old_ckpt_sha256=sha(ckpt), old_train=len(tr_c), old_val=len(va_c), old_best_val=best, old_best_epoch=best_ep,
                old_test=dict(OA=m['OA'], AA=m['AA'], Kappa=m['Kappa'], per_class=m['per_class']),
                old_region_oa=float(np.mean(pred_old[lab] == gt_reg[lab])),
                old_region_hold_recall=float(np.mean(pred_old[gt_reg == hold] == hold)),
                old_region_pred_hist=np.bincount(pred_old.ravel(), minlength=ncls + 1).tolist(),
                seconds=int(time.time() - t0))
    (out / 'region.json').write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(info, indent=1, ensure_ascii=False))


def cmd_finetune(args):
    spec, scene, train_mask, test_mask, train_p, test_p, ncls = load_scene(args)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    hold = args.hold_class
    out = ROOT / 'data' / 'closed_loop' / args.scene
    info = json.loads((out / 'region.json').read_text(encoding='utf-8'))
    assert info['hold_class'] == hold and info['seed'] == args.seed
    r0, c0 = info['region']['row0'], info['region']['col0']
    t_start = time.time()

    # 标注点：hold 类在官方 Train100 里的像素，先取区域内的，不够再按到区域中心的距离补；剩下的作该类验证
    pts = np.argwhere(train_mask == hold)
    center = np.array([r0 + REGION / 2, c0 + REGION / 2])
    inside = (pts[:, 0] >= r0) & (pts[:, 0] < r0 + REGION) & (pts[:, 1] >= c0) & (pts[:, 1] < c0 + REGION)
    order = np.lexsort((np.linalg.norm(pts - center, axis=1), ~inside))
    pts = pts[order]
    ann = pts[:args.annotate]
    hold_val = pts[args.annotate:args.annotate + args.val_per_class]
    if args.run_tag:         # 地面站现场微调：产物进 runs/<tag>/，不覆盖已验证的版本，不追加报告
        out = out / 'runs' / args.run_tag
        out.mkdir(parents=True, exist_ok=True)
    (out / f'annotations_{args.annotate}.json').write_text(json.dumps(dict(
        scene=args.scene, hold_class=hold, source=train_p.name, inside_region=int(inside[order][:args.annotate].sum()),
        points=ann.tolist()), indent=1), encoding='utf-8')

    held_mask = train_mask.copy(); held_mask[held_mask == hold] = 0
    tr_c, va_c = split_train_val(np.where(held_mask > 0, train_mask, 0), args.val_per_class, args.seed)   # 与 make-old 同一划分
    tr_c = np.concatenate([tr_c, ann]); va_c = np.concatenate([va_c, hold_val])
    tr_y = train_mask[tr_c[:, 0], tr_c[:, 1]] - 1
    va_y = train_mask[va_c[:, 0], va_c[:, 1]]
    win = Windows(scene.padded)
    model = tt_model.MODELS[args.model](ncls).to(device)
    model.load_state_dict(torch.load(info['old_ckpt'], map_location=device, weights_only=True), strict=True)
    tag = f'{args.scene}_{args.model}_s{args.seed}_hold{hold}_ft{args.annotate}' + (f'_{args.run_tag}' if args.run_tag else '')
    ckpt = ROOT / 'data' / 'ckpt' / f'{tag}.pth'
    log_lines = []
    def log(s):
        print(s, flush=True); log_lines.append(s)
    best, best_ep = train(model, win, tr_c, tr_y, va_c, va_y, args.epochs, args.lr, args.batch, device, ckpt, log)
    t_train = time.time() - t_start

    test_c = np.argwhere(test_mask > 0)
    test_y = test_mask[test_c[:, 0], test_c[:, 1]]
    m = metrics(predict(model, win, test_c, device), test_y, ncls)
    rc = region_coords(r0, c0)
    pred_new = predict(model, win, rc, device).reshape(REGION, REGION).astype(np.uint8)
    pred_new.tofile(out / f'pred_new_region_ft{args.annotate}.bin')
    base = ROOT / 'data' / 'closed_loop' / args.scene
    pred_old = np.fromfile(base / 'pred_old_region.bin', np.uint8).reshape(REGION, REGION)
    gt_reg = np.fromfile(base / 'gt_region.bin', np.uint8).reshape(REGION, REGION)
    lab = gt_reg > 0

    # Export both existing-contract packages, with checkpoint/SHA provenance.
    # A successful training run alone is neither a deployable package nor a
    # board result. The export never modifies an existing immutable tag.
    from export_board_candidate import export_candidate
    board_candidate=export_candidate(args.scene,ckpt,args.weights_version)
    wdir = ROOT / 'data' / 'scenes' / args.scene / 'weights' / args.weights_version
    t_total = time.time() - t_start

    res = dict(tag=tag, new_ckpt=str(ckpt), new_ckpt_sha256=sha(ckpt), annotate=len(ann), train=len(tr_c), val=len(va_c),
               epochs=args.epochs, lr=args.lr, best_val=best, best_epoch=best_ep,
               new_test=dict(OA=m['OA'], AA=m['AA'], Kappa=m['Kappa'], per_class=m['per_class']),
               old_test=info['old_test'],
               region=dict(old_oa=info['old_region_oa'], new_oa=float(np.mean(pred_new[lab] == gt_reg[lab])),
                           old_hold_recall=info['old_region_hold_recall'], new_hold_recall=float(np.mean(pred_new[gt_reg == hold] == hold)),
                           changed_pixels=int(np.sum(pred_new != pred_old)), agree_old_new=float(np.mean(pred_new == pred_old))),
               weights=dict(version=args.weights_version, dir=str(wdir), weights_all_sha256=sha(wdir / 'weights_all.bin'),
                            board_candidate=board_candidate),
               seconds_train=int(t_train), seconds_total=int(t_total), log=log_lines)
    (out / f'finetune_{args.annotate}.json').write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding='utf-8')
    if args.run_tag:
        res.pop('log')
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return

    rep = ROOT / 'report' / 'closed_loop_pc.md'
    if not rep.exists():
        rep.write_text('# 闭环模拟（PC）：旧权重误分 → 标注 → 微调 → 验证 → 权重包\n\n'
                       '由 model/finetune_region.py 追加，勿手改。旧模型 = 官方 Train 去掉 hold 类训练；标注点来自该类的官方 Train 像素，不碰 Test；'
                       'Test 只评一次。区域 OA 与召回用真值算，仅作评测。时间为 PC（GPU）从加载数据到权重包落盘。\n\n'
                       '| 日期 | 景 | hold 类 | 标注点 | 微调轮 | Test OA 旧→新 | Test AA 旧→新 | 区域 OA 旧→新 | 区域 hold 召回 旧→新 | 区域变化像素 | 用时 s | 新 ckpt sha256[:12] | 权重版本 |\n'
                       '|---|---|---|---|---|---|---|---|---|---|---|---|---|\n', encoding='utf-8')
    with rep.open('a', encoding='utf-8') as f:
        o, n_, rg = info['old_test'], res['new_test'], res['region']
        f.write(f"| {time.strftime('%Y-%m-%d')} | {args.scene} | {hold} {info['hold_name']} | {len(ann)} | {args.epochs} | "
                f"{o['OA']:.4f}→{n_['OA']:.4f} | {o['AA']:.4f}→{n_['AA']:.4f} | {rg['old_oa']:.4f}→{rg['new_oa']:.4f} | "
                f"{rg['old_hold_recall']:.4f}→{rg['new_hold_recall']:.4f} | {rg['changed_pixels']} | {res['seconds_total']} | "
                f"{res['new_ckpt_sha256'][:12]} | {args.weights_version} |\n")
    res.pop('log')
    print(json.dumps(res, indent=1, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['make-old', 'finetune'])
    ap.add_argument('--scene', required=True, choices=list(scenes.SCENES))
    ap.add_argument('--model', default='unoverlapping')
    ap.add_argument('--hold-class', type=int, required=True, help='旧模型没见过的类（1 起）')
    ap.add_argument('--per-class', type=int, default=100)
    ap.add_argument('--val-per-class', type=int, default=10)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--epochs', type=int)
    ap.add_argument('--lr', type=float)
    ap.add_argument('--annotate', type=int, default=30, help='finetune：标注点数')
    ap.add_argument('--weights-version', default='v3', help='finetune：权重包版本目录')
    ap.add_argument('--run-tag', default='', help='finetune：地面站现场微调标签，产物进 data/closed_loop/<景>/runs/<标签>/，不追加报告')
    args = ap.parse_args()
    if args.cmd == 'make-old':
        args.epochs = args.epochs or 100; args.lr = args.lr or 1e-3
        cmd_make_old(args)
    else:
        args.epochs = args.epochs or 30; args.lr = args.lr or 2e-4
        cmd_finetune(args)


if __name__ == '__main__':
    main()
