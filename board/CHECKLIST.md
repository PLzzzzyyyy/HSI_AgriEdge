# 上板日检查清单（C2 → C3 → D2）

更新：2026-09-29。所有板上结果均待用户实测；本文件中的 PASS 字样是验收要求，不是已完成结果。

## 0. 准备、平台配对与证据

> **2026-10-06 真板结果（覆盖下面较早的待确认状态）**：用户已确认AXU5EV-E，PHY实测KSZ9031 / ID 0022:1622 / 地址1；原始记录见 [PHY首测](phy_id/README.md)。用户已在根目录vitis创建test平台/test_phy应用并完成识别。此次启动实际配置了PL且FSBL提示PMU-FW未运行；后续先核对PMUFW加载流程和风扇，不能把PHY读取成功当作以下M1/C3/M2项目通过。

> **2026-10-06 前置核对**：实物 E/B 重新待确认，不能只看 J45/J46。先按 [源码导入与 PHY 识别说明](vitis_sources/README.md) 自己在 Vitis 建 PHY App，取得完整 ID 并结合 PCB/芯片丝印确认。PHY 不需要 PL bitstream；后续 M1/C3/M2 仍要匹配各自 bitstream。若是 JL/B 候选，先复核适配和风扇极性，不直接跑旧 C3 的 u/a。下列既有检查项保留，不代表已经上板通过。

- [ ] AXU5EV-E、供电、JTAG、PS_UART、千兆网线、FAT32 SD 卡、DP 显示器就绪。先断电接线；SW1 按板卡手册拨 JTAG。
- [ ] 串口 115200 / 8N1，关闭 HEX 发送，开启原始文本保存。
- [ ] 每轮单独建 `board/periph/<日期时间>/`，保存串口、PC JSON、DP/LED 照片，记录板卡、XSA/ELF SHA256、工具版本、网卡/显示器型号。
- [ ] C2 使用 M1 的 `tt_zu5ev.xsa` + M1 应用；C3 使用同一个 XSA + **periph_plat** BSP + 外设应用；D2 改用 **tt_m2_zu5ev.xsa** + M2 应用。禁止交叉配对。
- [ ] 切换应用时停止旧调试，使用对应平台重新初始化 PS/下载对应 bitstream，不只替换 ELF 后沿用未知外设状态。
- [ ] Vitis 2020.2，psu_cortexa53_0，standalone；用户在 Vitis Build 和下载。本清单不执行下载。

### 0.1 不上电文件核对（2026-09-29）

已复核 09-28 的配对清单 `build/board/preflight_20260928.json`（SHA256 `5e3992eb75b0ff51eff9fcce08a17d17fc549c7bf5d40f8ac6b02d9fd3791e13`），三套平台及四份下载 ELF 均与各自工作区原件匹配；平台 XSA、bitstream、psu_init、BSP/驱动及链接脚本通过文件级核对。没有重新构建或连接板卡。

| 用途 | 已核对工作区 / 平台 | XSA | 下载 ELF（路径相对仓库根） | ELF SHA256 前16位 |
|---|---|---|---|---|
| C2 / M1 | `build/vivado/chk_zu5ev` / `chk_plat` | `build/vivado/tt_zu5ev.xsa` | `board/m1/tt_bench_zu5ev.elf` | `edb5cf6f55b63337` |
| C3 | `build/board/periph_formal_20260928` / `periph_plat` | `build/vivado/tt_zu5ev.xsa` | `board/periph/periph_zu5ev.elf` | `7b7d2c1ac47bebea` |
| D2 / M2 正式 | `build/vivado/chk_m2_zu5ev` / `chk_plat` | `build/vivado/tt_m2_zu5ev.xsa` | `board/m2/tt_m2_zu5ev.elf` | `0e6e1b00e77d9fea` |
| D2 / M2 自检 | 同上 | 同上 | `board/m2/tt_m2_zu5ev_chk.elf` | `861a70fd94150af1` |

M1 和 M2 平台都叫 `chk_plat`，但属于不同工作区，不能按平台名认版本。表中仅是配对检查，不重新声称 M1/M2 源码零告警；C3 完整证据见 `periph/build_manifest_20260928.json`。

