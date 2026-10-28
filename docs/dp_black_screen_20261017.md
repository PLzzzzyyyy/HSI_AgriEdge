# 2026-10-17 DP 黑屏诊断与修复

当前状态：根因已由启动记录、实际 ELF 反汇编及本地厂商驱动源码确认；修复正在构建，
尚未完成修复版板测与显示器画面确认。

## 原始证据

- 原始以太网启动记录：
  `build/host/gcs_network_boot/network_start_20261017_221844_923362/board_log/board_log.txt`。
- 同目录 `discovery.json` 保存 `boot_id=228ce102`、`generation=26`、`dp_rc=1`；
  模型扫描成功，登记 14 个权重包，网络进入 READY。
- 板端原句：`S2C DP init_rc=1 1920x1080; picture requires user check; no SD assets`。

网页服务启动、网络 READY、模型扫描成功都不证明 DP 初始化成功。该应用在启动阶段
就应显示就绪画面，无须先执行推理任务。

## 确切根因

迁移到 Vitis 2026.1 SDT BSP 后，`XDpPsu_LookupConfig`、`XDpDma_LookupConfig`
的参数语义从旧 DeviceId 改为物理基址，驱动逐项比较 `ConfigTable[].BaseAddr`。
旧兼容宏仍把 `XPAR_PSU_DP_DEVICE_ID` 与 `XPAR_XDPDMA_0_DEVICE_ID` 定义为 0，
原应用却继续将它们传给 SDT 查询函数。

本次实际 ELF 在 `0x47b30`、`0x47b3c` 两处查询前传入 0，配置表中的有效基址分别为
DP `0xFD4A0000`、DPDMA `0xFD4C0000`，因此两次查询返回空指针。
`roi_display.cpp::init_subsystem()` 遇空指针返回 false，`display_init()` 返回 1。
失败发生在 HPD 等待和链路训练之前，本次已有软件根因。

厂商源码依据（本机 `D:/AMDDesignTools/2026.1/Vitis/data/embeddedsw/XilinxProcessorIPLib/drivers/`）：

- `dppsu_v1_8/src/xdppsu_sinit.c:78`：SDT 查询接收 BaseAddress，按 BaseAddr 匹配。
- `dpdma_v1_7/src/xdpdma_sinit.c:67`：相同参数语义。
- `dppsu_v1_8/examples/xdppsu_common_example.h:45`：SDT 使用 `XPAR_XDPPSU_0_BASEADDR`。

## 修复范围与验证

- `src/ps/s2c_roi_app/roi_display.cpp`：SDT 下改用 `XPAR_XDPPSU_0_BASEADDR` 与
  `XPAR_XDPDMA_0_BASEADDR`，旧工具链保留 DeviceId 分支；同时保留 XAVBuf 两参适配。
- `tools/vitis_py/build_abi4_app.py`：对冻结源码的暂存副本补齐上述两处查询适配，
  不修改冻结发布包；转换支持幂等，并拒绝缺失/重复的已知调用形状。
- `tools/vitis_py/tt_vitis_client.py` 与迁移文档：更正“SDT 配置表数组下标即 DeviceId”
  的错误说明；不改变其他外设宏。
- 离线转换验证通过：完整既有冻结 `roi_display.cpp` 仅改变指定调用、重复转换不再改变，
  已有 XAVBuf 适配兼容，缺失/重复调用拒绝，Python 语法检查通过。
- 正式重建成功：平台 `D:/FPGA.GAME/dpfix`；应用编译 `BUILD PASS`，应用源码零警告。
- 修复 ELF：`firmware/gcs_r1_abi4_app_dpfix.elf`，SHA256 `82fe33ebda32a5ef35e55e2c3c9f31fbc5fd1859889e5a90475a99837cd47b8c`。
  原 `gcs_r1_abi4_app.elf` 保留；启动脚本优先选择修复版。
- 已核对新 ELF 反汇编：`0x47b30` / `0x47b3c` 分别传入 `0xFD4A0000` / `0xFD4C0000`。
- 已下载并读取真实板端启动记录：boot `228ce104`，generation `28`，
  **`DP init_rc=0`**，`READY`，SD 登记 14 项、扫描成功。
  证据：`build/host/gcs_network_boot/network_start_20261017_223211_178353/board_log/board_log.txt`。
- 用户使用 DP 转 HDMI，已明确回复“已经有画面”，**实际显示恢复已由用户确认**；无需因未知有源属性更换现用转接器。
- 只读寄存器交叉核验：`FD4A0080=1`（输出使能）、`FD4A0084=1`（主视频流使能），`FD4A0280=0x1f`。

板端 DP 初始化、视频输出使能及用户目视确认均已通过。原失败记录保留；
不能用网页可访问或网络 READY 代替显示器验证。
