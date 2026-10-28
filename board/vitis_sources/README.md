# 按 XSA 整理的 Vitis 手工导入包

**2026-10-07 串行 M3a 新入口**：只需 M3a 时使用独立 `tools/prepare_m3a_sources.py`，操作见 [../m3/app_readme.md](../m3/app_readme.md)。交付在 `build/board/m3a_sources_20261007/`，只有既有 `tt_m3a_zu5ev.xsa` 和 `test_m3a`，不重新生成下述旧包或重测 M1/M2/C3。以下旧步骤保留为对应包的历史说明。

**你自己新建 Platform → App → 导入源码 → Build → Run As。这里不是已建好的工作区，不能用“导入已有工程”直接导入此包。**

在仓库根运行 `D:/pytorch/python.exe tools/prepare_vitis_sources.py`，生成目录显示在终端；默认放在 `build/board/vitis_sources_<时间>/`。只复制所需输入，不改原工程，不启动 XSCT/Vivado，不覆盖旧目录。包内有 XSA、源码、必需数据、每个 App 的 README/settings.json 和哈希 manifest。

## 1. 选择对应的 XSA 和 App

```text
导入包/
  README.md
  manifest.json
  tt_zu5ev/
    tt_zu5ev.xsa
    phy_id/src/          ← 明天先建这个，只读 PHY 识别
    m1/src/              ← 基线推理
    c3/src/              ← 外设测试，必须单独配置 BSP
  tt_m2_zu5ev/
    tt_m2_zu5ev.xsa
    m2/src/              ← 正式版
    m2_selfcheck/src/    ← 自检版，不用于计时
```

这两个 XSA 是现有版本的原样副本，不是新综合的设计；板型 E/B 尚待实物核实，**不能因工程能编译就认定硬件适配**。PHY 探测程序不需要 PL IP，但仍需要 XSA 对应的 PS/DDR、GEM3 时钟/复位和 MIO 初始化。E/B 最终以 PCB 型号/修订和实物器件交叉确认。

## 2. 明天先手工建 PHY 识别程序

1. Vitis **2020.2**，选你自己的空工作区。新建 Platform Project，名字例如 `phy_plat`，选择包里的 `tt_zu5ev/tt_zu5ev.xsa`；处理器 `psu_cortexa53_0`、OS `standalone`。BSP stdin/stdout 选 `psu_uart_0`。**不勾 lwip211、xilffs**。Build 平台。
2. New → Application Project，选择 `phy_plat` 的 A53 standalone 域，命名 `phy_id_zu5ev`，模板 **Empty Application (C)**。不要选 lwIP 模板。
3. 导入 `tt_zu5ev/phy_id/src/` 中三个文件到新 App 的 `src/`：`main.c`、`phy_id.c`、`phy_id.h`。保留 Vitis 自动生成的 `lscript.ld`，不要导入其他 App 的 main 或 platform.c。
4. C/C++ Build Settings：GCC Compiler 加 `-std=c11 -O2 -mcpu=cortex-a53 -Wall -Wextra -Werror`；保留默认 BSP include 路径及 xil/gcc/c 链接库，不添加 lwip4。不需要自己写驱动。
5. Linker Script 保持所有段在低 DDR `psu_ddr_0_MEM_0`（<4GB）；Build，确认成功。生成的是你自己的 Debug/Release ELF。
6. **断电接线**：按对应板卡手册接电源、JTAG、PS_UART，启动开关设 JTAG。串口 115200 / 8N1、文本模式、保存日志；本程序不需要 SD 卡、网线或 IP 配置。
7. 上电后选你的 App，Run As → Launch on Hardware（或等价的单应用硬件启动项）。首次在运行/调试配置中核对 A53 #0、系统复位、**PS 初始化**和当前 App 的 ELF，不能沿用另一 XSA 的初始化。若 Debug 停在 main，要 Resume 才执行。
8. PHY 程序是 **PS-only**，不用勾 Program FPGA。若向导使用 FSBL 初始化，必须是同一 XSA 平台生成的 FSBL；不要随意混用旧启动文件。未执行 PS/DDR 初始化时，仅下载 ELF 可能无串口或无法运行。
9. 复制从 `PHY_ID_DIAG v1` 到 `PHY_ID_DIAG_END` 的整段输出。无需按 u，启动即扫描一次，结束不会开始其他测试。

