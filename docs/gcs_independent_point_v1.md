# 私有 ABI4 App：独立单点与原 owner 恢复

2026-10-12。本页描述隔离候选，不是 v5 已部署能力；不修改 PL/HLS ABI，也不是所有 v1 客户端都可使用的协议保证。主机、App 和发布身份必须一起重新绑定，仍由用户 Build/下载。当前生产服务和 SD journal 未操作。

## 不依赖整景

- 新 `POST /api/board/probe` 指定 scene/version/row/col。通过本地候选、启动身份和原 socket owner 检查后，仅使用 INFO、PING、PROBE；不分配 Run、不发 START/STOP、不把单点填成整景结果。
- 没有任务时 wire task=0；有任务时沿用该 owner 的实际 wire task。每次操作生成新的 request_id，线上的 PROBE 序号在同一 boot/session/task 内不复用。历史探查不自动回填到新选择。
- 复用既有、已校验的 SD 输入/LOAD_W/CLASS/LOGITS+注意力路径，不新增数值算法。首次单点允许加载目标包，但不声称模型已激活，不设置 task attempted/completed。有原驻留模型时，成功恢复它后才提交单点结果；DMA 故障不重写硬件所属缓冲区。

## 私有线协议扩展

| 位置 | 语义 |
| --- | --- |
| PROBE 0x09 body flags bit0 | 请求真实 ABI4 12×6×6 Q0.24 注意力，保持既有含义 |
| PROBE body flags bit1（值2） | 显式 independent；task0 必须有此位，不能把旧普通 PROBE 的 task 门禁放开 |
| INFO_R 0x86 offset43 bit1（值2） | App 支持 independent，以及可信的 PROBE 忙态 |
| INFO_R offset43 bit0 | 已接受的单点尚未完成/恢复原模型，不能当作空闲 |

独立点版本接受 flags=0（旧描述）、2（独立能力/空闲）、3（独立能力/忙）。后续显示控制增加bit2=显示能力、bit3=显示操作忙，允许6/7/14/15；ABI3仍只允许0，其他组合拒绝。独立单点/其通道恢复必须有能力位，不能用旧 INFO 猜测空闲。任一点/显示操作忙时有界继续 INFO 观察，不自动再次 PROBE，更不 START。原身份、模型、坐标、LOGITS/CLASS、完整注意力 CRC/行和的检查不变；普通任务/历史的注意力解码仍拒绝 task0，只有明确的独立 owner 路径允许它并继续核全部身份字段。显示控制见 `gcs_display_control_v1.md`。

## 互斥与断连

- 一条 UDP owner 同时调度任务、模型、独立点和回读。独立点未结束时拒绝新任务、模型切换和任务控制；协议侧也拒绝在 task0 单点执行中改建任务，不能只靠按钮禁用。
- 即使模型直接从 SD 导入、没有 WBEGIN 历史，已执行 PROBE 的 peer 也被锁定。在线 owner 不可抢占；离线后仅同 session 可显式重接，不能把拔线当作新 session。
- 任务恢复先核同 boot/session/task/ROI/CRC，再核 PONG/STATUS；若 INFO 表示旧点仍忙，等其结束。恢复握手未完时不能用新任务替换它。
- 原模型/独立点通道恢复需要原 channel 和 point 两份原始记录相符。缺少本通道证据仍拒绝；无关坏历史不删除，也不阻止另一完整通道恢复。未回全的点不改称成功，恢复只观察忙态，不重发推理。
- task0 的 INFO 是空任务描述，但 STATUS.wcrc 可以是已激活模型 CRC，并非固定0。单点发送前采集 INFO 之后的同 boot/session/task0 空闲 STATUS，要求其 CRC 为0或真实登记值，推理中保持该空闲身份；不会因此放开任意 CRC。已有同模型任务 CLASS 时，还要逐字核对同坐标结果，原始重放引用同任务证据。
- 任务重接清掉旧 Point 对象，避免重新以独占创建模式打开旧文件。恢复所有已发送独立/任务内 PROBE 序号；新 task 号跳过已分配但未发 START 的本地主机失败任务，防止旧身份混淆。

## 证据和显示

- 独立点保存在 `probe_时间/` 的 session.json、packets.jsonl、summary.json；`board_point.audit_point()`只重放原包，改 summary 不能产生成功值。
- 主机软最大仅把板端 LOGITS 转成概率；注意力只做 Q0.24 缩放。右侧严格核本次 request_id、boot/session/task、场景/模型/坐标，前端再核张量 CRC/行和。HTTP queued 迟于完成消息到达时不能降级它。
- 独立点不进入整景精度/农情分母；当前任务精度只统计其真实 ROW 和固定测试标签交集。清 PC 显示不停止任何任务、不删除上述记录、当前也不暗改 DP。

## 离线复现

```powershell
D:/pytorch/python.exe -X utf8 -B tools/check_gcs_point.py --out build/host/point_checks_<新编号>
node tools/check_gcs_scene.cjs C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright build/host/point_ui_old_<新编号>
node tools/check_gcs_v5_ui.cjs C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright build/host/point_ui_new_<新编号>
```

这些是注入 socket、CPU 统计/标签和驱动替身检查，不代表实板单点、SD 启动、DP 画面或第一轮 A～G/T 全通过。独立点之外，断网期间整景+DP、PC/DP清显示联动、SD独立启动和统一部署仍须继续完成。
