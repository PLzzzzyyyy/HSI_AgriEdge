# sim/attn：注意力 / 分类头 HLS 单元的逐位验证（PLAN §17 D3）

单元在 `src/hls/tt_attn.h/.cpp`：SCORES、SOFTMAX、CTX+RES、HEAD 各一个 HLS 顶层（`tt_attn_scores` 等），核心函数 `ta_*` 留给 D4a 并进 tt_engine 的 dataflow。数值定义见 `docs/engine_arch.md` §3.3、§3.4、§3.6，唯一来源 `model/engine_ref.py`。

## 文件

- `tb_attn.cpp`：testbench。回放 `sim/golden/n6_engine` 入口 A、B 各 12 层（SCORES 对 s，SOFTMAX 对 attn，CTX+RES 对 x_mid、S1/Sxx 与由它们算出的 stats_mlp，HEAD 对 logits 与类别字），另比 HanChuan 32 像素批与边界用例。输入文件按字节数精确校验，补齐 lane 填垃圾值、X 的补齐位置放哨兵，结尾核对比对总数（防止空跑 PASS）。宏 `TT_ATTN_UNIT` 选单元（0 全部），环境变量 `TT_TB_LAYERS` 减少回放层数。
- `gen_vectors.py`：以 `engine_ref.py` 为 oracle 生成 `vectors/`（exp 截断阈值与进位边界、T_HI/T_LO 全部表项、attn 舍入半点、全相等与单峰 softmax、ctx 与 x_mid 正负饱和、attn 取满 25 位、logit 并列、conf 在 0xFFFF / 0xFFFE 分界、r = 1 与 63、ncls = 1..24、HanChuan 批的终块 token 1）。开头先对黄金 24 层自检。12 s。

## 命令

```
D:/pytorch/python.exe sim/attn/gen_vectors.py
D:/mingw64/bin/g++ -O2 -std=c++14 -ffp-contract=off -include array -DTT_K3=7 -I D:/xilinx/Vitis_HLS/2020.2/include ^
    D:/HSI_AgriEdge/sim/attn/tb_attn.cpp D:/HSI_AgriEdge/src/hls/tt_attn.cpp -o build/host/tb_attn_k7.exe
build\hls\run_tt_attn.bat <scores|softmax|ctx|head> <csim|synth|cosim> <7|14>
```

- g++ 要用绝对路径（testbench 靠 `__FILE__` 找仓库根）；`-include array`：Vitis HLS 2020.2 的 `hls_stream_thread_unsafe.h` 用了 `std::array` 却没有 include，GCC 15 下编不过。
- `run_tt_attn.bat` 不要在构建目录里执行（csim/synth 会先删构建目录），日志 `build/hls/optimization_build/tt_attn_<unit>_k<K3>_<stage>.log`，`.done` 写 OK / FAILED。

## 结果（09-25）

g++（主机）：K3 = 7、14 各 81 项、502,235 个值，0 不一致。vitis csim 与 cosim：下表各单元全部逐位 PASS。

| 单元 | K3 | 拍数（cosim，RTL） | §4.2 预算 | DSP | LUT | FF | BRAM18 | 估计时钟 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| SCORES | 7 | 3,981 | 3,969 | 24 | 1,549 | 1,267 | 0 | 2.89 ns |
| SCORES | 14 | 1,996 | 1,985 | 48 | 1,861 | 1,415 | 0 | 2.89 ns |
| SOFTMAX | — | 349 | ≈300 | 5 | 1,187 | 1,410 | 2 | 3.46 ns |
| CTX+RES | 7 | 4,015 | ≈4,000 | 28 | 6,496 | 4,682 | 0 | 3.52 ns |
| CTX+RES | 14 | 2,037 | ≈2,000 | 56 | 12,547 | 8,185 | 0 | 3.53 ns |
| HEAD | — | 2,685～2,731 | ≈2,686 | 27 | 3,330 | 3,603 | 2 | 3.54 ns |

DSP、LUT、FF、BRAM 与估计时钟是 csynth 的 HLS 估计（5 ns 目标，xazu5ev-sfvc784-1-i），只看趋势；拍数是 cosim 实测。四个单元合计（K3 = 7）约 12.6k LUT、84 DSP；K3 = 14 约 18.9k LUT、136 DSP。CTX+RES 的 LUT 主要是段起点不对齐时 V / XN 的按 bank 取址与 lane 旋转选择。

## 布局约定（09-26 D4a 起改为引擎块布局，单元不再用流）

- Q、K、V、XN、X 都是 `blk[t·TA_H + h][i]`（`ta_blk_t`），元素 (p, t) 在 lane h = p % TA_H、字 i = p / TA_H；t、h 合成一维是因为顶层数组参数上对两个维度各写一条 ARRAY_PARTITION 只有一条生效（II 掉到 2）。
- SCORES 直接读 K 块（token c 依次）；HEAD 直接读终块的 token 1。
- CTX 按 (token, 组, 段) 扫，段起点 441c 不按 TA_H 对齐，按 bank 各自取址、按 lane 旋转。
- HEAD：`wh[g][p]` 的 16 位 lane q 是类别 4g + q 的 W[p]；返回 CLASS 字 {conf[31:16], 0, label[7:0]}。
- 09-25 的 csim / cosim / csynth 数字是改动前（k 流、V/XN/X 为 `[h][t·TA_BD + i]`）的版本；09-26 改动后 g++ K3 = 7 / 14 仍 81 项 0 不一致。
