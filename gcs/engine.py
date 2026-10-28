"""地面站的 PC 推理核心：景数据、权重版本、GPU 取窗与前向（浮点参考，不是板上定点路径）。

数据来自 model/export_scene.py 的 data/scenes/<景>/：cube_f32.bin 已做高斯 + 全景归一化 + 3 像素零边，
与板上同一份立方体；patch 级无偏归一化在 GPU 上做，与 train_scene.Windows 同式。
"""
import json
import sys
import threading
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import preprocess  # noqa: E402
import scenes      # noqa: E402
import tt_model    # noqa: E402

DATA = ROOT / 'data' / 'scenes'
CKPT = ROOT / 'data' / 'ckpt'
LOOP = ROOT / 'data' / 'closed_loop'
WIN, PAD = 7, 3

# 采集信息取自官方 data/raw/WHU-Hi/README.docx（Zhong et al.）
MISSION = {
    'longkou': dict(site='湖北 龙口镇', date='2018-07-17 13:49–14:37', platform='DJI Matrice 600 Pro',
                    sensor='Headwall Nano-Hyperspec 8 mm', altitude_m=500, gsd_m=0.463, weather='晴 36°C'),
    'honghu': dict(site='湖北 洪湖市', date='2017-11-20 16:23–17:37', platform='DJI Matrice 600 Pro',
                   sensor='Headwall Nano-Hyperspec 17 mm', altitude_m=100, gsd_m=0.043, weather='多云 8°C'),
    'hanchuan': dict(site='湖北 汉川市', date='2016-06-17 17:57–18:46', platform='Leica Aibot X6 V1',
                     sensor='Headwall Nano-Hyperspec 17 mm', altitude_m=250, gsd_m=0.109, weather='晴 30°C'),
}

# 权重版本：id → checkpoint 与板上权重包目录（None = 只有 PC checkpoint，没有导出权重包）
VERSIONS = {
    'longkou': [
        dict(id='v2', label='v2 自训 s0', ckpt=CKPT / 'longkou_unoverlapping_s0.pth', pkg='v2'),
        dict(id='v1', label='v1 上游权重', ckpt=Path(scenes.UPSTREAM) / 'TensorTransformerHSI_unoverlapping_LK.pth', pkg='v1_board'),
        dict(id='hold3', label='闭环前（训练未含芝麻）', ckpt=CKPT / 'longkou_unoverlapping_s0_hold3.pth', pkg='hold3'),
        dict(id='v3', label='v3 闭环 30 点微调', ckpt=CKPT / 'longkou_unoverlapping_s0_hold3_ft30.pth', pkg='v3_board'),
        dict(id='v3_ft50', label='v3_ft50 闭环 50 点', ckpt=CKPT / 'longkou_unoverlapping_s0_hold3_ft50.pth', pkg='v3ft50_board'),
    ],
    'honghu': [dict(id='v1', label='v1 自训 s0', ckpt=CKPT / 'honghu_unoverlapping_s0.pth', pkg='v1')],
    'hanchuan': [dict(id='v1', label='v1 自训 s0', ckpt=CKPT / 'hanchuan_unoverlapping_s0.pth', pkg='v1')],
}
PKG_FILES = ('weights_all.bin', 'cls_token.bin', 'pos_embed.bin', 'classifier_w.bin', 'classifier_b.bin')


def discover_board_exports():
    """Restore explicitly exported model versions from verified local manifests.

    No checkpoint is loaded, inferred or trained. Unavailable files remain
    unavailable through the catalog, never a fallback to a different model.
    """
    import board_models
    errors=[]
    for scene in VERSIONS:
        registered={v.get('pkg') for v in VERSIONS[scene]}
        for manifest in sorted((DATA/scene/'weights').glob('*/board_model.json')):
            tag=manifest.parent.name
            if tag.startswith('.') or tag in registered:continue
            try:
                board_models.load_candidate(DATA,scene,tag)
                meta=json.loads(manifest.read_text(encoding='utf-8'))
                if not meta.get('checkpoint'):raise ValueError('Missing checkpoint provenance path')
                if any(v['id']==tag for v in VERSIONS[scene]):raise ValueError('Export tag conflicts with a version ID')
                VERSIONS[scene].append(dict(id=tag,label=f'本地板端候选 {tag}',ckpt=Path(meta['checkpoint']),pkg=tag));registered.add(tag)
            except (ValueError,OSError,KeyError,TypeError) as exc:errors.append(dict(scene=scene,tag=tag,error=str(exc)))
    return errors


def read_meta(scene):
    kv = {}
    for line in (DATA / scene / 'meta.txt').read_text(encoding='utf-8').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            kv[k] = v
    return kv


def version(scene, vid):
    for v in VERSIONS[scene]:
        if v['id'] == vid:
            return v
    raise KeyError(f'{scene}: no version {vid}')


