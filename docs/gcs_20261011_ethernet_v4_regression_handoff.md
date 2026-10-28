# 2026-10-11 20:32 以太网回归交接：3 项门禁未闭环，v4 未准备

## 恢复状态

- 本轮源码/测试/证据本地提交 **`6644af3`**；随后交接记录提交以实际 HEAD 为准，不回退，均未 push。此前 `cb3f9b6`、`6e1da2a` 保留。
- 已修：终态任务取证与模型事务串行化；多条延后模型回执关闭时明确失败落盘；可取消丢页回读；以太网上传/START/任务恢复与旧 UART 守卫隔离，旧兼容故障拒绝仍在。
- 59 定向 Python + BoardLog C++ PASS。扩展完整入口 **93/96 顶层命令 PASS、3 FAIL，整体 FAIL**；当前用户 BSP 14 A53 syntax-only、86 AST、17 JS 语法和96浏览器检查PASS；模型/runtime/pipe interop子入口通过。不是完整发布、App Build或实机验收。
- 用户在本轮要求交接，已等在途检查结束；没有遗留测试任务，原服务继续保留。**v4 未生成/冻结，源码默认 BUNDLE 仍 v3。**

## 下一轮直接做

1. 先只读核实际 git HEAD/status/index 和 35444/8765；按 CLAUDE.md 读当前快照及本页、`report/gcs_roi/20261011_ethernet_v4_regression/review.md`。不重读整份会话导出，不混入排除项。
2. 针对保留的三项失败逐一修复/验证：
   - `sim/host/test_gcs_probe.py:19` 使用旧 `from test_gcs_roi`，在新 runner 的包式 unittest 导入失败。修正确的双入口/包导入，不删探查检查。
   - `sim/host/test_gcs_release.py:20` 仍固定 34；当前清单 35，新增的是 `roi_board_log.h`。核全量清单后改精确数量和必要文件断言，不放宽条件。
   - `sim/host/test_gcs_roi_prefix.cpp` 缺 `tt_m3a_output_bytes` 与 `tt_m3a_run` 链接替身。按当前签名补有约束夹具，不能放过非预期驱动调用或用真实设备路径“修绿”。其余 runtime 套件已通过，不能据此跳过前缀检查。
3. 针对修复先回归，再用**全新输出目录**运行 `tools/test_gcs_round1.py --group all`；保留本轮所有 RED/FAIL，不覆写 `full_initial`。实际硬件/IP/XSA、源码/host assets、本地数据清单与发布布局仍须核清，不能拿合成门禁代替真实输入绑定。
4. 完整门禁清零后，才显式在 `build/host/gcs_r1_abi4_release_v4` 准备源码包，**绝不默认 prepare 到 v3**。准备前核清候选 bundle 的默认/选择方式，避免冻结后再改受绑定 host assets。当前旧 `--refresh-from` 工具只允许 validator/绑定头变化，并非 v3→v4 通用源码升级许可。
5. 源码同步、用户 Build、服务切换各自取得当次明确授权；不重建既有平台/HLS/XSA，不改批准 ELF。全部 A～G/T 实机仍待，全过才第二轮。

## 现场与证据

- 原服务 `PID35444`，`D:/pytorch/python.exe -X utf8 -u -B tools/gcs_roi.py serve --port 8765`，工作目录 `D:/HSI_AgriEdge`。20:26/收尾只读确认127.0.0.1:8765，source active/authorized=false，UART released/TX0；无本轮临时回归进程。不要重复启动或按旧记录擅停。
- 服务保存的旧 RX 还显示 `boot=228ce0ea/generation=2`；此前 `228ce0e9/generation=1` 为历史已用记录。不是本轮新的板卡观测，**journal 已用，绝不初始化回退或手填身份**。
- 182 个原 v3 包/用户 App 源与配置/批准 ELF 文件 SHA 未变；本轮没有设备/SD/串口操作，没有源码同步、Build或服务切换。Packages、第三方目录、旧ELF、Vitis/Vivado生成树、历史Build观察、会话导出保持原位，不暂存或删除。
- 证据 `report/gcs_roi/20261011_ethernet_v4_regression/{review.md,closing_summary.json,manifest.json,receipts.zip,runtime_state.json}`；原工作输出 `build/host/gcs_ethernet_v4_regression_01`。ZIP 331 成员已按CRC与逐成员SHA核验；不含可替代用户Build的ELF或新发布包。

```powershell
D:/pytorch/python.exe -X utf8 -B tools/test_gcs_round1.py --out build/host/gcs_ethernet_v4_resume_02 --group all
```

不使用 goal/token 预算；简短汇报、直接推进上述剩余项，不扩大范围。
