"""复刻上游 img_predict.py + utils.pyc 的预处理（utils.py 源码缺失，按字节码反汇编还原）。

流程（gaussian_filtering_enable=True，padding_mode=0，win=7）：
  1. image_Gaussian_conv：每个波段 scipy.signal.convolve2d(band, K, mode='same')，零边界
       K = [[.05,.1,.05],[.1,.4,.1],[.05,.1,.05]]
  2. mean = np.mean(np.mean(x,0),0)   逐波段均值 (270,)
     std  = np.std(np.std(x,0),0)     ★ 不是逐波段标准差，是"每列标准差"再对列取标准差；照抄
     x = (x-mean)/std
  3. utils.normalize(x)：x 是 numpy → (x - x.mean()) / x.std()，全局、ddof=0
  4. 四周零填充 3 像素
  5. 取 7×7×270 patch（以像素为中心）→ float32 → torchvision ToTensor → (270,7,7)   ★ 变成 CHW
  6. utils.normalize(patch)：patch 是 torch → (p - p.mean()) / p.std()，全局、无偏 ddof=1
  7. 送模型：模型内部 reshape(-1,7,7,54,5) 作用在 (270,7,7) 的内存序上

第 5 步的 CHW 转置意味着模型看到的 (i1,i2,j,n) 与真实 (行,列,波段) 的关系是：
  e = c*49 + h*7 + w ；i1 = e//1890, i2 = (e//270)%7, j = (e//5)%54, n = e%5   （(7,7,54,5) 的步长 1890/270/5/1）
权重就是这么训的，板上 PS 也必须按这个顺序排 patch。
"""
import numpy as np
import scipy.io as sio
from scipy import signal

DATA = 'D:/FPGAlearn/RemoteSensing_LK_data/WHU_Hi_LongKou.mat'
GT = 'D:/FPGAlearn/RemoteSensing_LK_data/WHU_Hi_LongKou_gt.mat'
WIN, HALF = 7, 3
KERNEL = np.array([[0.05, 0.1, 0.05], [0.1, 0.4, 0.1], [0.05, 0.1, 0.05]])


def load_mat(path):
    d = sio.loadmat(path)
    return next(v for k, v in d.items() if not k.startswith('__'))


def preprocess_image(img):
    """img: (H,W,270) float32 → 填充后的 (H+6, W+6, 270) float32。"""
    res = np.zeros_like(img)
    for c in range(img.shape[2]):
        res[:, :, c] = signal.convolve2d(img[:, :, c], KERNEL, mode='same')
    mean = np.mean(np.mean(res, axis=0), axis=0)
    std = np.std(np.std(res, axis=0), axis=0)
    res = (res - mean) / std                                # 升为 float64（numpy 广播规则）
    res = (res - res.mean()) / res.std()                    # ddof=0
    return np.pad(res, ((HALF, HALF), (HALF, HALF), (0, 0)), 'constant', constant_values=0)


def patch_tensor(padded, i, j):
    """像素 (i,j) 的模型输入：(270,7,7) float32，已做 token 级归一化（无偏）。
    返回的数组内存序就是模型 reshape 前的顺序。"""
    p = padded[i:i + WIN, j:j + WIN, :].astype(np.float32)   # (7,7,270)
    p = np.ascontiguousarray(p.transpose(2, 0, 1))            # ToTensor → (270,7,7)
    p = p.astype(np.float32)
    mean = p.mean(dtype=np.float32)
    std = p.std(ddof=1, dtype=np.float32)
    return ((p - mean) / std).astype(np.float32)


class Scene:
    """一景：立方体 .mat 与真值 .mat。band_drop 给要去掉的波段下标（HanChuan 274 → 270）。"""

    def __init__(self, cube_path, gt_path, band_drop=()):
        self.gt = load_mat(gt_path).astype(np.int64)           # (H,W)，0 = 无标签
        cube = load_mat(cube_path).astype(np.float32)
        if band_drop:
            cube = np.delete(cube, list(band_drop), axis=2)
        self.raw = cube                                          # 未预处理，画底图用
        self.padded = preprocess_image(cube)

    def labeled_coords(self):
        return np.argwhere(self.gt > 0)

    def patch(self, i, j):
        return patch_tensor(self.padded, i, j)


class LongKou(Scene):
    def __init__(self):
        super().__init__(DATA, GT)


if __name__ == '__main__':
    lk = LongKou()
    print('padded', lk.padded.shape, lk.padded.dtype, 'labeled', len(lk.labeled_coords()))
    p = lk.patch(100, 100)
    print('patch', p.shape, p.dtype, float(p.min()), float(p.max()), float(p.mean()), float(p.std(ddof=1)))
