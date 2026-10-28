"""三景注册表：原始文件、checkpoint、类别名、调色板、假彩色波段。export_scene.py 与地面站共用。

原始数据放 data/raw/<scene>/（不入库），LongKou 找不到时回退到 D:/FPGaLearn 的旧位置。
HongHu、HanChuan 的类别名取自 WHU-Hi 数据集论文（Zhong et al. 2020），导出时会用真值最大值核对类别数。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
CKPT = ROOT / 'data' / 'ckpt'
UPSTREAM = 'D:/FPGAlearn/Tensor-Transformer-for-HSIC-master/Tensor-Transformer-for-HSIC-master'

# 22 类以内够用的调色板（0 = 无标签 黑）
PALETTE = ['#000000', '#ff0000', '#ee9a00', '#ffff00', '#00ff00', '#00ffcf', '#00a0ff', '#0000ff',
           '#b000ff', '#ffb6c1', '#8b4513', '#7fff00', '#ff1493', '#40e0d0', '#ffd700', '#adff2f',
           '#dc143c', '#00ced1', '#9370db', '#f0e68c', '#ff7f50', '#2e8b57', '#c0c0c0']

SCENES = {
    'longkou': dict(
        cube='WHU_Hi_LongKou.mat', gt='WHU_Hi_LongKou_gt.mat', dirname='LongKou',
        fallback_dir='D:/FPGAlearn/RemoteSensing_LK_data',
        # v1 = 上游权重（黄金向量、csim、主机回归都基于它）；自训 s0 权重导成 v2（export_scene.py --ckpt --weights-version v2）
        ckpt={'unoverlapping': f'{UPSTREAM}/TensorTransformerHSI_unoverlapping_LK.pth',
              'overlapping': f'{UPSTREAM}/TensorTransformerHSI_overlapping_LK.pth',
              'unoverlapping_s0': CKPT / 'longkou_unoverlapping_s0.pth'},
        bands=270, band_drop=(), rgb_bands=(112, 67, 31),
        classes=['Corn', 'Cotton', 'Sesame', 'Broad-leaf soybean', 'Narrow-leaf soybean',
                 'Rice', 'Water', 'Roads and houses', 'Mixed weed'],
    ),
    'honghu': dict(
        cube='WHU_Hi_HongHu.mat', gt='WHU_Hi_HongHu_gt.mat', dirname='HongHu', fallback_dir=None,
        ckpt={'unoverlapping': CKPT / 'honghu_unoverlapping_s0.pth'},     # train_scene.py --scene honghu --seed 0
        bands=270, band_drop=(), rgb_bands=(112, 67, 31),
        classes=['Red roof', 'Road', 'Bare soil', 'Cotton', 'Cotton firewood', 'Rape', 'Chinese cabbage',
                 'Pakchoi', 'Cabbage', 'Tuber mustard', 'Brassica parachinensis', 'Brassica chinensis',
                 'Small Brassica chinensis', 'Lactuca sativa', 'Celtuce', 'Film covered lettuce',
                 'Romaine lettuce', 'Carrot', 'White radish', 'Garlic sprout', 'Broad bean', 'Tree'],
    ),
    'hanchuan': dict(
        cube='WHU_Hi_HanChuan.mat', gt='WHU_Hi_HanChuan_gt.mat', dirname='HanChuan', fallback_dir=None,
        ckpt={'unoverlapping': CKPT / 'hanchuan_unoverlapping_s0.pth'},   # train_scene.py --scene hanchuan --seed 0
        bands=274, band_drop=(270, 271, 272, 273), rgb_bands=(112, 67, 31),   # 去掉末 4 波段凑 270，B2 训练时同步
        classes=['Strawberry', 'Cowpea', 'Soybean', 'Sorghum', 'Water spinach', 'Watermelon', 'Greens',
                 'Trees', 'Grass', 'Red roof', 'Gray roof', 'Plastic', 'Bare soil', 'Road',
                 'Bright object', 'Water'],
    ),
}


def official_dir(name):
    """官方整包位置：data/raw/WHU-Hi 优先，仓库根 WHU-Hi 兜底（09-22 目录被占用没搬成）。"""
    sub = Path('Matlab_data_format') / f'WHU-Hi-{SCENES[name]["dirname"]}'
    for base in (RAW / 'WHU-Hi', ROOT / 'WHU-Hi'):
        if (base / sub).exists():
            return base / sub
    return RAW / 'WHU-Hi' / sub


def raw_paths(name):
    """查找顺序：data/raw/<scene>/ → 官方整包 → 旧位置。"""
    s = SCENES[name]
    for d in (RAW / name, official_dir(name), s['fallback_dir']):
        if d and (Path(d) / s['cube']).exists():
            return Path(d) / s['cube'], Path(d) / s['gt']
    raise FileNotFoundError(f'{name}: put {s["cube"]} and {s["gt"]} in {RAW / name}')


def split_paths(name, per_class):
    """官方固定划分（每类 per_class 个训练像素，25/50/100/150/200/250/300）：返回 (Train.mat, Test.mat)。
    .mat 里的变量名带景前缀（LKtrain100 / HHCYtrain100 / Train100），用 preprocess.load_mat 取第一个变量即可。"""
    d = official_dir(name) / 'Training samples and test samples'
    return d / f'Train{per_class}.mat', d / f'Test{per_class}.mat'