- 本地主机 5 个 SD 源文件 CRC 全匹配（包括 LongKou `weights/v2/weights_engine.bin`，不是 int8 包），日志 `build/board/preflight_20260929_crc.log`；**没有检查实物卡**，拷卡后仍须执行 C3a 的 `--root` 命令。
- 只读检查时，Realtek 有线网卡已有静态 `192.168.1.102/24`，状态为 Disconnected；UDP 5011 未占用。未改网卡或防火墙，不能据此认定 PHY/链路/吞吐通过；插线后再次检查路由和端口占用。
- 串口仍按 115200 / 8N1、ASCII、完整原始文本记录：M1/M2 分别存入 `board/m1/`、`board/m2/`；C3 存入带日期的 `board/periph/` 子目录。COM 号、JTAG/PS_UART 实物、拨码及 Debug 初始化尚未现场验证。
- 首次上板仍按下面 C2 → C3 → D2；以上核对不勾选任何真板验收框。

## 1. C2：先建立 M0/M1 基线，过 G-M1

详细平台和源码导入步骤：[m1/README.md](m1/README.md)。注意只导入该文档列出的文件，不递归导入 periph，也不要混入 M2 的 tt_hw_engine.cpp。

1. 下载 M1 程序，记录启动全文；不得有 `WARNING unaligned` 或 `ERROR PL buffer above 4 GB`。
2. 发 ASCII `1`：单 patch PS+PL，要求 `Warmup PASS`，保存 max|dlogit| 和计时。
3. 发 `2`：纯 PS，保存正确性输出及 ms/像素，作为 M0。
4. 发 `3`：保存 PS/PL 两组结果，要求 `COMPARE PASS`。
5. 发 `5`：要求 `PAIR CHECK PASS`，保存双 patch ms/像素。
6. 日志放 `board/m1/`，填写 `report/perf_m1.md` 的 M0/M1 行。不要把旧 7020 数字当 ZU5EV 实测。

- [x] G-M1 PASS（2026-10-06）：模式1/2完整数值与计时日志、模式3COMPARE PASS汇总、模式5逐位PASS已留档；mode3原始前缀未提供，以独立完整mode2覆盖PS路径，不补造缺失日志。

2026-10-06状态：模式1均值23.136ms、误差1.149e-03 PASS；模式2完整10次均值356.782ms、误差1.149e-03 PASS；模式3汇总PS356.957/PL23.135ms、15.429×、两路径差0；模式5十次逐位一致、流水17.437ms/像素。详见 `m1/20261006_first_run/` 和 `report/perf_m1.md`。数值验收已闭合，不再重跑；模式3保留原有片段来源边界。下一步PMUFW/风扇核对和C3。

## 2. C3：外设测试平台与构建

**2026-10-07实际状态**：SD quick、UDP、DP（用户目视确认）、KEY/LED（用户目视确认）通过；SYSMON两次FAIL、PSINTFP/PS温度历史值异常，尚待修查，不能勾选全部C3。SD full未测。用户实际运行vitis/c3_plat + test_c3，不是下述旧正式ELF；证据board/periph/20261007_acceptance，报告report/perf_c3.md。FSBL警告保留，不能将PL正常值解释为bitstream未加载。

构建说明和当前证据：[periph/README.md](periph/README.md)。平台设置来自 `tools/build_periph_platform.tcl`：xilffs + LFN、lwip211 RAW、静态地址、1000M 配置、描述符 256、pbuf 2048、dppsu 1.3。

在 Vitis 创建/打开外设平台，应用导入且仅导入 `src/ps/periph/*.cpp` 和 `.h`，Release `-O2 -mcpu=cortex-a53 -Wall -Wextra -Werror`。使用平台生成的链接脚本。大约 554 MB 的 BSS 是 SD 缓冲、帧缓冲、网络池等，不代表 ELF 文件这么大。

已正式构建并核对的工作区为 `build/board/periph_formal_20260928/`；当前下载副本 `board/periph/periph_zu5ev.elf` 的 SHA256 以 `board/periph/build_manifest_20260928.json` 为准，不再使用此前13:55旧ELF。正式构建通过不等于下面五项真板通过。

程序启动应显示 `=== C3 peripheral test ... ===` 和 `s S u d t k a` 菜单。首次分项测试，不建议直接按 `a`。

### C3a：SD（s / S）

