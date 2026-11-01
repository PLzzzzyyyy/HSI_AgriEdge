# S2a：空闲态 v1 子集（未接入 App）

- `idle_protocol.{h,cpp}`：不依赖 BSP 的小端字节核心；只收精确 16 B v1 PING，产出 24 B PONG / 92 B STATUS。没有推理、DMA、任务、权重或结果缓存引用。
- `idle_lwip.{h,cpp}`：standalone/raw IPv4 接入层。源 IP/端口回包；使用 `pbuf_copy_partial` 处理分链输入；检查分配、拷贝和发送结果，不重试循环。构造函数无副作用。
- 本轮没有调用 `open()`、`poll()`、`close()`，没有网络模拟或服务。实际 BSP 仅用于 A53 `-fsyntax-only`，不是 App Build/链接。

## 后续接入契约（须另授权，不是本轮执行命令）

未来独立 App 负责 lwIP/GEM/netif/GIC、IP/MAC、定时器和 `xemacif_input()`；同一主循环独占对象与回调，之后调用 `poll()`。`open()` 默认绑定 5010；成功后同对象不能重新 open，`close()` 是终止性关闭。失败的首次 bind 可以重试；不替换已有 PCB/netif，不重置用户中断配置。

App 须提供每次上电的新 `boot_id`，本模块不伪造随机身份；真实生成来源尚待接入时核实。PHY、温度、功耗不在此层读取。空闲计时由 `XTime_GetTime()` 的完整 64 位值换算，线上只写低32位。不得把这个 poll 直接拼到同步 ROI 前后后便声称运行中仍可服务网络。

## 明确的子集限制

- 只接受 v1 PING。v0、START/STOP/PAUSE/RESUME/INFO/PROBE/ROWREQ/权重及其他类型一律丢弃并计 `rx_bad`，不回成功 ACK；没有执行或排队。**这不是完整 v1 接收器/业务 ACK 实现**，不承诺通用 v0 接收兼容。未改原 `docs/protocol.md` 或 `gcs/`。
- STATUS `task/done/total/state/wcrc/front_row=0` 表示本对象从未接任务/模型，不携带历史15像素结果。`ms_per_px/temp_c/power_w` 均为 IEEE754 qNaN `0x7fc00000`（未测）。原协议无有效位，此为 S2a 的明确表示约定，地面站后续必须将非有限值转成未测/null，不能直接当严格 JSON 数值或0。
- `link.bit0` 为本模块 PING 活性；`bit1=0` 仅表示**未提供PHY观测**，不能据此断言网线断开。`tx_retx/rx_dup=0` 表示没有实现 ROW/可执行命令；其余计数来自本对象处理，非 GEM 全流量计数。
- 首次合法 PING 前不发包。之后在线 STATUS 最短间隔250ms、离线1s；调度必须由主循环及时驱动，不承诺实际时延。1s未见合法 PING 判离线，断线累计从阈值开始；换源/会话或重连清 RX 序号基准，TX序号和累计计数不清。没有鉴权，不把 session 当安全认证。
- `tx_pkts/tx_bytes` 只记实际 `udp_sendto==ERR_OK`；STATUS包含发送前快照，不包含自身。失败只计 `tx_fail`，不认作接收端已收到。RX序号缺口仅对该空闲PING子集有意义；不冒称完整v1链路六指标。

验证与证据、下一轮授权入口：[report/system_s2a_idle.md](../../../report/system_s2a_idle.md)。
