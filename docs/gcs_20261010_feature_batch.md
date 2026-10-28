# 全功能推进批次：整景/PROBE WIP补齐与简化验收

更新：2026-10-10；起点 `ee2b2c2`。**仅本批离线检查通过，未同步Vitis/Build/下载/实机验收，第一版未完成。**

**本日后续优先记录：** 用户已确认S3最小旧driver改动并要求“做完告诉我测试”。S3＋整景＋PROBE已整理成可供用户同步/Build的阶段包；等待回调/重入保护、S3与单点自动核验及新ELF门禁均离线通过。用户App尚未同步，须本次确认自动Build关闭；完整步骤见`docs/gcs_scene_probe_s3_board_test.md`。下述“S3待单独确认”等保留为前一批历史，不再是当前许可状态。

## 当前已实现

- 修复交接中的runtime host链接缺口，测试桩核验真实调用约定，不是空返回：完整场景、执行中禁止探查、CLASS失败/不完整完成、LOGITS尺寸错误及DMA失败均有用例；输出失败保持调用者缓冲与原任务CPU结果不变。
- 板端PROBE出队后仍保持独占；同seq仅缓存回复，不重新计算；旧seq拒绝，含16位回绕。只改私有App两个cpp，没有改旧driver/BSP/数值/公共UDP布局。
- 完成后保留**同一socket/peer固定300秒**供显式探查，空闲不发心跳，不续期；到期/用户关闭/源切换/服务退出关闭。任务完成通知只发一次。PROBE用原seq原包有界重传最多3次，5秒结束，独立错误/证据，不覆盖整景成功。
- PC LOGITS严格关联task/req_seq/scene/wcrc/坐标/长度/CLASS与argmax、已有ROW，要求本次PING/PONG和匹配STATUS；无PC模型补推理。概率是CPU对板端Q16 logits做softmax的显示派生值，明确不等于引擎置信度；输入光谱/注意力仍未回传。
- 原GCS新增手动PROBE、会话关闭、整景核验包下载按钮。恢复检查HTTP状态/长度/掩码/CLASS；失败不标记已加载；空闲tick不重复绘制22万点。当前只覆盖页面恢复的生产loadRun路径，**不声称已实现服务重启后的历史恢复/板端INFO**。
- `gcs_scene_verify.py`只读核550行CRC、总CRC、22万唯一像素、身份、ACK/DONE、JSON逐字与字段一致；不引用旧15像素参考补数据。
- “核验整景并下载证据包”：检查本次UART、UDP、页面words+seen的SHA256、实际打包的JSON，下载原始UART/UDP、JSON/CSV及报告。通过仅指此数据链路，不指S3、DP、模型闭环、Test100或全部功能。无匹配UART时明确缺材料，不自动重跑。

## 本轮新增UART授权与操作方式

用户要求旧验证过程不要太麻烦；说明串口独占及影响后，用户回复“欧克4”，按同意刚说明的有限范围记录：

1. **只有用户主动点击**“连接并自动采集”才打开所选UART0 COM口；刷新列表/页面刷新/服务启动不连接、不取随机数、不发包。
2. 先释放其他串口终端、选择原UART0端口和原波特率（界面115200只是默认选项，不是本轮测得）；8N1/无流控，DTR/RTS在open前置false，不发BREAK/复位。串口被占用不杀进程、不抢占、不自动重连。USB驱动/硬件瞬态未实测，不承诺连接动作物理上绝无电平变化。
3. 连接后**用户自行独立冷启动**，完整r1提示到达才现取PC OS CSPRNG一次、持久化身份占用、发送8hex+LF一次；收到相同boot_id/WCRC的S2C READY后仅打开地面站本地许可门禁，**不发送START/PING**。
4. r1板端60秒期限不改；PC等待提示最多180秒、发送后READY最多120秒、采集总限45分钟，均不续期。部分写入/非法身份/重复提示/超时/板端STOP时保留首错、无重试；停止后释放端口。
5. 原r1允许0，但当前GCS门禁禁止0及已用旧ID；本候选抽到不可用值时停止，不以常量/再次取数降级。冷启动真实性仍是操作者义务，不把UART文本当物理冷启动证明。
6. Build、下载、PL复位、地面站推理启动均仍由用户；工具不代做。未打开过真实串口，也未实测自动r1。

