# 2026-10-09 S1b独立平台/App：手动Build准备

## 当前更新：平台已完成，下一轮从第3节App开始

用户实际采用原工作区`D:/HSI_AgriEdge/vitis`并新建`s1b_m3a_plat`，20:50:13 Build完成，已核配置及导出。用户明确一次预配BSP：除xilffs外，还启用lwip2111.3和dppsu1.3；不等于现在接入业务。**不用再建平台/执行下方历史平台准备步骤。** 报告`report/system_s1b_platform_build.md`含准确配置、告警、XSCT DP绑定及重建Tcl遗漏风险。

下一轮助手逐步指导用户创建`vitis/s1b_roi_app`，按第3节导入/设参数/Build，不让用户自行摸索。下文独立工作区路径是原建议，未采用；以现有`vitis/s1b_m3a_plat`为准。

## 原准备小轮结论（历史）

起点`42cf4ca`，只读核验通过；**新平台、应用BSP及App尚未创建，未Build**。用户在Vitis 2020.2手动操作；助手等首轮Build日志再定位，不提前修编译问题、不启动硬件工具、不下载、不做S1c。

- 36项输入/原源码/包输出的尺寸与SHA全部匹配（有CRC字段的同时匹配CRC），`app_src`恰好15文件，无额外文件；manifest与入库r1副本内容一致。未重打包，未重跑S1a/S1b或旧硬件。
- 冻结XSA原件/副本一致；HWH中SD1已启用、MIO46..51、CD为MIO45。没有要求修改硬件的证据。
- 本地SDK 2020.2的xilffs4.4参数定义、生成脚本及C3 BSP只读确认下述最小字段与默认映射。**参考BSP正确不代表尚未生成的新BSP已配置正确。**
- 用户已有Vitis IDE `eclipse.exe` PID27228，经`cmd.exe` PID36464启动交互式`rdi_xsct.exe` PID26000，指向旧`D:/HSI_AgriEdge/vitis/`；未发现S1a/S1b runner、综合或A53编译进程。助手未启动/结束这些用户进程，不能写成全机无后台。

证据：`report/system_s1b/20261009_build_preflight/{audit,background}.json`。没有新的SD/PL/A53链接/真板/性能证据；历史63用例PASS只引用原记录。

## 1. 独立路径（建议，用户创建前再确认仍未占用）

| 项目 | 绝对路径/名称 |
|---|---|
| 新Vitis工作区 | `D:/HSI_AgriEdge/build/board/s1b_vitis_20261009` |
| 新平台 | `s1b_m3a_plat`，位于上述新工作区 |
| 新App | `s1b_roi_app`，位于上述新工作区 |
| 已核源文件夹 | `D:/HSI_AgriEdge/build/host/m3a_s1b_20261009_r1/source_package/app_src` |
| 导入XSA | `D:/HSI_AgriEdge/build/host/m3a_s1b_20261009_r1/source_package/hardware/tt_m3a_zu5ev.xsa` |

核查时新工作区及两个项目路径均不存在；助手没有创建它们。禁止覆盖`vitis/m3a_plat`、`vitis/test_m3a`、C3或其他已有工程。若另选路径，请提供实际绝对路径并保持隔离。

冻结XSA SHA256：`9813b5632250839274e6e298e5e4df8ea601b6d41016351148f98cf6057d9652`。只用此串行M3a，不用P2/S2，不重新导出硬件。

包中`S1B_SOURCE_REV=5d3720c269a8+manifest`表示生成时父提交加manifest，不是声称新增源码已存在于5d3720c；15文件已与入库包核对，不为改显示文字重打包。

## 2. 用户创建平台与应用BSP

1. 用户自行切换到新工作区，创建Platform Project `s1b_m3a_plat`，从已核XSA创建。处理器`psu_cortexa53_0`、OS `standalone`、64位A53域，stdin/stdout均`psu_uart_0`。
2. 进入**新平台的应用standalone domain**的Board Support Package Settings，不是`zynqmp_fsbl` BSP。选择`xilffs`版本`4.4`；旧m3a应用有sdps3.10但缺xilffs/ff.h，不能借FSBL FatFs。

| xilffs字段（本机2020.2准确名称） | 值 | 最小理由 |
|---|---|---|
| `fs_interface` | `1` | SD，不是RAM文件系统 |
| `use_lfn` | `1` | 静态LFN缓冲；`cls_token.bin`、`pos_embed.bin`、`weights_engine.bin`超过8.3短名限制 |
| `num_logical_vol` | `2` | 逻辑驱动0和1，App固定`1:/` |
| `enable_multi_partition` | `false`，默认 | 保留逻辑驱动号到物理驱动号直接映射 |
| `enable_exfat` | `false`，默认 | FAT32，不扩展到exFAT |

其余保持默认，包括`read_only=false`、`use_mkfs=true`；这不要求App写卡/格式化。App只以`FA_READ`打开，不调用写入/格式化API，无需额外裁剪库。不复制C3整套BSP，不加lwIP/DP/线程/多核。`use_lfn=1`为非重入静态缓冲，符合本App单调用者串行范围。

3. 用户在新工程确认/生成BSP并Build平台；检查实际应用域`bsp/psu_cortexa53_0/`下的文件（路径以新工程为准）：

```c
/* include/xparameters.h */
#define FILE_SYSTEM_INTERFACE_SD
#define FILE_SYSTEM_USE_LFN 1
#define FILE_SYSTEM_NUM_LOGIC_VOL 2
#define XPAR_XSDPS_NUM_INSTANCES 2
#define XPAR_PSU_SD_1_DEVICE_ID 1
#define XPAR_PSU_SD_1_BASEADDR 0xFF170000
/* include/ffconf.h的有效值：FF_USE_LFN=1, FF_VOLUMES=2,
   FF_MULTI_PARTITION=0；同时存在ff.h及lib/libxilffs.a。 */
```

