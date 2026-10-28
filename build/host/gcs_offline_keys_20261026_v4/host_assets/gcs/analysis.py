"""地面站分析（PLAN §15.1）：待核查斑块、补采样建议、评测指标、版本对比。

业务口径：只用分类图与置信度；真值只进"评测"与"对比"，不进斑块与统计。
"""
import numpy as np
from scipy import ndimage

EIGHT = np.ones((3, 3), bool)


def _components(mask):
    """连通区（8 邻接）：逐个给 (切片, 局部掩膜)，切片外扩 1 像素便于取周边。"""
    lab, n = ndimage.label(mask, EIGHT)
    H, W = mask.shape
    for k, sl in enumerate(ndimage.find_objects(lab)):
        r0, r1 = max(sl[0].start - 1, 0), min(sl[0].stop + 1, H)
        c0, c1 = max(sl[1].start - 1, 0), min(sl[1].stop + 1, W)
        box = (slice(r0, r1), slice(c0, c1))
        yield box, lab[box] == k + 1


def patches(pred, conf, done, gsd, conf_thr=0.6, min_px=6, frag_px=12, limit=60):
    """两类待核查：低置信连通区（面积 ≥ min_px）；孤立碎斑（某类 3～frag_px 像素的连通区，周边九成以上是别的类）。"""
    out = []
    for box, mk in _components(done & (conf < conf_thr)):
        if mk.sum() >= min_px:
            out.append(_patch('低置信', box, mk, pred, conf, gsd))
    for c in np.unique(pred[done]):
        if c == 0:
            continue
        for box, mk in _components(done & (pred == c)):
            a = mk.sum()
            if not 3 <= a <= frag_px:
                continue
            ring = ndimage.binary_dilation(mk, EIGHT) & ~mk & done[box]
            if ring.sum() >= 3 and (pred[box][ring] != c).mean() > 0.9:
                out.append(_patch('孤立碎斑', box, mk, pred, conf, gsd))
    out.sort(key=lambda p: (p['kind'] != '低置信', -p['area_px']))
    return out[:limit]


def _patch(kind, box, mk, pred, conf, gsd):
    rr, cc = np.nonzero(mk)
    rr, cc = rr + box[0].start, cc + box[1].start
    n = int(mk.sum())
    return dict(kind=kind, area_px=n, area_m2=round(n * gsd * gsd, 1),
                row=int(round(rr.mean())), col=int(round(cc.mean())),
                bbox=[int(rr.min()), int(cc.min()), int(rr.max()), int(cc.max())],
                cls=int(np.bincount(pred[box][mk]).argmax()), mean_conf=round(float(conf[box][mk].mean()), 3))


def sampling(conf, done, k=5, win=15):
    """补采样建议：置信度均值最低的 k 个不重叠 win×win 窗中心（只看已处理像素，窗内八成以上已处理）。"""
    if done.sum() == 0:
        return []
    s = ndimage.uniform_filter(np.where(done, conf, 0).astype(np.float64), win, mode='constant')
    n = ndimage.uniform_filter(done.astype(np.float64), win, mode='constant')
    score = np.where(n > 0.8, s / np.maximum(n, 1e-9), np.inf)
    out = []
    for _ in range(k):
        i = np.argmin(score)
        if not np.isfinite(score.flat[i]):
            break
        r, c = np.unravel_index(i, score.shape)
        out.append(dict(row=int(r), col=int(c), mean_conf=round(float(score[r, c]), 3)))
        score[max(0, r - win):r + win + 1, max(0, c - win):c + win + 1] = np.inf
    return out


def metrics(pred, done, test_mask, ncls):
    """官方 Test100 像素里已处理的部分：OA / AA / Kappa / 混淆矩阵。"""
    m = done & (test_mask > 0)
    n = int(m.sum())
    if n == 0:
        return None
    gt, pr = test_mask[m].astype(np.int64) - 1, pred[m].astype(np.int64) - 1
    cm = np.zeros((ncls, ncls), np.int64)
    np.add.at(cm, (gt, pr), 1)
    oa = np.trace(cm) / n
    per = np.diag(cm) / np.maximum(cm.sum(1), 1)
    present = cm.sum(1) > 0
    pe = (cm.sum(0) * cm.sum(1)).sum() / n ** 2
    return dict(n=n, OA=float(oa), AA=float(per[present].mean()), Kappa=float((oa - pe) / (1 - pe)) if pe < 1 else 1.0,
                per_class=[round(float(x), 4) if p else None for x, p in zip(per, present)], cm=cm.tolist())


def compare(a, b, gt):
    """两次运行的公共已处理像素：变化像素数、各自在有真值像素上的精度（真值只作评测）。"""
    both = a.done & b.done
    n = int(both.sum())
    if n == 0:
        return None
    ch = both & (a.pred != b.pred)
    lab = both & (gt > 0)
    acc = lambda p: float((p[lab] == gt[lab]).mean()) if lab.any() else None   # noqa: E731
    return dict(common=n, changed=int(ch.sum()), agree=float(1 - ch.sum() / n), acc_a=acc(a.pred), acc_b=acc(b.pred),
                labeled=int(lab.sum()))