采集目录 `build/host/gcs_uart/capture_*/`：`uart.bin`原字节、`uart.txt`、`serial_events.jsonl`（先记tx_attempt，成功再记tx）、session/summary。身份不得从旧日志复用。

## 验证入口与证据

所有本批离线检查合并为一个入口，通常由助手运行，**不是要求用户每次运行它**：

```powershell
D:\pytorch\python.exe -B tools\gcs_roi.py test
```

结果：`report/gcs_roi/20261010_full_feature/checks_170532_852262/checks.json`。
- 最后审查补强UART线程启动前的active预留门禁，避免独立调用者在worker赋值前二次连接；只重跑受影响的6个UART用例，PASS和最新两文件SHA在同目录族 `uart_reservation_delta/`。其余已通过项未机械重跑。
- Python 43个用例（含7个整景receiver），C++调度/协议/6个PROBE定向场景通过；Vitis **2020.2** AArch64实际BSP的4单元`-fsyntax-only`通过，不是目标链接/Build。
- 5个JS语法入口通过；无头Edge离线浏览器16项通过（真实组件，确定性数据fixture，非模拟板或板上证据），截图未用于宣称真实分类结果。
- 首份RED保留：`full_scene/checks_163726/probe_early.log`、`checks_163756/protocol.log`；对应GREEN `checks_163815`，最终统一检查关联 `full_scene/checks_170532`。
- 增量测试可单跑 `sim/host/test_gcs_{probe,uart,scene_verify}.py`。`tools/check_gcs_scene.cjs`自建临时localhost静态fixture服务并在finally关闭浏览器/服务，不连接真实GCS/UART/UDP。
- `tools/check_gcs_roi.cjs`仍是旧固定ROI观察器，明确拒绝整景，避免继续把15格当整景验收；本轮仅语法检查，没有重跑旧已通过板测。
- 既有FastAPI `on_event`弃用告警仍存在，不是本批测试失败；未无关迁移整个服务生命周期。

## S3及剩余功能（不得当完成清单）

已定位S3阻塞点 `src/ps/tt_m3a.cpp:execute`。已向用户集中请求：允许在 `tt_m3a.cpp/.h` 增加默认关闭的等待服务回调，等待PL时处理网络、禁止回调重入推理；原数值/cache/DMA/超时永久停车不改。**尚待用户对此单独确认；本批没有修改这两个旧文件。**

获准后先做callback/重入/超时不读DMA定向测试，再集成App与控制命令安全边界；实际网络服务间隔需用户新板测，不把批间轮询或host fixture当S3通过。

其余仍待：运行中探查及注意力/光谱方案、任意ROI、PAUSE/RESUME/STOP与安全任务切换、ROWREQ/丢包恢复/结果槽/INFO/历史、全场景模型上传CRC/持久化/切换、原农情/地块/统计/导出业务、Test100/混淆矩阵/OA真实板执行、多模型PC训练后板端闭环；最后统一DP中文/标点/分类进度/统计并用户目视验收。

不让用户立刻Build本中间批次；继续攒齐功能、离线门禁及目标源清单，确认自动Build关闭后再备份同步。旧24源App/ELF `9a1cd013…`、已用boot64ead9e4、小ROI已通过证据保持原样。未测功率/温度/性能保持未测，不需要功率计。DMA永久停车/外部PL复位/CPU成功前缀/补卡不追溯/P2暂停/G2旧OOC FAIL及全部历史限制保留。

本批临时测试进程均退出；用户IDE/XSCT/hw_server/板端未操作。只任务文件本地检查点，不push。恢复先读本页，再读旧完整清单 `gcs_20261010_next_handoff.md`，旧文“未授权UART/host link FAIL/无PROBE按钮”以本页较新状态为准。