def package_bytes(scene, vid):
    """权重包（板上下发的五个文件）拼接后的字节；没有包返回 None。"""
    v = version(scene, vid)
    if not v['pkg']:
        return None
    d = DATA / scene / 'weights' / v['pkg']
    return b''.join((d / f).read_bytes() for f in PKG_FILES)


class Scene:
    """一景的立方体（GPU 上）、真值、官方划分、训练样本光谱库。"""

    def __init__(self, name, device):
        meta = read_meta(name)
        self.name = name
        self.H, self.W, self.B = int(meta['H']), int(meta['W']), int(meta['bands'])
        spec = scenes.SCENES[name]
        self.classes = spec['classes']
        self.palette = scenes.PALETTE[:len(self.classes) + 1]
        cube = np.fromfile(DATA / name / 'cube_f32.bin', dtype='<f4').reshape(self.H + 2 * PAD, self.W + 2 * PAD, self.B)
        self.cube = torch.from_numpy(cube).to(device)
        self.gt = np.fromfile(DATA / name / 'gt_u8.bin', dtype=np.uint8).reshape(self.H, self.W)
        tr, te = scenes.split_paths(name, 100)
        self.train_mask = preprocess.load_mat(tr).astype(np.uint8)
        self.test_mask = preprocess.load_mat(te).astype(np.uint8)
        # 光谱库：官方 Train100 每类均值（只用训练样本，不碰测试集）
        centre = cube[PAD:PAD + self.H, PAD:PAD + self.W]
        self.library = [centre[self.train_mask == c].mean(0).tolist() if (self.train_mask == c).any() else None
                        for c in range(1, len(self.classes) + 1)]
        nb = spec['bands']
        self.wavelengths = [round(400 + 600 * i / (nb - 1), 1) for i in range(self.B)]   # 400～1000 nm 等间隔（近似）
        # 三维立方体视图的显示量化：整景（不含零边）1%～99% 分位映射到 0～255，各面与切片共用
        g = torch.Generator(device=device).manual_seed(0)
        flat = self.cube[PAD:PAD + self.H, PAD:PAD + self.W].reshape(-1)
        smp = flat[torch.randint(0, flat.numel(), (1 << 20,), device=device, generator=g)]
        self.vis_lo, self.vis_hi = (float(v) for v in torch.quantile(smp, torch.tensor([0.01, 0.99], device=device)))

    def info(self):
        return dict(name=self.name, H=self.H, W=self.W, bands=self.B, classes=self.classes, palette=self.palette,
                    mission=MISSION[self.name], wavelengths=self.wavelengths,
                    versions=[dict(id=v['id'], label=v['label'], pkg=v['pkg']) for v in VERSIONS[self.name]],
                    test_pixels=int((self.test_mask > 0).sum()), train_pixels=int((self.train_mask > 0).sum()))

    def windows(self, coords):
        """coords: (B,2) int64 tensor（未填充坐标）→ (B,270,7,7)，patch 级无偏归一化。"""
        ar = torch.arange(WIN, device=coords.device)
        rows = (coords[:, 0:1] + ar)[:, :, None]          # 填充图里 (r..r+6)
        cols = (coords[:, 1:2] + ar)[:, None, :]
        p = self.cube[rows, cols].permute(0, 3, 1, 2).contiguous()   # (B,7,7,270) → (B,270,7,7)
        flat = p.reshape(p.shape[0], -1)
        mean = flat.mean(1, keepdim=True)
        std = flat.std(1, unbiased=True, keepdim=True)
        return ((flat - mean) / std).reshape(p.shape)

    def clip_rect(self, r0, c0, h, w):
        r0, c0 = max(0, min(r0, self.H - 1)), max(0, min(c0, self.W - 1))
        h = self.H - r0 if h <= 0 else min(h, self.H - r0)
        w = self.W - c0 if w <= 0 else min(w, self.W - c0)
        return r0, c0, h, w

    def _u8(self, t):
        t = (t - self.vis_lo) * (255 / (self.vis_hi - self.vis_lo))
        return t.clamp(0, 255).round().to(torch.uint8).cpu().numpy()

    def cube_edges(self, r0, c0, h, w):
        """区域四条边的全部波段（显示量化）：前 (B,w) 末行 | 后 (B,w) 首行 | 左 (B,h) 首列 | 右 (B,h) 末列。"""
        c = self.cube[PAD + r0:PAD + r0 + h, PAD + c0:PAD + c0 + w]
        return b''.join(self._u8(f.T).tobytes() for f in (c[-1], c[0], c[:, 0], c[:, -1]))

    def band_image(self, b, r0, c0, h, w):
        """区域第 b 波段 (h,w)（显示量化）。"""
        return self._u8(self.cube[PAD + r0:PAD + r0 + h, PAD + c0:PAD + c0 + w, b]).tobytes()