Run As 是 JTAG 下载到内存后运行，**不等于写入 Flash/SD 启动镜像**，断电后需重新下载。这里没有替你生成或修改 BOOT.bin。

## 3. 怎么看识别结果

每个地址打印两次寄存器 2/3 的读取值；扫描包含地址 0 和 31。

- `KSZ9031 / E-candidate`：完整 ID 匹配 `0x0022162x`，末位为芯片修订。是 E 型的强线索，不是 PCB 型号证明；地址通常为 3，但不按地址直接判断。
- `JLSEMI-family / B-candidate (JL2121 unconfirmed)`：ID1 为 `0x937C`，支持景略系列/B 型线索。现有 ALINX 补丁只按厂家 ID 进入 JL2121 分支，因此程序**不凭这个字段宣称具体就是 JL2121**；保存 ID2，结合芯片丝印确认。地址通常为 1。
- `UNKNOWN_PHY`：有稳定响应但型号不在表中；**不等于 B**。`UNSTABLE`/`SUSPICIOUS` 不能作为识别结果。
- `EMPTY`、全 0000/FFFF：未获得有效身份；可能无该地址、供电、PHY 复位、MIO 或时钟问题，不等于坏板，也不区分 E/B。
- `MDIO_TIMEOUT`：管理总线没完成，本轮终止而不是无限等待。检查匹配的 PS 初始化/时钟/复位；不要继续跑 C3 的 u。
- `ACTIVE_MAC`：MAC 正在收发，拒绝接管。先复位重新 PS 初始化，不在 C3/lwIP 运行过程中直接覆盖执行本程序。
- 多地址响应可能是别名或多器件，不自动选板型。所有情况下都输出 `BOARD_MODEL=UNCONFIRMED`。

程序仅写 GEM 的 MDIO 使能/分频和读事务命令，结束恢复原控制/分频；**不发 PHY 写事务、不软复位 PHY、不改页面、不配置协商、不启用 MAC 收发、不写 GPIO/Flash**。只读寄存器 2/3（PHY ID1/ID2），不读取会清除锁存状态的 BMSR。每次等待有 10ms 时间限制及 100000 次轮询后备；若 CPU 的 MMIO 访问本身异常/总线不返回，软件超时无法修复。平台初始化自身会配置 PS，不属于“整套启动零写寄存器”。

## 4. 其他 App 的配置

**每个 App 只导入自己的 src 内容，不要合并五套源文件。** M1/PHY 可用同一 XSA 的纯 standalone 平台；C3 推荐另建 `c3_plat` 防止 BSP 配置互相影响。M2 两个 App 使用 `tt_m2_zu5ev.xsa` 新建的平台，不能选 `tt_zu5ev.xsa`。

| App | 模板 | 编译 Symbols（GCC/G++ 两处） | 额外选项 | 额外链接库 |
|---|---|---|---|---|
| phy_id | Empty C | 无 | `-std=c11` | 无 |
| m1 | Empty C++ | `TT_HW_RUNTIME_SWITCH` | `-ffp-contract=off` | `m` |
| c3 | Empty C++ | 无 | 见下方 BSP | `xilffs`、`lwip4` |
| m2 | Empty C++ | `TT_HW_RUNTIME_SWITCH` | `-ffp-contract=off` | `m` |
| m2_selfcheck | Empty C++ | `TT_HW_RUNTIME_SWITCH`、`TT_ENG_SELFCHECK` | `-ffp-contract=off` | `m` |

所有 App：`-O2 -mcpu=cortex-a53 -Wall -Wextra -Werror`；保留默认 BSP include 和 xil/gcc/c 库，C++ 保留默认 C++ 运行库。低 DDR 链接，不要把 PL DMA 缓冲放高于 4GB。M1 平台需生成 `xtucker_proj.h`，M2 需生成 `xtt_engine.h`；缺少时先核对 XSA 和 BSP 驱动，别复制另一平台的头文件凑编译。

