# 第一轮计时口径：私有分项候选与已授权待实现的内部细分

**12:21收尾更新**：用户要求等原后台结束后交接；完整RTL cosim已于12:17 PASS，12:18任务进程退出。未继续export/system/新测试。最新入口 `gcs_20261011_round1_resume.md`，不是第一轮完成或部署就绪。

**2026-10-11 本轮实施更新**：已写 `tt_measure.h`、原PS取窗/归一化/embed和driver cache/submit/wait/complete候选，新增TASK_DETAIL/TASK_ENGINE与GCS/报告；真实RTL counter接现有cycles寄存器，完整RTL最终回执待核。step总耗时仍不是纯PL，各内部桶属于step子集，wait_service属于wait子集，PL周期又在submit/wait内，均不能重复相加。换算频率来自33,333,000Hz参考/RPLL48/2/4=199,998,000Hz，名义200MHz分列，CRL读核最后扩展未做最终验证。没有板测数值。详见 `gcs_20261011_round1_resume.md`；以下08:47是前阶段历史，不否定本轮专项已授权/部分实施。

**2026-10-11 09:57许可更新**：用户明确授权上一盘点列出的T2必要公共数值/driver计时接口及E/F必要实现，见 `gcs_20261011_implementation_handoff.md`。本次没有新实现/测量；下文08:47阶段的“待确认”只保留为历史许可状态，不再重复请示同一范围。范围外扩展及用户设备操作边界不变。

2026-10-11。此文是源码候选/验收说明，不含新板测数值。计算像素/秒、ms/像素始终属于第一轮；新增私有App分项**没有替代**尚未实现的PS内部/纯PL细分。

## 保留的计算指标

- UART `TASK_DONE/TASK_STOP.compute_us` 与 STATUS 的 `ms_per_px` 使用同一批 `step_task()` 调用的累计墙钟时间：含PS取窗/embed、driver/cache、引擎运行及等待服务；**不是纯PL周期或纯推理内核时间**。
- `ms_per_px = compute_us / committed_pixels / 1000`，`px/s = 1000 / ms_per_px`。只对已确认的有效提交计算；没有数据/失败继续显示未测，不能拿PC接收耗时回填。
- LOAD_W、SD、显式PROBE、前台DP/UDP、暂停/idle不混入这个计算分母。每次分块仍≤4且不跨ROI行，STOP/PAUSE在行边界处理。
- 本次用私有计时scope结束值同时更新`compute_us`和step分项，避免两次采时造出两个不同“计算总数”；包含边界测量代码自身开销，不借此宣称提速。

## 新增私有 App 墙钟分项（不更改公共接口）

`src/ps/s2c_roi_app/roi_timing.h`只有CPU bookkeeping与现有`now_us()`读取。没有driver/BSP/HLS/公共数值模块或UDP字段修改，9个前台不重叠桶：

| part | 包含 | 不能声称 |
|---|---|---|
| setup | 本次START的模型/输入准备、健康driver初始化/LOAD_W与begin_task；含内部SD/等待服务 | 独立SD耗时、纯LOAD_W耗时或纯PL |
| step | step_task墙钟；同上述计算指标 | 独立PS数值准备或纯PL周期 |
| probe | 运行中的PROBE调用及临时模型/输入恢复 | 单次CLASS、纯LOGITS、真实注意力或不含切换的探查延迟 |
| results | 已完成CPU结果拷取、结果槽提交和CLASS CRC | PL输出DMA时间 |
| display | 前台DP begin/append/update | 显示器端到端呈现延迟或用户目视通过 |
| rows | 前台ROW分片、补传轮询及发送 | 全部网络开销或链路吞吐；pump内STATUS仍属于pump |
| pump | 外层网络/定时器轮询；包括其中的控制解析与STATUS发送 | 纯UDP发送时间 |
| model | 任务期间的模型命令轮询/校验；包括未发生操作的轮询成本 | 单一模型上传耗时 |
| control | 行边界控制检查调用；包括空轮询 | 用户点击到板端状态改变的往返延迟 |

`wait_service`另记为setup/step/probe等桶**内部子集**，不进入9项合计。SD服务或driver等待中的嵌套pump不会再单列到前台pump，避免重复累计。

`elapsed_us`起于前台接受本次START工作、止于终态已处理后冻结计时；包括setup及期间暂停/日志。`accounted_us`为9项合计，`other_us=elapsed-accounted`是未埋点调度/诊断日志/暂停或空闲等余项，**不能全部当PS、不能全部当纯空闲**。终态之后的PROBE/补传不会改写已冻结的旧任务计时。

## 原始日志、读取与失败门禁

- 每任务输出一次 `S2C TASK_CLOCK session=... task=... elapsed_us=... accounted_us=... other_us=... valid=...`，并输出9条 `TASK_PHASE`及1条`wait_service`子集。都走原有有界UART日志，不改变启动身份来源。
- 单调性、区间重叠、uint64累加溢出错误使`valid=0`，读取侧不显示部分累计值为完整测量。
- `gcs/board_timing.py`要求正确READY boot、TASK_BEGIN场景/model/CRC/ROI/类别、终态提交像素；逐项数量/格式/非负值/完整性/唯一性/合计/嵌套子集及step总数核验。
- step调用数应等于完成行数×`ceil(ROI宽/4)`。step累计时间必须与原UART compute_us一致，并与原STATUS float32平均吻合，不接受“只要总时间差不多”。
- `GET /api/run/{rid}/timing`只读已保存UART文本，不打开串口、不发板命令。缺记录、旧任务、运行中、错误、身份不符返回不可用/未测，没有接收时间替代值。历史切换、异步过期回执必须清掉旧表。
- PC在原“链路与下发→任务记录”内的折叠详情展示，保留中央主图与现有仪表。导出JSON、任务核验报告及农情报告包保留完整身份、原UART字节哈希和口径；无内部PS/PL数据时显式标缺。

## 验收与剩余授权

- 主机合成时钟/日志测试与A53语法检查只证明候选逻辑，不证明硬件时钟、实际时延、DP显示或第一轮验收。当前没有新实机计时数据。
- 最终用户验收需：正确新App/ELF/IP-XSA身份，健康任务与有界STOP各一次，UART/STATUS/浏览器/JSON/报告step总数对应，9项合计及wait子集不重计；跨模型/场景、PROBE、暂停、SD慢操作与故障缺项按完整矩阵验证。不得为通过而把功能路径移出实际范围。
- **T2仍未实现/待确认**：公共数值模块内的取窗/归一化/embed时间，driver/cache提交/完成时间，纯PL周期/频率口径。需要相关公共模块或driver接口扩展时先说明并等授权；本次私有桶只是已授权部分，不能代替T2。
- **E/F仍待确认**：真实12层注意力的HLS/driver/公共输出/分片/新IP-XSA；脱离PC串口的boot身份来源/持久记录/失败门禁。此新增日志不是新的独立启动身份。
- 全候选齐备后才统一同步/用户Build下载实机，旧24源同步/ELF门禁现在仍不可用于新版。第二轮仅整理性能归因方案，不启动USB、旧P2或优化。
