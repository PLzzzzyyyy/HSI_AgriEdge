# 串行 M3a：源码导入与首轮上板

本包只含 **一个已验证串行 XSA + 一个 test_m3a 源码 App**，不是 Vitis 工作区，也没有可下载 ELF。由用户在 Vitis 2020.2 创建、Build、下载。M1/M2/C3 不重测，SYSMON 暂缓。

## 1. 固定硬件与包内容

- XSA：`tt_m3a_zu5ev/tt_m3a_zu5ev.xsa`。
- SHA256：`9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652`。
- 既有串行硬件：完整 RTL cosim 通过；200 MHz 系统 WNS +0.067 ns。这些不是板上性能。
- App：`tt_m3a_zu5ev/test_m3a/src/`，编译设置见相邻 `settings.json`。
- `manifest.json` 列出每份源/黄金文件及输出文件 SHA256。`source_parent_commit` 是打包时 HEAD，精确源版本以逐文件哈希为准（允许尚未提交的本轮 App）。UART 打印 package_id 和预期 XSA 哈希，**软件不能据此读出/确认实际已编程 bitstream 的哈希**，下载配置仍要人工核对。
- 全部数据嵌入 `m3a_vectors.c` 和原 `tt_data.c`，无需 SD、网络、外部 `.bin` 或绝对 `.incbin` 路径。没有 HLS 实现源码、并行候选、M2 硬件驱动或旧 App main。

复现仅打包（仓库根）：

```powershell
python tools/prepare_m3a_sources.py --out build/board/m3a_sources_new
python tools/test_m3a_sources.py build/board/m3a_sources_new
```

脚本拒绝覆盖已有目录；XSA 或冻结黄金向量哈希不符即拒绝打包。不要运行 HLS/Vivado、不要用当前包含 `TT_M3_OVERLAP` 候选的源码重建/替换此 XSA。候选默认关闭，保持暂缓。

## 2. Vitis 2020.2 操作

1. 新建独立 Platform，例如 `m3a_plat`，选择本包 XSA；CPU `psu_cortexa53_0`、OS `standalone`、64 位 A53 域。BSP stdin/stdout 都选 `psu_uart_0`。不加 lwIP/xilffs。**不要 Update 旧 M2 平台，也不要修改 test_m2/test_c3**。
2. 用户 Build Platform。XSA 的 HLS 驱动 Makefile 已修正，不必再修包或重导硬件。
3. New Application `test_m3a`，选新平台 A53 域，模板 **Empty Application (C++)**。将本包 `src/` 的全部文件导入新 App 的 `src/`，不要导成 `src/src`，不要合并其他 App。保留 Vitis 自动生成的 `lscript.ld`。
4. **GCC 与 G++ 两处**都设 `-O2 -mcpu=cortex-a53 -ffp-contract=off -ffunction-sections -fdata-sections -Wall -Wextra -Werror`。GCC 加 `-std=c11`，G++ 加 `-std=c++14`。不用 `-ffast-math`。Symbols 无需添加；不加 `TT_HW_RUNTIME_SWITCH`/`TT_ENG_SELFCHECK`/任何 HLS 宏。核对完整实际命令，不只看 Release/Debug 名称。
5. G++ Linker 保留默认 BSP 路径和 xil/gcc/c/stdc++ 等库，额外 Libraries 加 **`m`**；Miscellaneous 加 `-Wl,--gc-sections`。`tt_net.cpp` 复用原 `tt_embed`，`tt_hw_sim.cpp` 只补齐该文件链接依赖，未执行 PS 整网推理，也不访问 PL；不可改为 M2 的 `tt_hw_engine.cpp`。
6. 链接脚本：代码、只读黄金数据、`.data/.bss`、heap/stack 全放低 DDR `psu_ddr_0_MEM_0`（<4 GiB）；建议 stack **0x10000**、heap **0x10000**，检查链接 map 的静态 buffer 地址。驱动会拒绝未对齐或超出低 4 GiB 的 DMA 缓冲；默认静态数据与 buffer 约数 MB，不放 OCM。
7. 用户 Build App，保存完整 Build Console。此次交付检查不代替真实平台的最终链接。确认没有 error/warning、只有一个 main，ELF 为本次 `test_m3a`。
8. 串口 115200/8N1，文本模式并保存完整日志。Run As / Launch on Hardware：选 **A53 #0、当前 ELF、匹配当前 XSA 的 PS 初始化/FSBL**，勾 **Program FPGA**，确认 bitstream 来自新 `m3a_plat`。执行系统复位/PS 初始化，若停在 main 则 Resume。不复用旧 M2 bit/ELF。
9. App 自动执行一次，无菜单、不需按键。完成打印 `M3A_APP_END PASS/FAIL` 后永久停驻。**失败不要仅 Resume/retry；超时后 PL DMA 可能仍在运行，重新配置 PL 并重启 App。** 不写 Flash/SD/BOOT.bin。

