# 2026-10-09 最新：有限S1c已确认，S2a源码/定向检查完成

用户已接受原5×3有限功能验收，不追加dump/OA/性能/长稳，不重算/重跑原成功批次。S2a纯协议+薄lwIP源码及独立边界/实际BSP语法检查PASS；未接入App、启动服务或上板，非完整v1/网络通过。当前恢复与下一轮提示词使用 [S2a报告](../report/system_s2a_idle.md) 和CODEX_CONTEXT.md顶部；下一另授权S2b独立空闲App源码/Build清单准备，不自动操作用户工程。下面评估/数值记录保留为历史，不再按其中“待有限验收确认”重复推进。

# 2026-10-09 历史：S1c缺口评估完成，有限验收建议待确认

起点0a86208。本轮仅只读评估，不重算原15像素、不重跑成功板批次/完整套件、不构建/重打包/下载。原S1c计划未把OA/性能/长稳或板端中间dump设为前置；建议用户确认“原5×3 ROI有限功能验收”后进入S2，尚未确认，不宣告完整S1c。原数值证据与下文历史结论保留。

**当前恢复及下一轮提示词改用 [system_20261009_s1c_gap_assessment.md](system_20261009_s1c_gap_assessment.md)**：矩阵区分板端CLASS与离线中间结果；下一仅建议授权S2a空闲PING/PONG/STATUS板端源码/定向主机检查，不开始网络业务或动用户工程。S3的同步轮询/网络服务缺口另报授权，未改旧driver。

最小演示还需S2/S3/S4三关，完整业务/交付再八关；DP做板端独立监视、地面站做任务/农情分析，不复制同一大屏。用户IDE/XSCT/hw_server保留，无助手后台。P2暂停/旧FAIL、成功前缀和超时DMA契约不变，补卡不追溯。本轮仅文档提交不push；下文所有旧提示词仅供历史，不执行。

# 历史：2026-10-09 S1b原15像素同口径数值核验完成

起点f9d51f3。原第三次用户UART的15/15完整CLASS字与两路离线冻结M3a入口A参考逐位一致；原PS取窗/float32/Q3.12匹配，PS饱和0。不是板端中间张量读回、整景OA/性能/完整S1c验收。报告 `report/system_s1b_numeric_reference.md`，证据 `report/system_s1b/20261009_numeric_r2/`；默认/`--verify`入口 `tools/check_s1b_numeric_reference.py` 只读哈希，不重算。

未改旧数值/driver/接口、平台/App、冻结XSA或源码包；没有板端或完整S1a/S1b重跑。r1无计算门禁失败及r2包版本误判均保留；r2已完成C++只继续未完成Python。原成功批次/完成前缀和超时DMA契约不变，P2暂停与旧FAIL保留。后台用户IDE27228/XSCT26000/hw_server30296保留、无助手运行任务。

**这15像素核验已完成，不再列待办。下一先评估最小S1c验收缺口并确认执行范围，不直接接业务或扩大实验。** 提交定位 `git log -1 -- report/system_s1b_numeric_reference.md`，不push。

## 下一轮可复制提示词（当前）

```text
继续 D:\HSI_AgriEdge，先 git log -1 -- report/system_s1b_numeric_reference.md 核最新提交。
读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/system_20261009_s1b_handoff.md和report/system_s1b_numeric_reference.md；先核后台，不操作用户已有IDE/XSCT/hw_server。
原S1b 5×3 ROI已完成15/15完整CLASS字同口径数值对照，两路离线patch/input/logits一致；不是整景OA/性能/完整S1c。证据在report/system_s1b/20261009_numeric_r2/，不要重复这15像素计算或成功板批次。
本轮先按现有系统计划评估最小S1c验收缺口，区分已有证据与未覆盖项，给出一个最小下一步建议和需要确认的授权；先评估，不自行开新实验或扩样本。
不重跑完整S1a/S1b/旧硬件，不重建平台/App、重打包或自行下载；改旧driver/数值/接口、扩大范围前先报告证据和最小范围。补卡已确认无问题，不追溯。
保留成功批次/完成前缀和LOAD_W/FULL超时不复用DMA；P2/2ms暂停、G2/旧OOC FAIL保留。不接M2/地面站/DP，不加双缓冲/多核。一次一小轮，结束四件套、不push，附下一轮提示词。
```

# 历史：2026-10-09 S1b App已Build，首次板端流程成功时待数值对照

## 当前恢复入口

起点f1cebd7，本轮用户创建并Build `vitis/s1b_roi_app`（21:16:09），随后明确授权首次上板，由用户运行。第三次UART `rc=0 sd_loaded=1 completed=15 halted=0`，四文件和清理均过，固定5x3结果完整。前两次file0/file1的FR_NO_FILE保留，不用成功覆盖失败。用户确认补卡无问题，不追溯；助手曾只读预检F盘，未实际复制/修复。

报告`report/system_s1b_app_board.md`，证据`report/system_s1b/20261009_app_board_r1/`。15导入源SHA一致；实际严格A53编译及ELF/map/64B/完整跨度低4GiB已核，_end=0x0E970D00。ELF SHA `2f899ec02cc4263dd54c91720fb0e128a05cfca25044535ad4e405165fada489`。现有平台/BSP/App不重建，不重打源码包，成功批次不重跑。