def forward_trace(model, x):
    """与 tt_model 前向同式，另外记录 12 层注意力矩阵 (L,N,N)。x: (1,270,7,7)。"""
    enc = model.encoder
    t = model.tokens(x)
    t = torch.cat((enc.cls_token.expand(t.shape[0], -1, -1, -1, -1), t), dim=-1) + enc.pos_embed
    attns = []
    for layer in enc.encoders:
        B, N = t.shape[0], layer.channels + 1
        D = layer.dims * layer.win_size * layer.win_size
        xn = tt_model.transformer_normalize(t)
        q = layer.project(xn, 'query').reshape(B, D, N)
        k = layer.project(xn, 'key').reshape(B, D, N)
        v = layer.project(xn, 'value').reshape(B, N, D)
        a = torch.softmax(q.transpose(-1, -2) @ k, dim=-1)
        attns.append(a[0])
        ctx = (a @ v).reshape(xn.shape)
        t = tt_model.transformer_normalize(xn + ctx)
        t = t + layer.project(t, 'mlp')
    logits = model.classifier(torch.flatten(t[..., 1], start_dim=1))
    return logits, torch.stack(attns)


class Engine:
    """景与模型缓存。GPU 只放当前景；模型按 (景, 版本) 缓存。"""

    def __init__(self):
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device_name = torch.cuda.get_device_name(0) if self.device == 'cuda' else 'CPU'
        self.lock = threading.Lock()
        self.scene = None
        self.models = {}
        self.extra_versions = {}        # 现场微调产生的新版本

    def get_scene(self, name):
        with self.lock:
            if self.scene is None or self.scene.name != name:
                self.scene = None
                if self.device == 'cuda':
                    torch.cuda.empty_cache()
                self.scene = Scene(name, self.device)
            return self.scene

    def get_model(self, scene, vid):
        key = (scene, vid)
        with self.lock:
            if key not in self.models:
                v = version(scene, vid)
                ncls = len(scenes.SCENES[scene]['classes'])
                m = tt_model.load('unoverlapping', ckpt=v['ckpt'], classes=ncls).to(self.device)
                self.models[key] = m
            return self.models[key]

    @torch.no_grad()
    def infer(self, scene, vid, coords):
        """coords: (B,2) numpy int → (label 1 起 uint8, 置信度 float32, logits float32)。"""
        sc, m = self.get_scene(scene), self.get_model(scene, vid)
        c = torch.from_numpy(np.ascontiguousarray(coords, dtype=np.int64)).to(self.device)
        logits = m(sc.windows(c))
        prob = torch.softmax(logits, 1)
        conf, lab = prob.max(1)
        if self.device == 'cuda':
            torch.cuda.synchronize()
        return (lab + 1).to(torch.uint8).cpu().numpy(), conf.cpu().numpy(), logits.cpu().numpy()

    @torch.no_grad()
    def probe(self, scene, vid, r, c):
        sc, m = self.get_scene(scene), self.get_model(scene, vid)
        x = sc.windows(torch.tensor([[r, c]], device=self.device))
        logits, attn = forward_trace(m, x)
        prob = torch.softmax(logits, 1)[0]
        spec = sc.cube[r + PAD, c + PAD].cpu().numpy()
        # 7×7 邻域各像素自身的分类（出界为 0），不依赖是否扫描过
        nb = [(r + dr, c + dc) for dr in range(-PAD, PAD + 1) for dc in range(-PAD, PAD + 1)]
        ok = [0 <= rr < sc.H and 0 <= cc < sc.W for rr, cc in nb]
        nbr = np.zeros(len(nb), np.uint8)
        nbr[ok] = self.infer(scene, vid, np.array([p for p, k in zip(nb, ok) if k]))[0]
        return dict(row=r, col=c, logits=logits[0].cpu().tolist(), prob=prob.cpu().tolist(), nbr=nbr.tolist(),
                    label=int(prob.argmax()) + 1, conf=float(prob.max()), attn=attn.cpu().numpy().round(4).tolist(),
                    spectrum=spec.round(4).tolist(), gt=int(sc.gt[r, c]),
                    split='train' if sc.train_mask[r, c] else ('test' if sc.test_mask[r, c] else ''))


def closed_loop_info(scene):
    d = LOOP / scene
    if not (d / 'region.json').exists():
        return None
    region = json.loads((d / 'region.json').read_text(encoding='utf-8'))
    out = dict(region=region)
    for n in (30, 50):
        f, a = d / f'finetune_{n}.json', d / f'annotations_{n}.json'
        if f.exists():
            r = json.loads(f.read_text(encoding='utf-8'))
            r.pop('log', None)
            out[f'ft{n}'] = r
        if a.exists():
            out[f'ann{n}'] = json.loads(a.read_text(encoding='utf-8'))
    return out
