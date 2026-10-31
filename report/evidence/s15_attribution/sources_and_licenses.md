# 来源与许可核对清单

更新：2026-09-29。范围：本地工程、导入来源和用户提供的官方指南副本。本文是发布前核对清单，不是法律意见或完整授权证明；本次未联网核对上游最新条款，未公开发布、删除数据或修改现有许可证。

## 1. 发布边界

- 官方指南 §3.3.3.3 要求最终作品在 GitHub/Gitee 开源，且协议允许再分发；这不赋予作品使用的第三方内容再分发权。
- 根目录 [LICENSE](../LICENSE) 有 MIT 声明，仅能覆盖有权按该许可发布的部分；不能覆盖 WHU-Hi、上游模型、厂商 BSP、文档或其他第三方权利。
- **本地能下载、能训练、能编译，不等于可以把原件或派生内容放进公开仓库。** 无明确授权的内容先列待核项，最终决定由权利方条款或书面许可支持。
- 不因原始 `data/raw` 被忽略就断言仓库没有数据：`model/data`、`sim/golden`、划分文件及部分 `board` 文件包含数据或其派生内容，必须单独核对。不能只增加下载链接却忽略已经入库的内容。

## 2. 逐项清单

| 内容 | 已确认来源/本地依据 | 已知许可与尚缺证据 | 公开交付前动作 |
|---|---|---|---|
| 本项目原创源码/文档 | 根 `LICENSE`，项目 Git 历史 | MIT 文本存在；不代表全部混合来源已经授权 | 复核版权归属，界定原创/改编/第三方范围 |
| Tensor Transformer 模型代码 | `model/tt_model.py` 文件头、`model/MODEL.md` §1 模型；上游本地副本 `D:/FPGAlearn/Tensor-Transformer-for-HSIC-master/Tensor-Transformer-for-HSIC-master/` | 本地副本未找到 LICENSE/COPYING/NOTICE；未确认固定上游 commit 和再分发许可 | 核对正式仓库 URL、commit/tag、许可证；保存原始声明，必要时联系作者 |
| 上游 LongKou checkpoint | `model/MODEL.md` 中上游权重条目，上游 README 的 checkpoint 说明 | 有文件不等于获授权；权重条款与代码条款须分别确认 | 补来源版本、完整 SHA256、权重授权/获取方式 |
| 自训三景及 QAT 权重、导出包 | `model/MODEL.md`，`data/ckpt/`，`data/scenes/*/weights/`；数值与包哈希见 `report/evidence.md` | 与上游 checkpoint 区分；训练数据限制及权重再分发权限尚未闭合 | 按版本记录训练脚本、数据、种子、SHA256 和可发布范围，不能自动宣称无使用限制 |
| WHU-Hi cube、GT、官方划分 | `data/README.md`；原包 `data/raw/WHU-Hi/README.docx` 的 Copyright 段 | **限学术用途、禁止商用、要求引用已确认；再分发权限未确认** | 保留原条款及引用；公开打包前取得允许范围，不以根 MIT 替代 |
| 图块、黄金输入/参考、划分与板上示例 | `.gitignore` 的入库例外、`model/data/`、`sim/golden/`、相关 `board/` 及 splits | 可能源于 WHU-Hi 或上游权重；不能假设“派生”就可自由发布 | 按文件分类追溯；区分原创脚本、数值结果和数据样本；调整交付范围须先确认，不自动删除 |
| 7020 / YOLO 来源代码 | `CLAUDE.md` 的只读来源；`src/ps/reference/README.md`、`tools/reference_yolo/README.md` | `TT_HSI_FPGA` 冻结 commit `a348f0a` 是来源记录；两个来源项目根目录未见 LICENSE，不能据此判定所有导入代码许可 | 核对原作者/厂商文件头与修改范围，保留声明及固定来源版本 |
| ALINX 文档、出厂工程及 Xilinx BSP/lwIP | 厂商本地资料与生成平台各组件 | 适用各自许可证；工具使用权不自动等于可再分发安装包或全部生成内容 | 分别审查手册、BSP 源码/库、bitstream/XSA/ELF 等交付内容；不要打包工具安装目录 |
| ECharts | `gcs/web/vendor/ECHARTS_LICENSE.txt` | 存有 Apache-2.0 文本；其他适用版权/NOTICE 仍需核对 | 保留许可证及适用声明，核对实际库版本和来源 |
| pySerial（2026-10-10 UART辅助运行时） | 本机 `D:/pytorch/Lib/site-packages` 已装3.5，`importlib.metadata`读取版本/License=BSD | 本轮只调用已装包、未下载或分发库二进制；metadata不是完整再分发许可审查 | 最终打包若包含依赖，补保留pySerial自身完整LICENSE及版权声明；不以本项目MIT覆盖 |
| 官方竞赛仓库副本 | `fpgachina26-amd-master/fpgachina26-amd-master/TRACK_GUIDE_2026.md` | 本次仅作为条款依据，不是本项目原创材料 | 不整份纳入作品提交；需要模板时引用正式来源 |

## 3. WHU-Hi 原包已确认条款与引用

本次只读核查原包 `README.docx` 的 Copyright 段，其中写明：

> The WHU-Hi dataset can be used for academic purposes only … but any commercial use is prohibited.

这确认了用途限制，不是允许再分发的声明。比赛使用是否满足具体授权范围、原始或派生样本能否公开、训练权重能否再分发仍需按权利方条款核对。

原包要求引用：

1. Zhong et al., *WHU-Hi: UAV-borne hyperspectral with high spatial resolution (H2) benchmark datasets and classifier for precise crop identification based on deep convolutional neural network with CRF*, Remote Sensing of Environment, 250, 112012, 2020。
2. Zhong et al., *Mini-UAV-borne hyperspectral remote sensing: From observation and processing to applications*, IEEE Geoscience and Remote Sensing Magazine, 6(4), 46–62, 2018。

Tensor Transformer 上游本地 README 给出论文 DOI：`10.1016/j.patcog.2025.111470`。论文引用不能替代模型代码/权重许可证；正式报告完整作者表、出版信息和链接仍需核验。

## 4. 最终发布核对

- [ ] 每项补齐正式来源 URL、版本/commit、许可证原文或书面授权及核对日期。
- [ ] 检查 Git 已跟踪数据和历史提交；如果确认不应公开，先由用户决定交付/历史处理方案，不能默认直接 push 当前历史。
- [ ] 明确哪些数据由复现者自行获取，记录所需文件、哈希、训练/导出命令及预期结果。参考 `data/README.md`、`model/MODEL.md`、根 `README.md`。
- [ ] 固定依赖版本、保留第三方版权/NOTICE，检查密钥、个人信息和不应分发的厂商包。
- [ ] 许可核对完成后再进行用户授权的对外发布；本清单不将任何待核条目标记成已许可。
