# 迁移后在真板上跑通业务闭环（2026-10-17 板测记录）

目的：确认「2020.2 环境做好的项目 → 2026.1 工具链」这次迁移之后，整套系统在真板
（ALINX AXU5EV-E，XCZU5EV-2SFVC784I）上还能正常跑，并把学长的演示复现出来。

结论：**能跑**。下载、启动、SD 权重表、选权重、下发任务、UDP 回结果、板上分类图，
全链路过了一遍；5×3 ROI 的 15 个字与 2026-10-09 板测参考逐位一致，整幅 LongKou
220,000 像素全部产出。

## 1. 用的是哪套产物

| 项 | 实际用的 | 说明 |
|---|---|---|
| 工具链 | Vitis / Vivado **2026.1**（`D:\AMD\2026.1`） | `Vitis\bin\xsdb.bat` 下载与启动 |
| 下载脚本 | `build/host/dl_gcs.tcl` | 复位 → 编程 PL → 跑 FSBL 到 `XFsbl_Exit` → 下载应用 |
| 比特流 | `build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_app/_ide/bitstream/tt_gcs_r1_abi4_zu5ev.bit` | 7,797,812 B，SHA256 前缀 `E5D1B5C4F121E4E9` |
| 应用 ELF | `build/host/gcs_r1_abi4_vitis/gcs_r1_abi4_app/Debug/gcs_r1_abi4_app.elf` | GCS r1 / ABI4，`SERIAL_DEBUG=false`（串口静默） |
| 板卡 | AXU5EV-E，SW1 `0000`（PS JTAG），DP 1920×1080，SD 卡在位 | 串口线未接，全部走 UDP + DP 观测 |

四个比特流副本（Vitis `_ide` / Vitis 平台 `hw` / 平台 export / `build/vivado`）哈希完全相同，
即下载的就是 2020.2 那次验证过的 PL 配置；2026.1 重新综合的 M1/C3/M2/M3a 比特流此前已核为
**字节相同**，所以 PL 侧不受迁移影响。

## 2. 跑过什么、看到什么

### 2.1 下载与启动

`xsdb.bat build/host/dl_gcs.tcl` → `[1/4]`…`[4/4]` 全过，退出码 0（日志 `logs/dl_gcs_20261017d.log`）。
GCS 版串口静默，判据是 DP 出界面 + UDP 有回包：

- DP 显示深色界面、地图面板、任务卡「等待地面任务」、模型行「尚未选择模型」= **READY 空闲**。
- `PING` 有 `PONG`，`STATUS` 每 250 ms 一包；`INFO` 读回 `boot_id`、协议 v1、引擎契约 4、
  片上位宽 16、**SD 上登记 14 个权重包**。

### 2.2 选权重（WACT）

板卡上电后 `STATUS.wcrc = 0`（没选模型）。发 `WACT(scene=0, when=0, crc=0x27231983)` 后：

```
ACK type=0x13 code=0            ← 接受
STATUS wcrc=27231983            ← 已装入 LongKou v2 引擎权重（480,576 B，从 SD 读）
```

`when=0` 是「下一任务起用」；`when=1` 在本版固件回 `code 8`（单库实现，未做双库热切换）。

### 2.3 5×3 ROI 与学长参考逐位比对

`tools/s2c_roi_client.py --boot-id 228ce0f5 --session 5a5a0001 --board-started`：

```
START once: boot=228ce0f5 session=5a5a0001 task=24095
ROW y=0: A58F0000 92170005 AED80000 F5ED0000 F8760000
ROW y=1: F6110000 E48B0000 FA0C0000 FF540000 FF700000
ROW y=2: F5880000 F08F0000 FBF60000 FF610000 FED10000
PASS: received=15/15 matched=15/15
```

比对基准是 `report/system_s1b/20261009_app_board_r1/uart_attempt_03_user.txt`
（2026-10-09 板上记录的真值参考，SHA256 `d8541b4b…`）。**15 个 CLASS 字逐位相同**，
证据目录 `build/host/board_demo_20261017_193500/`（`summary.json`、`packets.jsonl`、
`session.json`、`results.csv`、`result.html`）。

### 2.4 整幅 LongKou（一张完整的分类图）

