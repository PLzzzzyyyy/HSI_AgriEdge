# MODEL.md：模型来源、权重、量化与已知数值问题

对应指南 §3.1.5.3 的模型声明要求（自主选题赛道不强制，借鉴其格式，见 PLAN §16.6）。所有数字来自 PC；板上数字另见 `board/`。

## 1 模型

- 结构：Tensor Transformer for HSIC，`unoverlapping` 变体（N = 6 token，7×7×270 patch，Tucker 三模积投影 12 层）。代码 `model/tt_model.py`，讲解 `docs/legacy_7020/TT_EXPLAINED.md`。
- 上游：`D:/FPGAlearn/Tensor-Transformer-for-HSIC-master`（论文作者公开代码，随附 LongKou 的两份 .pth，无训练脚本）。
- 本项目训练脚本：`model/train_scene.py`（Adam 1e-3 + 余弦、batch 128、500 轮、best-val 选模；因子 trunc_normal 0.05，cls/pos 0.02）。数据划分为 WHU-Hi 官方 Train100/Test100，另从 Train100 每类抽 10 个做验证，坐标入库 `data/splits/`。

## 2 权重（checkpoint 不入库，按 sha256 核对）

| 景 | 类别 | 来源 | ckpt sha256[:12] | Test100 OA / AA / Kappa（float） | 权重包 |
|---|---|---|---|---|---|
| longkou | 9 | 上游 `TensorTransformerHSI_unoverlapping_LK.pth` | 07ff41b82e60 | 0.9314 / 0.9089 / 0.9110 | `data/scenes/longkou/weights/v1/`（与 7020 时期 `model/data/` 逐字节相同；黄金向量、csim、主机回归都用它） |
| longkou | 9 | 自训 seed 0，best val 第 25 轮 | 3f8acada1311 | 0.9384 / 0.9273 / 0.9201 | `weights/v2/` |
| honghu | 22 | 自训 seed 0，best val 第 25 轮 | 2bcb0b8f4742 | 0.8482 / 0.8485 / 0.8129 | `weights/v1/` |
| hanchuan | 16 | 自训 seed 0，去末 4 波段，best val 第 30 轮 | 05538d45df21 | 0.8590 / 0.8328 / 0.8359 | `weights/v1/` |

完整记录 `report/accuracy_pc.md`（由训练脚本追加）。权重包内容与字节数见 PLAN §14：IP 用 `weights_all.bin` 289 KB（12 层 × 4 投影 × 3014 int16），PS 用 float32 的 cls_token、pos_embed、classifier。

## 3 量化方案（`model/quant.py`，与 `src/hls/tt_types.h` 一致）

| 量 | 格式 | 范围 | 用途 |
|---|---|---|---|
| data_t | ap_fixed<16,4> Q3.12，AP_RND + AP_SAT | ±8 | DDR 里的激活（PS 归一化后送 PL，PL 投影结果送回） |
| wt_t | ap_fixed<16,2> Q1.14 | ±2 | 因子矩阵 |
| mid_t | ap_fixed<18,4> Q3.14 | ±8 | 模 1、模 2 之后的片上中间量 |

PS 侧归一化、注意力、分类头为 float32（`tt_net.cpp`）。定点仿真 `model/fixed_point_sim.py` 与 HLS 逐位一致（7020 时期 csim/cosim/板上三级验证）。

## 4 定点回归（`model/fixed_regression.py`，2026-09-22）

官方 Test100 每类抽 100 像素，输入取板上 float32 立方体，同一 checkpoint 走 float 与 fixed 两条路径。

| 景 | 像素 | 标签一致率 | max\|dlogit\| | mean\|dlogit\| | 有饱和的像素 | 最大激活 |
|---|---|---|---|---|---|---|
| longkou（v2 自训） | 900 | 100% | 0.177 | 0.0010 | 1.8% (16) | 14.5 |
| honghu | 2200 | 100% | 0.222 | 0.0015 | 0.8% (17) | 12.5 |
| hanchuan | 1600 | 100% | 2.104 | 0.0030 | 2.6% (42) | 20.2 |

完整表 `report/accuracy_fixed_pc.md`；逐像素坐标与两路 logits 在 `data/regress/*.npz`（不入库，可重生成），板上跑同一批像素时直接比对。

## 5 已知数值问题：Q3.12 饱和

- 现象：三景都有 1～3% 的像素，在某几层归一化后的激活绝对值超过 8，进 PL 前被 AP_SAT 截到 ±8。未饱和像素的 max|dlogit| ≤ 0.027；饱和像素最大到 2.10（HanChuan (373,112)，激活 20.2，该像素分类边距 5.3，标签未翻）。统计脚本 `model/saturation_stats.py`。
- 上游 LongKou 权重在 7020 时期的同类统计：主机回归 12 层 max|dlogit| 1.15e-3（黄金像素未饱和）。
- 影响：抽样内标签一致率 100%，精度不受影响；但 max|dlogit| 不能作为"逐位一致"的口径，报告要分开写"标签一致率"和"logits 误差"（PLAN §16.5 已有此要求）。
- D1 决定（2026-09-23，`docs/engine_arch.md` §3.1；实验 `model/format_scan.py`，结果 `report/format_scan_pc.md`）：整网引擎片上 data_t 用 18 位 Q5.12（±32）。同批像素上未饱和像素与 Q3.12 逐位相同，饱和像素 max|dlogit| 降到 ≤ 0.03，三景标签一致率 100%；16 位的 Q4.11 / Q5.10 未饱和误差反而增大 1.3～3 倍且有标签翻转，不取。v1.4 IP 与 M1/M2 黄金向量仍是 Q3.12。int8 版（PTQ 七种组合的结果与 QAT 计划）见 §3.7。