M1/M2 两版附带 `region_f32.bin`（编译需要，与 SD 数据不同）。导入时必须一起复制到 App/src，生成副本里的 `.incbin` 使用 `../src/region_f32.bin`，适配 Vitis 默认从 `Debug/` 或 `Release/` 编译；不要只导入 .c/.h，也不要再套一层 src。仓库原源码没有被改写。自定义编译输出目录时需要相应调整相对路径。

### C3 专用 BSP（现有版本，未针对待确认的 B 板改驱动）

在其 Platform 的 BSP Settings 中：

- 勾选 `xilffs`、`lwip211`；`psu_dp` 驱动选择 `dppsu` **1.3**（依赖 avbuf/video_common 随之生成）。
- xilffs：`use_lfn=1`；SD1 的卡对应盘符 `1:`。
- lwip211：`api_mode=RAW_API`、`lwip_dhcp=false`、`phy_link_speed=CONFIG_LINKSPEED1000`、`n_rx_descriptors=256`、`n_tx_descriptors=256`、`pbuf_pool_size=2048`、`mem_size=524288`。
- 重新 Build 平台，再编 C3 App；C3 要链接 `xilffs`、`lwip4`（库名不是 lwip211）。
- 如果 PHY 确认为 JL 系列/B 型，**先停在识别结果，不发送 u/a**：当前 C3 的初始化/速率解析和 XSA 风扇常量需复核适配，不能用“UDP失败”证明硬件故障。

M1/C3/M2 运行需要各自匹配的 PL bitstream；与 PHY 的 PS-only 情况不同。实际板型未明确前，复核风扇极性，不做长时间负载运行。后续仍按项目 `board/CHECKLIST.md` 的 C2→C3→D2 验收。

## 5. 验证和维护边界

本包是方便手工建工程的源码快照。源码维护入口仍是仓库 `src/ps/`（以及 M2 寄存器头 `src/hls/tt_engine_regs.h`）；在 Vitis 修改后需同步回仓库并重新生成包。不要维护多套互相矛盾的源码。

`manifest.json` 给出 XSA/源码/数据的来源、SHA256 和仅发生在副本上的 incbin 路径改写。含数据的导入包仅供当前本地实验；遵守 WHU-Hi 授权约束，不自动公开发布。

本地预检查可以使用已有匹配 BSP 做交叉编译，但**不替代你新建平台的验证，也不表示 GUI、JTAG 或真板已通过**。此轮没有生成新的 Vitis 工作区。

开发者复查（在原仓库根目录，不是你手工建工程的必做项）：

```powershell
D:/pytorch/python.exe tools/test_vitis_sources.py <导入包目录>
D:/pytorch/python.exe tools/verify_vitis_sources.py <导入包目录> --out <全新的验证目录>
D:/mingw64/bin/gcc.exe -std=c11 -Wall -Wextra -Werror -O2 -Isrc/ps/phy_id sim/host/test_phy_id.c src/ps/phy_id/phy_id.c -o build/host/test_phy_id.exe
./build/host/test_phy_id.exe
```

第二项只借用本机已有的 M1/C3/M2 匹配 BSP 和链接脚本，先核对其 XSA 哈希再交叉编译。它不会调用 XSCT、创建 Vitis 工作区、替换旧 ELF 或连板；验证 ELF 留在独立目录，不加入源码导入包。若原 BSP 不存在，直接按前面的手工建工程步骤操作，不必为了验证器另造旧工作区。

PHY ID 判据依据：KSZ9031 的完整 ID 定义见 Linux `include/linux/micrel_phy.h`（`PHY_ID_KSZ9031`）；JL 厂家码依据本地 ALINX `2020.1版本lwip例程专用库文件.zip` 中 `lwip211_v1_2/src/contrib/ports/xilinx/netif/xemacpsif_physpeed.c` 的 `JLSEMI_IDENTIFIER=0x937C`。只读 MDIO 编码依据 Vitis 2020.2 `emacps_v3_12` 驱动；未复制厂商补丁到交付源码。
