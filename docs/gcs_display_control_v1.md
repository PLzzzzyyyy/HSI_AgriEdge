# 私有 ABI4 显示控制：清显示不是停任务

2026-10-12，隔离候选，未部署/未实板验收。复用现有PL/平台，只改私有App与主机；新的发布绑定和用户Build仍必要。

## 三种操作

- **清PC显示**：本地持久化隐藏选择，保留任务/台账/原包。不会发板卡控制。
- **清PC+DP显示**：明确确认DP当前wire task，先保留PC清显示意图，再向既有健康owner发专用显示命令。无原连接/已静默/版本不支持时不建新socket，PC可单独清，DP未应用明确显示。
- **恢复DP显示**：明确确认后从当前ResultStore已提交CLASS前缀重绘，不推理、不START、不恢复PC选择。普通网络重接不恢复DP隐藏层；新任务初始化才自动显示新结果。

停止推理仍用单独STOP（行边界/回执确认）；删除历史不是清屏的一部分，本组没有物理删除接口。

## 线协议与互斥

专用0x15，v1 header task=当前wire task，payload `<u32 boot, u32 session, u32 nonce, u8 action, 3 zero bytes>`，共28B；action0隐藏、1恢复。必须来自原peer，boot/session/task精确匹配。重试保持同seq/nonce/action，不能把另一请求或另一任务ACK当成功。

ACK仍0x83，acked_type=0x15、acked_seq/任务匹配，value回显nonce；code0表示帧缓存已应用并flush，code9表示未应用，code6保留板端故障。任何ACK都不是摄像头/用户看到显示器的证据。

INFO offset43：bit1独立点能力、bit0点忙、bit2显示控制能力、bit3显示忙；仅允许0/2/3/6/7/14/15，未知位/缺能力的忙态不作为可用证明。未完成显示回执时不换任务/模型或插入点；显式STOP仍独立处理。若当前START已受理但还未初始化画布，显示命令等待该任务初始化，不误清上一任务。

## 结果与证据

SceneCanvas隐藏地图/分类计数显示，但仍累计真实CLASS和任务进度。ResultStore不删不改；恢复先校验完整前缀的范围/类别/直方图，再原子改变画面。错误任务的告警不被清显示抹掉。不重新初始化DP、不重启DPDMA，不碰PL DMA所属缓冲。

每次显示操作保存 `display_时间/session.json, packets.jsonl, summary.json`。恢复需这些原包与原channel相符；不靠summary伪造成功。超时/错误不撤销PC隐藏意图，也不假称DP已应用；原连接恢复会先核INFO显示忙态。测试入口 `sim/host/test_gcs_display_link.py`、`test_gcs_display_control.cpp`、`test_gcs_model_protocol.cpp display`、管道 `Interop.test_display_clear_restore_does_not_stop_task_or_lose_results`。

当前通过的是CPU画布、协议管道与实际BSP语法。物理以太网拔插、DP线/显示器扫描输出以及SD启动均仍待用户实机验证。
