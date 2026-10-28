# 容差口径（docs/engine_arch.md §6 第 6 条，PLAN D3）

## 1 整数路径：0 容差（逐位）

| 比对 | 参考 | 被测 | 容差 | 当前状态（2026-09-24） |
|---|---|---|---|---|
| C 参考 ↔ Python | `model/engine_ref.py` | `sim/host/engine_ref.cpp`（g++ `-O2 -ffp-contract=off`） | 0 | PASS（契约 v3 bfp）：`sim/golden/n6_engine` 共 296 个文件，覆盖入口 A、B 每层的 xn_q / stats / q / k / v / s / attn / x_mid / xn2_q / m / x_out，前端的 S1/Sxx/V/g、xn24、x_embed，以及 logits 和类别字；`batch_hanchuan` 32 像素 0 FAIL |
| C 参考 ↔ Python（int8 版） | `engine_ref.py --num 8`（QAT 权重） | 同上（按权重包头的位宽选格式） | 0 | PASS（09-26）：`sim/golden/n6_engine_i8` 296 个文件、`batch_hanchuan` 32 像素 0 FAIL；int16 黄金同时回归 PASS |
| HLS csim / cosim ↔ C 参考 | `sim/golden/n6_engine/` | `tt_engine`（D4a 入口 A、D4b 入口 B） | 0 | 待 D4 |
| D2（M2 PROJ）↔ v1.4 | `sim/golden/n6_real/` | `tt_engine` PROJ | 0 | csim PASS（D2） |
| 板上 FULL + DUMP / CLASS / LOGITS | `engine_ref.py` | 串口 / 地面站 | 0 | 待板 |

整条路径里唯一的浮点运算，是每个 token / patch 各一次 `sqrtf` 和一次除法。它们是 IEEE 正确舍入，x86、A53、hls::sqrt 结果逐位相同。任何非 0 差异都按 bug 处理，不放宽容差。

复现步骤：
1. 生成黄金向量：`D:/pytorch/python.exe model/engine_ref.py golden`（int8 版加 `--num 8`；只为核对时用 `--out build/host/...`，不在原目录重生成）
2. 编译 C 参考：`g++ -O2 -std=c++11 -ffp-contract=off sim/host/engine_ref.cpp -o build/host/engine_ref.exe`
3. 比对：`build/host/engine_ref.exe sim/golden/n6_engine sim/golden/n6_engine/batch_hanchuan`，应输出 `RESULT PASS`；int8 版把两处 `n6_engine` 换成 `n6_engine_i8`

## 2 对浮点模型：只报统计量（不是逐位）

- 样本：三景回归像素 4,700 个，与 `fixed_regression.py` 同一批。
- 脚本：`engine_ref.py regress`，结果写在 `report/accuracy_fixed_pc.md` 的 "engine_ref" 节。
- 前端、注意力、分类头的误差各单列一行（其余部分全浮点）。

验收线（09-23 定，**09-24 用户改**）：

- 标签一致率 100%，max|dlogit| **≤ 0.06**（原为 0.05）。
  - 放宽原因：HanChuan 入口 B 为 0.053。这个数是三部分叠加的结果：前端 0.017、注意力 0.018、Q5.12 投影路径本身 0.025（`format_scan_pc.md`）。没有哪个部件单独超标，再压就要加宽 attn 或投影格式，代价与收益不成比例。
- **并列规则**（09-24 用户采纳）：浮点模型前两名 logit 差 < 0.01 的像素属于"并列"，任何量化都可能让它翻转，单列说明，不算失败。

最终结果（契约 v3 bfp，入口 B 全整数）：

| 景 | 一致率 | max\|dlogit\| | 结论 |
|---|---|---|---|
| LongKou | 100% | 0.0087 | 通过 |
| HongHu | 99.95%（1 个像素） | 0.0286 | 通过：像素 (649, 56) 的前两名 logit 差 0.002，属并列；入口 A 也翻转 |
| HanChuan | 100% | 0.0532 | 通过 |

## 3 前端立方体格式的选定过程（契约 v2 → v3）

| 立方体格式 | LongKou 入口 B max\|dlogit\| / 一致率 | HongHu | HanChuan | 说明 |
|---|---|---|---|---|
| v2：整景一个 k（`max` 规则，k = 10 / 11 / 8） | 0.011 / 100% | 0.032 / 99.95% | **0.337 / 99.88%** | HanChuan 有离群亮点，max\|x\| = 115.8，k 只能取 8；暗平 patch 的 σ 只有约 29 LSB，量化噪声约 1% |
| 整景 k，允许 ≤ 1e-5 的元素饱和（`sat`，k = 11 / 12 / 11） | 0.011 / 100% | 0.379 / 100% | 0.174 / 99.94% | 暗 patch 改善了，但亮 patch 饱和：回归像素里 HongHu 30～40 个元素、HanChuan 64～116 个元素 |
| **v3：每条光谱一个 2 幂指数（`bfp`）** | **0.009 / 100%** | **0.029 / 99.95%**（唯一翻转是上面的并列像素） | **0.053 / 100%** | 只看前端误差：0.005 / 0.012 / 0.017 |

v3 定义见 docs/engine_arch.md §3.6 与 `src/hls/tt_engine_regs.h`（TT_ENGINE_VERSION 3），要点：

- 导出：每条光谱取一个指数 e，存在波段 270。
- 前端：窗内按 e_min 右移舍入对齐，FRONT_S = 48。
- S1 / Sxx 每像素重算。

诊断脚本：`build/host/d3_front_k_scan.py`、`d3_worst.py`、`d3_blockfp.py`。

## 4 int8 版精度（09-26 用户定口径）

- 验收：int8 官方 Test OA 比 int16 版掉 ≤ 0.5 个点；两版的 OA 都用与板上逐位的整数参考在官方 Test 全集上算（`model/engine_gpu.py test`，对 `engine_ref.py` 逐位核对用 `engine_gpu.py verify`）。
- 与 torch 假量化前向的标签一致率只作诊断：整数引擎比 QAT 多三处 Q3.4 量化（前端输出、残差里的 xn、注意力输出 ctx），只要训练前向与引擎不逐位相同就到不了 100%。

| 景 | int16 引擎 OA | int8 引擎 OA | 差 | 结论 | 对假量化一致率（回归像素，诊断） |
|---|---|---|---|---|---|
| LongKou | 0.9384 | 0.9402 | +0.18 点 | 通过 | 99.11% |
| HongHu | 0.8482 | 0.8464 | −0.19 点 | 通过 | 96.55% |
| HanChuan | 0.8590 | 0.8570 | −0.20 点 | 通过 | 93.63% |

详细数据：`report/accuracy_int8_pc.md`（全集 OA、逐部件分解）；证据文件与命令：`report/evidence.md`。
