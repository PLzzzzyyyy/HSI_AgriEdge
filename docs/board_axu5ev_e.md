# AXU5EV-E 板卡速查（对照 7020 领航者）

> **2026-10-06 真板更新：用户明确确认 AXU5EV-E。** PS/GEM3的PHY实测为KSZ9031，ID `0x00221622`，**地址1**（两次一致、32地址仅1处响应），不是此前资料里的3。板型来源为用户确认，PHY/地址来源为用户串口；不由其中一项推定另一项。原始证据见 `board/phy_id/20261006_first_run/`。完整芯片料号/PCB修订未独立核实，仍不认定是手册笔误。手工导入说明见 `board/vitis_sources/README.md`。

来源：`docs/vendor/AXU5EV-E开发板用户手册/full.md`（MinerU 转换，厂商手册版本见文档头）与 7020 工程 `build/vivado/ps7_cfg.tcl`。目的：建 ZU5EV 的 Vivado 平台时，PS 外设与 PL 引脚一次配对，不再靠猜。
最终以厂商 factory 工程导出的 `zynq_ultra_ps_e` CONFIG 为准（PLAN A3），本文用来核对。

## 1. 芯片与核心板

| 项 | 7020 领航者 | AXU5EV-E（核心板 ACU5EV） |
|---|---|---|
| 器件 | xc7z020clg400-2 | 手册 **xczu5ev-sfvc784-2-i**；出厂工程 **xazu5ev-sfvc784-1-i**（汽车级 XA、速度 -1）。构建脚本默认跟出厂工程，上板看芯片丝印后定 |
| PS CPU | 2×A9 | 4×A53 + 2×R5，裸机跑 `psu_cortexa53_0` |
| PS DDR | DDR3 MT41J256M16 RE-125，32 bit 1 GB | **DDR4 ×4 片，64 bit 4 GB**，BANK504。出厂工程 PSU：每片 8192 Mbit ×16、Components、DDR4_2400P、行地址 16、BG 1、无 ECC、CL 16（§6） |
| PL DDR | 无 | DDR4 ×1 片，16 bit 1 GB，BANK64（本项目暂不用） |
| PS 参考时钟 | 33.333 MHz | 33.333 MHz（R16） |
| PL 时钟 | 50 MHz 单端 | **200 MHz 差分** PL_CLK0_P AE5 / N AF5（BANK64，是 PL DDR4 参考钟；用户逻辑主时钟仍走 PS 的 PL_CLK0 输出即可） |
| QSPI | MIO1..6 | 256 Mb MT25QU256，**MIO0..5 单片 x4**（SCLK MIO0，SS MIO5） |
| eMMC | 无 | 8 GB，**SD0 = MIO13..23**（8 bit，RSTN MIO23） |
| 启动模式 | 拨码 | SW1：0000 JTAG / 0010 QSPI / 0101 SD / 0110 eMMC |

## 2. PS 外设 → MIO（Vivado PSU 配置要填的）

| 外设 | 7020 | AXU5EV-E | 备注 |
|---|---|---|---|
| **调试串口** | UART0 MIO14/15 | **UART0 MIO42 (RX) / MIO43 (TX)** | CP2102，Mini-USB；驱动 `xuartps` 不变，波特率沿用 115200 |
| **SD 卡** | SD0 MIO40..45，CD MIO10 | **SD1 MIO46..51，CD MIO45** | 手册 SD_CLK 写 "I21"，J32 表实为 L21。经 TXS02612 电平转换，1.8 V 侧 |
| 千兆网 | 7020 TT 工程未开 | **GEM3 MIO64..75，MDIO MIO76/77** | PHY KSZ9031RNX，PHY 地址 011（=3）。lwIP 移植时 PHY 地址与 7020 YOLO 参考不同 |
| USB | 无 | USB0 MIO52..63，复位 MIO31 | 不用 |
| CAN | 无 | CAN0 MIO32/33，CAN1 MIO38/39 | 不用 |
| I2C | 无 | I2C1 MIO24/25 | EEPROM 24LC04 + LM75 温度，可作功耗/温度展示 |
| DP | 无 | GT lane2/3，AUX MIO27..30 | PLAN §5.2a 机载监视器 |
| PS 按键 | – | **MIO26**，低有效 | GPIO |
| PS LED | – | **MIO40**，高亮 | GPIO |
| PL 侧 AXI | GP0 + HP0/HP1，64 bit | **HPC0/HPC1 或 HP0..3**，可到 128 bit | pitfalls 已记：A53 cache API 语义要重验，优先评估 HPC |