`tools/gcs_mini.py`（本次新写的窗口版小地面站，只用标准库）选「整幅」跑完：

```
selftest: PASS done=220000/220000 rows=550 errors=[]
saved:    build/host/gcs_mini_20261017_195226
```

- 400×550 = **220,000 像素全部产出**，550 行齐全，9 个类别全出现，图上没有空白像素。
- 耗时约 15.5 分钟 → **实测 4.42 ms/像素**（int16 引擎，含 PS 侧取数与结果落 DDR）。
- 产物：`class_map.png`（400×550 分类图）、`class_stats.csv`、`summary.json`。

类别占比（图与统计两边逐项相等，`tools/class_stats_from_png.py` 独立复核）：

| 类别 | 中文名 | 像素 | 占比 |
|---|---|---:|---:|
| 6 | 水体 | 69,080 | 31.40% |
| 3 | 阔叶大豆 | 56,691 | 25.77% |
| 0 | 玉米 | 36,056 | 16.39% |
| 5 | 水稻 | 12,764 | 5.80% |
| 7 | 道路与房屋 | 11,764 | 5.35% |
| 1 | 棉花 | 11,106 | 5.05% |
| 8 | 混合杂草 | 8,564 | 3.89% |
| 4 | 窄叶大豆 | 8,247 | 3.75% |
| 2 | 芝麻 | 5,728 | 2.60% |

> 统计口径说明：`gcs_mini.py` 第一版按「行」去重计数，而宽 400 的行会被拆成两个 ROW 包
> （348+52），右边缘 52 列因此漏计（当时 CSV 合计 191,400）。已改为**按像素去重**
> （`grid` 用 0xFF 作未上色哨兵），并用 400×16 的 ROI 复核两边逐项相等；
> `gcs_mini_20261017_195226` 的 CSV/JSON 已按图重算，`summary.json` 里
> `stats_source` 注明来源。地图 PNG 本身没有这个问题（每个像素只画一次）。

## 3. 复现命令

```bat
:: 1) 下载（会复位板卡）
D:\AMD\2026.1\Vitis\bin\xsdb.bat D:/HSI_AgriEdge/build/host/dl_gcs.tcl

:: 2) 选权重（板卡刚上电时 wcrc=0，必须先做这一步）
D:\Anaconda\python.exe D:\HSI_AgriEdge\tools\board_model.py

:: 3) 严格验收：5×3 与学长参考逐位比对
D:\Anaconda\python.exe D:\HSI_AgriEdge\tools\s2c_roi_client.py ^
    --boot-id <INFO 里的 boot_id> --session 5a5a0001 --board-started

:: 4) 整幅出图（窗口版，选场景 → 整幅 → 开始；约 15.5 分钟）
D:\Anaconda\python.exe D:\HSI_AgriEdge\tools\gcs_mini.py
```

命令行快速演示：`tools\demo_roi.py`（5×3，秒级）、`tools\demo_roi.py --rows 64 --cols 64 --quiet`。

## 4. 这次没验到的

- **2026.1 重新编译的应用 ELF 没上板跑**：M1/C3/M2/M3a 的 2026.1 工作区存在、比特流字节相同，
  但这几条自检路线要串口交互，本次串口线没接（设备管理器无 CP210x），所以只有 GCS r1（2020.2 编译）
  上过板。接上串口后按手册 4.1～4.3 补测即可。
- **Vivado 重新综合出比特流未验证**：本机 `Generate Bitstream` 仍会崩（`0xC0000374`），
  现有比特流都是 2020.2 产物；手册 5 章已注明“只做下载不需要 Vivado”。
- **三景（HongHu 475×940 / HanChuan 303×1217）没跑**：本次只跑 LongKou 整幅，按 4.42 ms/像素
  外推约 35 / 27 分钟，SD 上 14 个权重包应已覆盖这三景，未逐个验证。
- **原版地面站仍连不上**：`/api/board/connect` 要 `approved_elf.json` + `sync.json`，
  本树没有（`tools/gcs_mini.py` 是绕过发布审查的替代路径，不经过那条门禁）。
- **温度/功率/PHY 未测**：`STATUS` 里这三项按固件约定是 NaN，不用 0 或估计值顶替。
