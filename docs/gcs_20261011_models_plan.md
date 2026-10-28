# 第一轮 D：多场景/模型与安全闭环（候选实施计划）

> **09:30用户交接决定**：当前线程goal已paused；新对话不用goal，先看第一轮验收，不自动继续本计划的实施。最新入口 `gcs_20261011_acceptance_handoff.md`，完整范围与待授权/待实机项不变。

2026-10-11；起点 `9e1e924`。这是实施/验收计划，不是板测通过记录。

## 本轮边界

- 用户要求继续全部第一轮，候选齐备后统一同步；用户 Build App、下载、上板。当前不运行 prepare/sync、不启动新服务、不 START、不复用 bb6bd8e3。
- 多模型沿用既有 v1 WBEGIN/WCHUNK/WCOMMIT/WACT/INFO 布局、int16 TTE2 与现有 `tt_m3a`/`m3a_roi`/FatFs 接口；仅私有 App、GCS、测试及配套生成工具。旧数值/driver/BSP/HLS不改。
- 现有 BSP 实际支持可写 FatFs、LFN=1、两个逻辑卷；“可写”不是已写卡或已持久化。板上文件存在与否只能由实际扫描/读取/CRC确认，不能用本地文件推断。
- E 真实注意力、F 脱离PC身份与可能的公共计时埋点尚待专项确认，单列待授权，不能用 PC/logits/MODE_DUMP 代替注意力。
- 用户补充：第一轮候选之后继续第二轮准备；可先整理验收矩阵/复现和性能定位方案，不能提前判第一轮实机完成，也不据此启动 USB/性能优化或其他未授权实现。

## 分层与安全决定

1. **本地模型目录**：三景固定输入/类别契约，模型按 scene/tag/kind/bytes/CRC/SHA 标识；只读验证实际文件和导出来源。缺 int16 包的版本明确不可部署，不回退其他权重/PC计算。
2. **板端注册/传输**：有界 CPU 暂存；WBEGIN 精确身份续传，WCHUNK 顺序与重复内容校验；完整长度、CRC、TTE2 位宽/类数/保留段和配套包通过才登记。错误不改变当前模型、不触碰 DMA 缓冲。
3. **持久化**：既有 FatFs 的临时文件→sync→关闭→rename，旧目录不删；冷启动重新读取/CRC检查，不以目录名或缓存判断成功。失败显式 code4，不能当已落盘。FAT 不能承诺掉电事务绝对原子。
4. **切换**：单库只在健康安全边界 LOAD_W；不清除原 DMA 永久故障锁，不在 callback 里执行 SD/IP。下一任务用新模型，旧结果槽保留自己的 scene/CRC/尺寸/类数；单库不伪装支持 when=1 双库行中热切换。
5. **业务链**：恢复/探查/历史/结果槽/报表/固定Test/DP均使用任务自身模型和场景，不套当前 UI 选择。闭环需要更新前和更新后两次真实任务；训练参考不充当板成绩。

## 阶段检查与未完成门禁

- 定向主机测试覆盖三景、坏头/CRC/路径/序号、重复与重排、SD失败、活动任务/故障锁/切换回退、四槽回收、旧历史恢复、跨模型PROBE及报告身份。
- 所有源码候选完成才更新最终源清单/同步器/ELF门禁；旧24源 `scene_probe_s3_r1` 不能审查新版本。
- 最终仍需用户真实三景/多模型/上传重启持久化/训练复测/真实12层注意力/SD冷启动/DP目视/分阶段计时及故障增量验收。离线PASS不关闭这些项。

## 证据入口

`report/gcs_roi/20261011_models/`；旧服务只读状态单独保存。各阶段原始失败/通过日志和源码SHA逐项记录，不生成板测数字。

## 2026-10-11 01:12 D2 进展（仍非 D 完成）

私有 `roi_models`/`roi_model_sd` 已接 `Protocol`、runtime、main、结果槽与三景 DP：沿用 v1 四命令、48 条有界注册、独立 CPU 暂存、CRC/格式/配对、FatFs 读回持久化、单库终态切换与不可清故障锁、跨模型 PROBE 临时切换/恢复。输入预检失败与 DMA 故障分开；旧结果自身身份不改。证据/限制/命令见 `report/gcs_roi/20261011_models/private_app/review.md`。