## 3. PL 引脚（XDC 用得到的）

| 信号 | 引脚 | Bank / 电平 | 备注 |
|---|---|---|---|
| PL_CLK0_P / N | AE5 / AF5 | 64，1.2 V | 200 MHz 差分 |
| PL_LED1 | AE12 | 43，3.3 V | 高亮 |
| PL_KEY1 | AF12 | 43，3.3 V | 低有效 |
| PL_UART_TX / RX | AH12 / AH11 | 43，3.3 V | 第二个 CP2102，可作 PL 侧 debug 串口 |
| 风扇控制 | AA11 | 43，3.3 V | 高=转。裸机不控则风扇不转，长时间跑要拉高 |
| PL 以太网 PHY2 | BANK66，1.8 V | 见手册 §三(五) | 不用 |
| MIPI 摄像头 | BANK65 差分 + BANK43 控制 | 1.2 V / 3.3 V | 不用 |
| 40 针扩展 J45 / J46 | BANK45/46（1.8 V？） / BANK43/44 3.3 V | | 功率计或指示模块可接 |

Bank 电平：BANK43～46 为 3.3 V；BANK65 由底板 LDO 供 1.2 V，BANK66 供 1.8 V，两者上限 1.8 V。

## 4. AXU5EV-E 与 AXU5EVB-E 的区别（两份手册逐行比对，引脚表完全一致）

| 项 | AXU5EV-E | AXU5EVB-E | 对我们的影响 |
|---|---|---|---|
| PS 网口 PHY | KSZ9031RNX，旧资料地址3；**本项目实物实测地址1**，MDIO MIO76/77 | JL2121-N040I（景略），手册PHY地址1，TX/RX时钟各2ns延时 | 地址不能用来单独判E/B；本项目按实测KSZ9031/地址1处理，不能套JL2121配置 |
| eMMC | 8 GB | 32 GB | 不用 eMMC，无影响 |
| 风扇控制 AA11 | **高电平转** | **低电平转** | 极性相反。上板先试一次，别写死 |
| 底板 DC/DC | TPS54620 + MP1482 | ETA8156 + ETA1471 | 无影响 |
| 40 针扩展口丝印 | J45 / J46 | J16 / J15 | 引脚相同，只是丝印 |

MIO 分配、PL 引脚、bank 电平、启动拨码、DP、SD、串口两板一致，第 2、3 节两板通用。

**历史判断已降为待核实（2026-10-06）**：09-22 用户判断应是 AXU5EVB-E；09-23 根据照片的 J45/J46 将其判断为 E，证据不足，不能进一步据此确认 PHY/地址/风扇极性。现有 XSA 沿用 E 假设（`FAN_LEVEL 1`）及出厂工程 -1 器件设置；这不证明实物版本。另更正：Vitis 2020.2 原始 lwIP 的 PHY 自动识别不能笼统称为已适配 KSZ9031，C3 现有 BSP 固定 1000Mbps；详见 `tools/build_periph_platform.tcl` 和 `board/periph/README.md`。若确认 JL/B 型，需另做网口和风扇适配。

## 5. 对 7020 代码的影响清单