1. 将 `data/scenes/<景>/` 拷到卡根目录的 `scenes/<景>/`。至少带上 LongKou 的 `cube_i16.bin` 和 `weights/v2/weights_engine.bin`（用于长文件名验证）。不在本流程中自动格式化卡。
2. PC 检查卡上实际文件：`python tools/periph_pc.py crc --root E:/scenes`，E: 按真实盘符替换；必须 MATCHES。
3. 断电插卡、重新启动外设程序，发 `s`。盘符为 SD1 `1:/`。
4. 要求两个 quick 文件均 `OK`、大小与 CRC 匹配，并有 `C3a SD PASS`。当前程序允许缺少非首项时 SKIP，因此**只有汇总 PASS 不足以证明 LFN 已验证**。
5. 全景文件拷齐后发 `S`，记录每文件 MB/s、耗时、CRC；SKIP 只能记未测，不能记通过。速度是文件 open/read/close 路径，不含 CRC 计算，1 MB=10^6 字节。

### C3b：UDP（u）

1. PC 有线网卡手动设 `192.168.1.102/24`；板为 `192.168.1.10:5010`。停止占用本机 UDP 5011 的地面站。仅对测试 Python/专用网络放行防火墙，不关闭整个防火墙。
2. 发 `u`，记录 PHY ID、链路状态/速率和 UDP READY。**READY 不是吞吐 PASS**；1000M 为当前 BSP 配置，优先用千兆网卡/交换机。
3. 菜单等待期间执行（仓库根）：
   ```powershell
   python tools/periph_pc.py all --out board/periph/<日期时间>
   ```
4. 要求 `C3b UDP PASS`：ping 回包≥99.9%、内容匹配，两个方向 100 Mbps **发送上限**下丢包≤0.1%、数据错误0。此阈值是本测试的工程验收设置，不是官方最低吞吐要求，也不是保证实测达到100 Mbps。
5. 不限速两项只记录吞吐/丢包和主机瓶颈；同时保留 PC JSON 与板端 TX/RX 输出。测试 UDP 时不要再触发 SD、GPIO 等阻塞菜单项。
6. 若程序提示无回包，先查 u/线缆/IP/网卡路由/防火墙/端口占用，不据此宣称 PHY 损坏。10054 是排查提示，不是板上结论。

### C3c：DP（d）

显示器选择正确输入；优先直接 DP 线，DP→HDMI 必须使用兼容的主动转换器。发 `d`，HPD 等待最多30秒。出现 STREAMING 后必须肉眼确认1920×1080图案、四边橙色边框、色块/灰阶/棋盘格，并保存照片；**STREAMING 不等于显示 PASS**。重插后再按 d。无画面时保存训练/链路日志，按 PLAN 记录失败并采用串口进度退路，不隐藏缺项。

### C3d：SYSMON（t）

发 `t`，保存 PS/PL 温度、电压当前/最小/最大值及 `C3d SYSMON PASS/FAIL`。程序窗口为10..85℃、标称电压±5%，是工程检查范围，不替代器件完整额定规范；读数异常先核对 bitstream/通道/板卡型号。此项不是功率计，不得由电压温度推算实测整板功耗。

### C3e：按键/LED（k）

发 `k`，目视 PS LED（MIO40）闪3次；15秒内按下并释放 PS KEY（MIO26）3次。要求检测3次、串口 `C3e KEY/LED PASS` 且肉眼确认 LED 随按键变化。只测 PS 引脚；PL LED/KEY 不在当前平台中，不能记成已测。

- [ ] 五项分别记录 PASS / FAIL / 未测及证据路径；串口汇总不能替代 DP/LED 目视证据。

## 3. D2：由会话 A 维护，过 G-M2

仅按 [m2/README.md](m2/README.md) 选择 M2 平台、正式版和 selfcheck 版、下载并测试；本文不复制 A 的构建参数。

- [x] 前置 G-M1 已过（2026-10-06），不重跑。
- [x] 2026-10-07 正式版 COMPARE PASS、PS/PL差0、PAIR CHECK PASS；已提供片段无tt_eng ERROR，正式启动前缀未提供，不扩展声称全程已审计。
- [x] selfcheck 12条PASS、累计288调用零不一致，完整启动至返回菜单。
- [x] G-M2 PASS：15.776ms单patch/10.876ms每像素流水，分别比M1改善；自检计时不作性能。
- [x] 证据 `board/m2/20261007_acceptance/`；性能、范围及实际编译参数差异 `report/perf_m2.md`。

## 4. 当日结束

保存原始串口/JSON/照片和产物哈希，失败项记录复现步骤；未上板项不勾选。更新进度及性能报告后再判断 D4/D5 的后续安排。