## 3. 验收输出

完整保存启动/FSBL（若有）到 `HALTED`，连同编译命令。通过至少包括：

- `M3A_SERIAL_BASELINE v1`、正确 package_id / XSA、`PS_backend=NEON`、timer_hz、runs=10、batch=16。
- `LOAD_W PASS bytes=480576`：完整权重包只装载一次；返回契约 version=3、bits=18、frac=12。
- PS embed 与黄金 A 全部 15876 个 int16 一致；A/B/A 的 32 槽 LOGITS、打包 CLASS/置信度与奇数批尾部逐位一致。
- `PASS DUMP layer=0` 到 `11`；**实际 DUMP 第4层**转回 int16（先检查范围）后续算第5～11层 FEAT/CLASS 一致。18 位 FEAT 不能无条件截成 int16。
- `M3A_CORRECTNESS PASS mismatches=0`。
- 默认 **12 条 PERF**：n=1/3/16 × LOGITS/CLASS × 两个 scope，每组一次不计时 warmup + 10 次计时。每次结果都验证；共 120 条 SAMPLE 原始 ticks。
- `M3A_BASELINE PASS mismatches=0` 与 `M3A_APP_END PASS`。出现 FAIL 不报该轮性能通过，不以“有串口/有输出”验收。

黄金 A/B 来自同一 LongKou 像素的不同预 embed 块，B 只用来检查批次隔离，不代表本次上板执行了 M3b 前端。性能的**两个 scope 均重复完全相同的 A patch**，避免输入不同影响差分；这不是整景准确率或真实逐像素持续吞吐验证。

## 4. 计时口径（后续 A/B 必须保持一致）

| 输出 | 包含 | 不包含 |
|---|---|---|
| `LOAD_W` | 首次完整权重 cache clean、寄存器、等待 | 初始化、后续每 patch 计算 |
| `PREEMBED_FULL` | 预 embed 输入的 clean、输出 flush、寄存器配置、FULL、poll、输出 invalidate | PS embed、输入复制/打包、首次权重、DUMP、比对、UART |
| `PS_EMBED_PLUS_FULL` | 上一行全部 + 每个预处理 CHW patch 的原 `tt_embed` | 取窗、patch 归一化、读盘/网络/地面站、输入准备、权重、比对、UART |

这是 **PS 观察的同步调用延迟**，不是 PL 纯计算拍数。批总耗时 `mean_batch_ms`；单 patch 摊销 `ms_per_patch=总 ticks/freq/批总 patch 数`；`patches_per_s` 是**测量窗口内的计算服务率**，不包括窗口外准备/验证/打印，也不代表持续场景帧率。保留 warm-cache、重复同一 patch 条件。n=1 才是单次延迟；不要把 n=16 的摊销当单次响应。

不能把 `PS_EMBED_PLUS_FULL` 叫“含 PS 取窗的整景端到端”。它与原 M2 `tt_forward` 都从预处理 CHW patch 开始，适合后续注明条件的整网比较；M2/M3a 输出定点与执行路径不同，不能要求跨架构 logits 逐位相同。旧 M2 已验收，不为本轮重测。M2→M3a 同时迁移 attention/residual/head 并减少层间交互，不能把总收益全归因于“去交互”。正常 FULL 仍有输入、控制、最终输出与首次权重交互；DUMP 主动增加中间数据回传。并行收益要等串行真板基线后另做相同口径对照。

**当前没有 M3a 真板数值、延迟、吞吐结论。** 主机控制/模型日志及 A53 编译检查不能充作板上输出。