仅本次流程成功；15个打包结果尚无同口径数值参考，非准确率/性能/完整S1c验收。下一先核PS取窗/float32/Q3.12及冻结M3a参考入口，不能用旧测试像素代替本次坐标。PMU警告保留，未改启动配置；heap/stack已核静态布局，未测高水位。

只读证据复核：`D:/pytorch/python.exe report/system_s1b/20261009_app_board_r1/audit.py --verify`。用户IDE27228/XSCT26000/hw_server30296保留，无助手后台；恢复先核实际进程，不结束用户工具。提交定位`git log -1 -- report/system_s1b_app_board.md`。

### 下一轮可复制提示词（当前）

```text
继续 D:\HSI_AgriEdge，先 git log -1 -- report/system_s1b_app_board.md 核最新提交。
读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/system_20261009_s1b_handoff.md和report/system_s1b_app_board.md，先核后台，不操作已有IDE/XSCT/hw_server。
s1b_roi_app已在现有s1b_m3a_plat上Build并核ELF/map，第三次用户UART四文件校验通过，completed=15/halted=0；原三次日志在report/system_s1b/20261009_app_board_r1/。
本轮只做这次5x3 ROI的同口径数值参考核验：先核PS取窗、float32/Q3.12和冻结M3a入口的口径，给出最小验证方案；不要拿旧黄金像素替代。需要计算时只针对这15像素，不重跑完整S1a/S1b/旧硬件或已成功批次。
不重建平台/App、不重打包、不自行下载；需改旧driver/数值函数/公共接口或扩大范围先报告证据和最小范围。用户确认补卡无问题，不再追溯。
保留成功批次、完成前缀及LOAD_W/FULL超时不复用DMA；P2/2ms暂停、G2/旧OOC FAIL保留。不接M2/地面站/DP/双缓冲/多核，不将流程通过冒充数值/准确率/性能或完整S1c通过。
一次一小轮，结束四件套、不push，附下一轮提示词。
```

# 历史：平台已Build，下一轮创建并Build App

## 当前：用户平台/BSP已完成

实际平台`D:/HSI_AgriEdge/vitis/s1b_m3a_plat`于20:50:13 Build完成；冻结XSA、13对本地/export及AArch64库/boot产物已核。应用BSP已预配xilffs4.4、lwip2111.3及dppsu1.3，FSBL域未混入应用库。7条SDK warning、6条随后恢复的HSI重载错误文本留证，非全日志零告警，但无阻塞下一步App创建的证据。详见`report/system_s1b_platform_build.md`及`report/system_s1b/20261009_platform_build/`。

**下一轮不再建平台。** 助手应从现有Vitis界面一步步指导用户创建`vitis/s1b_roi_app` Empty C++，导入原包15文件，设编译/链接参数，用户Build后核ELF/map。App尚未创建；库预配不等于已接网络/DP。原工作区和新工程名已确认，不继续推荐未采用的build/board工作区。

DP实际用XSCT应用域`bsp setdriver -ip psu_dp -driver dppsu -ver 1.3`切换，不让用户找GUI不存在的驱动表。自动platform.tcl遗漏此覆盖，未来重建时须显式补充；当前已正确，不重执行。用户已有IDE/交互XSCT保留，助手无自建后台。提交定位`git log -1 -- report/system_s1b_platform_build.md`。

## 历史：42cf4ca后的手动Build准备核查

本轮已完成独立路径/36项包文件记录/15源码文件集合/XSA/LongKou-v2及本机xilffs最小配置的只读核验。操作清单见[独立平台/App手动Build准备](system_20261009_s1b_build_preflight.md)，证据`report/system_s1b/20261009_build_preflight/`。未创建平台/BSP/App，未Build；下一等用户实际路径与完整Build日志再定位。

建议新工作区`D:/HSI_AgriEdge/build/board/s1b_vitis_20261009`，核查时不存在。xilffs准确字段`fs_interface=1/use_lfn=1/num_logical_vol=2`，`enable_multi_partition=false`、exfat默认关闭；两逻辑卷不等于两分区，生成BSP后须核`1:/→SD1`。

本次发现用户已有Vitis IDE27228→cmd36464→交互XSCT26000指向旧vitis/，未干预，未见测试runner或构建进程。下文无后台是原S1b完成时记录，不代表现在全机无进程。助手本轮未启动硬件工具或后台任务。提交定位`git log -1 -- docs/system_20261009_s1b_build_preflight.md`。

## 原S1b恢复记录（历史）
读CLAUDE.md、CODEX_CONTEXT.md顶部和report/system_s1b_sd.md，先核后台；不重跑完成的S1a/S1b r1或旧硬件。起点5d3720c，本次提交用git log -1 -- src/ps/system/m3a_sd.cpp定位。无相关后台。

固定LongKou/v2四文件SD加载、一次性启动编排、独立main/traps、打包/主机验证已完成。严格native编译/链接+63用例PASS。真实数据/XSA只读核验与合成FatFs/MMIO证据分开，**非SD/PL/A53/BSP/系统或S1c通过**。

