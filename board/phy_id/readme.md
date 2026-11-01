# PHY 识别真板记录

## 2026-10-06 首次实测

- **板型：AXU5EV-E，来源为用户明确确认。** 不是仅凭PHY ID自动判定整板。
- PS GEM3：`0xFF0E0000`；PHY：**KSZ9031**，完整ID **`0x00221622`**；实际MDIO地址 **1**。两次读取一致，0–31中仅地址1响应，程序正常打印END。
- 原始串口：`20261006_first_run/uart_user.txt`（用户粘贴文本转存，UTF-8/LF）；启动日志片段：`ide_launch_excerpt.txt`；源码/ELF/平台/FSBL/配置等15项哈希与来源：`manifest.json`。
- 用户工程：`D:/HSI_AgriEdge/vitis`；平台`test`、App `test_phy`、A53 #0/standalone/UART0；Debug `-Wall -O0 -g3`，ELF 280480 B。App三源码和XSA与仓库a67abde及tt_zu5ev匹配。用户负责Build/Run As，代理未修改工作区。
- IDE日志显示本次启动**实际配置了tt_zu5ev.bit**，再运行配套FSBL和test_phy.elf。诊断程序设计上不依赖PL，不等于这次已验证无PL下载流程。
- FSBL提示 `PMU-FW is not running`；该分支在本地FSBL源码返回SUCCESS，诊断扫描随后确实完成。提示不否定本次PHY ID，但也不证明后续完整PM/DP/外设流程可忽略PMUFW。

## 本次没有证明的事项

没有验证UDP吞吐、以太网链路速率、SD、DP、完整DDR压力/容量、M1/M2整网基线或电源管理；未独立核验芯片完整料号/速度等级和PCB修订。原串口中的 `BOARD_MODEL=UNCONFIRMED` 保留原样，后续用户确认另记在manifest的board_identity。

## 下一步

按 `board/CHECKLIST.md`：先核对PMUFW启动配置和风扇状态，再用户跑C2/M1→C3→D2。网口以实测KSZ9031/地址1为准，不写死旧资料地址3，也不使用JL2121专用配置。手工建平台和App的方法继续见 `board/vitis_sources/README.md`；其板前候选措辞是历史状态，最新结果以本文件和CODEX_CONTEXT为准。