最终离线 9 测试程序、17 runtime 模式、5 driver 等待回调模式、6 Python 校验、4 实际本地配对、7 A53/C++11 语法入口通过，未板测；DP 三图是水印合成夹具。LongKou/v1 缺完整 companion SHA 仍不可上传，不能因结构配对 PASS 伪造来源；三个 int8 不适用当前引擎。

**立即继续 D3**：现 `board_task`、UART、核验仍 LongKou/v2/旧 App 硬编码，须接真实 GCS 上传/激活、训练导出与板任务复测，并泛化恢复/历史/报告/Test/PROBE/计时/长 SD 读超时。新 App `model_lifecycle_r1` 尚不匹配当前后端，当前不可部署。E/F/公共计时三个待确认项、全部 G 与第二轮准备范围不变；旧同步器仍 24 源，未 prepare/sync/Build/设备动作。

## 2026-10-11 03:54 D3 进展（候选，未上板）

board_link/board_upload已接server单一UDP owner、三景任务/模型传输/专用恢复/历史/Test/报告/UART/独立核验和配对导出。现在两端候选同为model_lifecycle_r1；旧生产Python及旧24源同步/ELF门禁不匹配，未部署。95Python集成+6包校验+8旧PROBE、9主机程序/17runtime/5等待回调、7真实本地配对、7A53/C++11、73离线浏览器通过；详见 `report/gcs_roi/20261011_models/gcs_link/review.md`。

修复长序列半范围/恢复时间锚和切景旧比较条，第二包续传保留暂存。旧checkpoint只做本地配对导出，不运行训练或板推理，公开API/UI不出CPU参考成绩。下一继续全D/生命周期覆盖审查、必要离线互通及完整验收准备，`docs/gcs_20261011_acceptance_matrix.md`保留所有A～G/T。E/F/公共计时仍待确认，最终统一同步/用户Build/实际增量验收都未完成；不能把这轮检查点当第一轮候选全齐或目标完成。

## 2026-10-11 06:45 D4 进展（离线互通，不是板测）

GCS真实协议字节经管道进入编译的私有Protocol/Models/ResultStore/ModelSd（RAM FatFs、合成数值），7用例覆盖传输/补传/切换/恢复/文件重扫。修复未启动job污染模型task与HanChuan609区间超限，SD分块服务/CRC避免主动长时无网络服务；不改driver/BSP/公共接口。完整证据 `report/gcs_roi/20261011_models/interop/review.md`。

原LongKou/v1由同checkpoint补独立v1_board完整来源，engine SHA与原v1相同、原目录不改；不是用其他权重回填。只读工具核45个未来SD数据文件（1150149380B），新准备入口 `docs/gcs_20261011_data_boot_readiness.md`。没有生成BOOT.BIN、写卡、部署或新板数字。最终99Python+6包校验+8旧PROBE、7互通及全套主机/runtime/A53/73浏览器通过，但E/F/公共计时授权、全部候选与最终实机仍欠。继续完整矩阵/授权内准备，不启动USB/P2/优化，不运行旧24源同步/ELF工具。

## 2026-10-11 08:47 私有分项计时及身份关系门禁

在私有App实现9个前台分项与内部等待服务子集，原step计算指标同源；UART读取/API/PC折叠详情/报告核验已接，详见 `docs/gcs_20261011_timing_scope.md`。外层candidate CRC必须对应int16包描述，元数据关系不一致拒绝。最终104Python/80浏览器等离线检查通过，证据 `report/gcs_roi/20261011_models/app_timing/review.md`；实际main埋点仅A53语法，没有新板计时。

此候选**不是内部PS/driver/纯PL细分完成**，仍保留T2公共扩展授权及实测；E真实注意力、F独立身份/镜像、G最终统一同步和用户完整实机未完成。旧24源工具未用，继续完整范围，不以私有较粗分项缩减目标。
