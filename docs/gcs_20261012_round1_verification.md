# 第一轮修复独立复验（2026-10-12）

> 后续并行进度（09:08 部署记录）：v7 服务已获许可切换到 PID 13872 / 127.0.0.1:8765，旧20352已退出；本会话只读核对原回执并被动核端口，未执行切换。**3716 现已是实际服务树，不再在其中热改运行资产。** 下一由部署会话指导用户 Ctrl+F5 后下载/运行已批准 ELF，不再同步/Build；本页 09:02 观察保留为历史。详 `docs/gcs_20261012_v7_sync_handoff.md` / `parallel_service_readonly.json`。

**当前 v7 候选的完整离线门禁 119/119 PASS；不是第一轮实机验收完成。** 本会话只接手验证，不接管并行会话的同步、Build 或部署。详细证据见 [复验报告](../report/gcs_roi/20261012_round1_verification/review.md)。

## 已核实

- 测试工作树：`C:/Users/86187/.codex/worktrees/3716/HSI_AgriEdge`，HEAD `b4a10ce` 加当时未提交候选；本会话未修改产品源码。
- 08:48:31–08:53:32：119 项顶层命令、46 个 Python 模块 / 322 个执行用例、96 项原浏览器检查 + 48 项修复专项检查全部通过，无跳过模块。另含 C++ 协议/画布/管道互操作和 15 个实际 BSP A53 语法检查；数字有包含关系，不相加冒充独立用例总数。
- 204 个测试输入源码和全部顶层日志 SHA256 无漂移；冻结 v7 manifest 与候选代码差异在测试期间不变。合成页面、缺省飞行元数据和回放数据不作为真实板卡画面证明。
- 冻结包：隔离树 `build/host/gcs_r1_abi4_release_v7`，37 份 App 源、110 个配套资产。
- release：`45dc34511ef5276a9c92c87cf99a6f36267840b33a81c51df31f69a402ef2d44`。
- 原 XSA：`bc7dfb43856d2ce2fddbd727aedc91daa091cec7ac7b8f64f6ea7773f8a2d380`；本会话没有重跑 HLS / Vivado / 平台。

## 并行进度：不要重复同步或 Build

测试期间只读发现另一流程已完成 v7 同步（08:51）、用户 App Build（约 08:53）和 ELF 登记（08:54）。08:57 对已有 `audited_elf` 门禁及同步前备份的哈希复核 PASS：15 条编译记录、12 个缓冲区、16 个必要符号。

- ELF：`D:/HSI_AgriEdge/build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_app/Debug/gcs_r1_abi4_app.elf`。
- ELF SHA256：`99c2c2cb9a2d0ae0f1e877ebbc69415b1b6966f30e08430fadbcee2f87be7194`，3,225,336 字节。
- 原回执：隔离树 `build/host/gcs_round1_takeover_01/{source_sync_v7_01,user_build_v7_observed_01,elf_review_v7_01}`。
- 本会话没有执行同步、Build 或登记，不根据旧快照回退 App。09:02 被动观察原服务仍为 PID 20352 / 127.0.0.1:8765；之后现场状态以负责部署会话的新回执为准。

## 下一步实机顺序

1. **由当前负责部署的会话**核对最新服务状态、取得当次服务窗口及设备操作许可；两个会话不能同时切服务、占用 UDP 或操作同一 App。
2. 用户下载同一获批准 ELF，核对本次真实 BUILD / boot / session / release；不重用旧 boot claim，不覆盖或回退已用 SD journal。
3. 先验小 ROI（如 5×3）的坐标、CLASS/seen、CRC、PC 和 DP；再验暂停→恢复→停止→同连接第二个 ROI，以及独立单点、刷新、农情统计、PC/DP 清显示与恢复。
4. 拔插网线、复位、断电或启动方式切换由用户明确安排；用真实回执和 DP 目视证明断网仍推理、重连恢复原任务。离线模拟不替代这些实机证据。
5. SD 独立冷启动另验。现有 LongKou/v2 mission 只是本地 opt-in 配置；需匹配新 ELF 的 BOOT 材料、保留已用 journal，不能把 JTAG 运行或启动引脚值当作 SD 冷启动成功。
6. 继续 [完整 A～G/T 矩阵](gcs_20261011_acceptance_matrix.md)，保留三景、边界、注意力、模型上传/切换/训练闭环、持久化及计时等未验范围；不提前关闭第一轮或进入第二轮。

## 复现入口（仅离线，不重建平台 / App）

在上述隔离工作树运行，`--out` 必须换成不存在的新目录：

```powershell
& 'D:/pytorch/python.exe' -X utf8 -u -B tools/test_gcs_round1.py --group all --bsp 'D:/HSI_AgriEdge/build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_plat/export/gcs_r1_abi4_plat/sw/gcs_r1_abi4_plat/standalone_domain/bspinclude/include' --out 'build/host/gcs_round1_verification_repeat_01/all'
```

本次原始输出：隔离树 `build/host/gcs_round1_verification_20261012_01`。便携证据、源码哈希和并行状态说明在 `report/gcs_roi/20261012_round1_verification/`。旧 118 项回执不包含后来新增的发布同步工具测试，不能直接代替本次最终 119 项结果。