- `ps7_cfg.tcl` 不能复用，改为 `psu_cfg.tcl`，从 factory 工程 `write_bd_tcl` 截 `zynq_ultra_ps_e_0` 段。
- `build_tt_soc.tcl`：part 改 `xczu5ev-sfvc784-2-i`，PS IP 换 `zynq_ultra_ps_e`，端口名 `M_AXI_HPM0_FPD` / `S_AXI_HPC0_FPD`，时钟 `pl_clk0`。DDR/FIXED_IO 外部端口不再需要。
- PS 代码：串口驱动名不变但实例基址由 XSA 决定；SD 文件系统从 SD0 变 SD1，Vitis 的 xilffs 要选 `sdps` 实例 1；`XTime_GetTime` 在 A53 上以 `COUNTS_PER_SECOND` 换算，不再是 CPU 频率/2。
- XSCT 脚本：`*A9*#0` 改 `*A53*#0`，多一步 `psu_init` 与 PMU 固件。
- lwIP：**实物PHY地址1、KSZ9031、GEM3**（2026-10-06串口实测）；`src/ps/reference/net_udp.cpp` 里 `XPAR_XEMACPS_0_BASEADDR` 要看 XSA 里 GEM3 映射成哪个实例号。C3现有地址扫描覆盖1，后续仍需网口实测。

## 6. 出厂工程 factory_vivado 核对结果（2026-09-23，factory_file.zip 下完后）

工程 `board_test.xpr`，Vivado **2020.1**，器件 xazu5ev-sfvc784-1-i，块设计 `design_1.bd`（zynq_ultra_ps_e 3.3）。PSU 全部 1013 项 CONFIG 由 `tools/extract_psu_cfg.py` 抽成 `build/vivado/psu_cfg_factory.tcl`，`build/vivado/build_zu5ev.tcl` 原样 source 再做少量覆盖。与第 2 节手册对照，MIO 分配全部一致：

| 项 | 出厂 PSU 值 | 本项目 |
|---|---|---|
| UART0 | MIO 42..43 | 沿用，调试串口 |
| UART1 | EMIO（出厂接 PL 串口 AH12/AH11） | 关掉 |
| SD0（eMMC） | MIO 13..22 | 保留不用 |
| SD1（SD 卡） | MIO 46..51，CD MIO 45 | 沿用，xilffs 选实例 1 |
| GEM3 | MIO 64..75，MDIO 76..77 | 沿用，lwIP |
| QSPI | x4，MIO 0..5 | 保留 |
| USB0 + USB3.0 | MIO 52..63 | 保留不用 |
| DP | Dual Higher（lane 2/3），参考钟 27 MHz，AUX MIO 27..30 | 保留，§5.2a 监视器 |
| I2C1 / CAN1 / TTC0 | MIO 24..25 / 32..33 / 使能 | 保留 |
| PCIe | 使能 | 保留（GT 与 psu_init 一致，不动） |
| GPIO1 MIO | 使能（PS KEY MIO26、LED MIO40） | 沿用 |
| GPIO EMIO | 95 位（接 J45/J46 扩展口） | 关掉 |
| PL0 / PL1 时钟 | 150 / 200 MHz | PL0 改 100 MHz（v1.4 IP 时钟；E5 三档再调）|
| M_AXI | GP2 = HPM0_LPD，32 位 | 沿用，接 IP CTRL |
| S_AXI | GP2/GP3 = HP0/HP1_FPD，128 位 | 改 64 位，FM→HP0、WT→HP1；HPC 在 C4 试 |
| 中断 | IRQ0、IRQ1 使能 | 沿用 |
| PL 引脚 | 风扇 AA11、LED AE12、KEY AF12、PL 串口 AH12/AH11、200 MHz 差分钟 AE5/AF5（DIFF_SSTL12，出厂给 PL DDR4 用） | 与第 3 节一致；风扇由 `FAN_LEVEL` 常量驱动 |

DDR4 时序（出厂）：2400P，CL 16、tRCD 16、tRP 16，DM 无 DBI，无奇偶校验。`top.xsa` 里 `psu_init.c` 就是这套参数生成的，Vivado 2020.2 用同一 CONFIG 重新生成即可。