**两逻辑卷不是给SD卡分两个分区。** xilffs4.4的`ff.c`在`FF_MULTI_PARTITION=0`时`LD2PD(vol)=vol`，`diskio.c`调用`XSdPs_LookupConfig(pdrv)`；结合SD1 DeviceId=1，得到`1:/ → pdrv1 → SD1@0xFF170000`。误开multi-partition时库默认`VolToPart[1]`反而指向物理驱动0。不要手改diskio/生成头或把App改到`0:/`绕过配置；先提供新BSP证据。

只读来源：SDK `D:/xilinx/Vitis/2020.2/data/embeddedsw/lib/sw_services/xilffs_v4_4/data/{xilffs.mld,xilffs.tcl}`；C3应用BSP的`system.mss`、处理器目录内`include/{xparameters.h,ffconf.h}`及`libsrc/xilffs_v4_4/src/{ff.c,diskio.c}`。旧m3a应用`xparameters.h`也确认SD0/1 DeviceId=0/1；引用不代表其已含FatFs。

## 3. 用户创建空C++ App并Build

1. 创建`Empty Application (C++)`，名`s1b_roi_app`，选**新平台的新standalone应用域**。将`app_src`全部15文件复制导入新App的`src`，不要链接旧App目录；不导入hardware/manifest/主机stub。若模板有示例main，仅移除新App自己的示例，最终只有包内`main.cpp`。
2. 七个编译单元：`main.cpp`、`legacy_traps.cpp`、`m3a_app.cpp`、`m3a_roi.cpp`、`m3a_sd.cpp`、`tt_m3a.cpp`、`tt_net.cpp`；其余8头文件。不加入test_m3a/m3a_bench、tt_hw_engine/tt_hw_xil/tt_hw_sim/tt_data或M2 owner。
3. 活动配置的C++编译参数如下。优化栏选O2，避免后置O0覆盖；以实际命令为准，不只看Debug/Release名字：

```text
-std=c++14 -O2 -mcpu=cortex-a53 -ffp-contract=off
-ffunction-sections -fdata-sections -Wall -Wextra -Werror
```

不启用`TT_HW_RUNTIME_SWITCH`、fast-math、A9参数；未见日志不提前改数值函数或删`-Werror`。

4. 链接保留新BSP默认库/路径，加入`m`、`xilffs`（Libraries栏通常不带`-l`）和`-Wl,--gc-sections`，顺序/依赖按新BSP实际链接命令。保留或启用map输出，例如`-Wl,-Map=s1b_roi_app.map`。
5. 新App自己的链接脚本选低DDR `psu_ddr_0_MEM_0`，不选高DDR/OCM/QSPI，不复制旧脚本覆盖。旧XSA派生参考低DDR为`0x0..0x7FEFFFFF`，高DDR起点`0x800000000`不可用于本App DMA；最终以新脚本/map确认。
6. Build后检查约244.53MB显式静态缓冲、text/bss/heap/stack无重叠、低DDR容量，以及`cube/cls/pos/weights/patch/input/output`起点64B对齐、完整跨度低4GiB。大小为源码估算，不是最终ELF测量；大`.bss`不等于ELF文件同样大。不提前增大heap/stack或改公共接口。

## 4. 固定LongKou/v2（本轮仅核文件，不操作SD卡）

本地根`D:/HSI_AgriEdge/data/scenes/longkou/`；卡上后续对应`1:/scenes/longkou/`：

| 相对路径 | 精确字节数 | CRC32 |
|---|---:|---|
| `cube_f32.bin` | 243794880 | BF3B60C5 |
| `weights/v2/cls_token.bin` | 10584 | C85F498E |
| `weights/v2/pos_embed.bin` | 63504 | F5113FAE |
| `weights/v2/weights_engine.bin` | 480576 | 27231983 |

四文件SHA再次匹配原manifest，权重头`[0x32455454,2,9,16]`。cube为预处理小端float32 HWC `(556,406,270)`、3像素零边；以相同哈希承接旧有限值/零边/EMB/投影证据，没有重跑数值扫描/重新导出。不混v1、raw、cube_i16/BFP或M2包。

## 5. 下一小轮只收Build证据

请提供：新工作区/平台/App实际绝对路径、应用domain与xilffs配置（截图或`system.mss`）；**完整Build Console**，从第一条命令到退出摘要，保留首个error上下文，不仅最后`make: ***`。平台/BSP先失败就提供该阶段日志，不跳过去诊断App。

成功时附`.elf`、`.map`、`src/lscript.ld`路径及实际编译/链接命令；若缺ff.h/库或映射存疑，附新应用BSP的`xparameters.h`相关宏、`ffconf.h`。没有日志不猜根因，不宣称已Build。

成功批次/完成前缀、LOAD_W/FULL错误锁闩、超时不读/复用/free DMA、不回CRT、外部PL复位+App重启的约定不变。**仅保留契约，不授权本轮复位/下载/运行。** P2/2ms暂停，G2/旧OOC FAIL保留，不接M2/地面站/DP/双缓冲/多核。

## 只读复核与记录入口

`audit.json`含逐项实际尺寸/SHA/CRC及参考BSP文件SHA；可用`Get-FileHash -Algorithm SHA256 -LiteralPath <具体文件>`对原manifest/入库package_manifest核验，新BSP用`Get-Content`核mss/头文件/映射。只在文件变更/缺失时复核对应项，不运行原测试/准备脚本替代Build日志。

提交定位：`git log -1 -- docs/system_20261009_s1b_build_preflight.md`；协作日志`report/llm_log/2026-10-09_s1b_build_preflight.md`。