## 可交付包
build/host/m3a_s1b_20261009_r1/source_package/
- app_src/：完整独立源码，包含旧S1a/driver/数值副本、新SD/编排/main/traps、生成s1b_profile.h。不要混入旧test_m3a。
- hardware/tt_m3a_zu5ev.xsa：冻结串行副本，SHA9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652。
- manifest.json：全部源/输入/输出哈希及待配置项，SOURCE_ONLY，不是已Build平台/ELF。
- 仅包丢失时，以tools/prepare_m3a_s1b.py --out build/host/m3a_s1b_sources_<新时间戳>恢复（D:/pytorch/python.exe），不用硬件工具；现有包完整不重复生成/测试。

## 原人工Build前置（历史；平台部分现已完成）
1. 用户确认后，用新工作区/新平台s1b_m3a_plat导入冻结XSA，A53_0/standalone/UART0。不能覆盖vitis/m3a_plat、test_m3a或任何已有平台/App，不用P2/S2 XSA。
2. 旧m3a应用BSP无xilffs，FSBL FatFs不能借用。新应用BSP最小配置参考已验证C3：xilffs4.4、SD interface、use_lfn=1、两个逻辑卷；核FILE_SYSTEM_USE_LFN=1、FILE_SYSTEM_NUM_LOGIC_VOL=2、SD1实例1与1:/映射。不复制整套C3 BSP/lwIP/DP。若需改硬件/旧公共接口/扩大配置，先报告证据再征求用户。
3. 新空C++ App s1b_roi_app只导入app_src全部文件；只移除该新App自己的示例main，不动其他App。不加tt_hw_engine/tt_hw_xil/tt_hw_sim/tt_data/m3a_bench或其他owner。legacy_traps不是后备计算。
4. 用户手动配置C++14、-O2 -mcpu=cortex-a53 -ffp-contract=off -ffunction-sections -fdata-sections -Wall -Wextra -Werror，链接m/xilffs和--gc-sections；库依赖/顺序按新BSP。不要TT_HW_RUNTIME_SWITCH、fast-math或A9参数。
5. 用户Build后核ELF/map：约244.53MB显式静态缓冲在低DDR，DMA64B对齐且完整跨度低4GiB；不放高DDR窗口，text/bss/heap/stack无重叠且容量足够。大数组.bss不等于ELF同样大。本轮无A53/link map证据。
6. 用户后续准备FAT32卡1:/scenes/longkou/，cube_f32.bin及weights/v2/{cls_token,pos_embed,weights_engine}.bin来自同一已核包，精确尺寸/CRC见报告。不是cube_i16/BFP/raw。本轮未写SD卡。

这些都是后续人工动作，本轮**未启动Vitis/XSCT、未生成BSP/ELF、未下载**。用户提供独立工程路径和首轮Build日志后再定位下一小轮问题。

## 结果/异常与边界
固定x0/y0/w5/h3、batch4，成功4/4/4/3；保存原图坐标和原始CLASS字。SD安全失败返回1，loaded0且不启动PL。driver错误/超时仅打印已提交CPU前缀、halted1后永久停车；禁止重试、复用/free DMA、切M2或直接继续debug，需外部PL复位+App重启。重复入口拒绝不是恢复功能。

真板UART/结果与参考比对还需另行授权S1c，mock CLASS、C3独立通过和旧3.626181ms不算本App系统通过。P2/2ms暂停，G2/旧OOC FAIL保留；不接地面站/DP/双缓冲/多核。

## 下一轮可复制提示词
```text
继续 D:\HSI_AgriEdge，先用 git log -1 -- report/system_s1b_platform_build.md 核对最新提交；S1b源码42cf4ca。
读CLAUDE.md、CODEX_CONTEXT.md顶部、docs/system_20261009_s1b_handoff.md、report/system_s1b_platform_build.md及必要的Build清单。
先核后台，不操作用户已有IDE/XSCT，不重跑S1a/S1b、旧硬件或已完成平台Build。
现有平台D:\HSI_AgriEdge\vitis\s1b_m3a_plat已Build并核查，xilffs/lwip211/dppsu BSP已配好，不再新建平台。
本轮请一步步告诉我在Vitis如何创建s1b_roi_app Empty C++、导入既有source_package/app_src的15文件、设置编译链接参数并Build；不要先让我自行Build再索要日志。
由我操作Vitis和Build，你只读检查生成文件及日志；遇错按实际证据定位，成功后核ELF/map/低DDR/64B对齐和完整跨度低4GiB。
你不启动HLS/Vivado/Vitis/XSCT，不修改旧平台/App或XSA，不重打包源码。
需要改硬件、旧driver/数值函数、公共接口或扩大BSP范围时先报告证据与最小范围。
不下载、不做S1c，不接M2 owner/地面站/DP，不加双缓冲/多核。
保留成功批次、完成前缀及LOAD_W/FULL超时不复用DMA；P2/2ms暂停，G2/旧OOC FAIL保留。
一次一小轮，结束四件套、不push，附下一轮可复制提示词。
```
