# 打包给队友：目录清单与运行说明

本机现用 PC/DP 联动修复版：直接运行 `START_DEMO.bat`。
它优先下载 `firmware\gcs_r1_abi4_app_linked.elf`，并使用配套独立本地演示身份；
探查结果会同步显示在 PC 和 DP 左侧结果卡。已通过 5×3 真板任务及单点探查，用户确认两端一致。
刷新网页后，在地图选点，再点“发送单点探查”。首次载入场景约需 15 秒。
详见 `docs\pc_dp_link_20261017.md`；原固件和已有任务历史保留。

这套东西分两部分：**能直接跑的运行包**（板卡固件 + 一键启动 + 网页界面），
和**能改的源码**（PS 应用、地面站网页 UI、模型/导出脚本）。

## 一、打包哪些目录

用 `tools\make_team_package.ps1` 生成（默认输出 `D:\FPGAgame\_team_package\HSI_AgriEdge_team_<日期>\`）：

```powershell
# 生成目录（约 36 MB）
powershell -NoProfile -ExecutionPolicy Bypass -File D:\HSI_AgriEdge\tools\make_team_package.ps1

# 顺便压成 zip
powershell -NoProfile -ExecutionPolicy Bypass -File D:\HSI_AgriEdge\tools\make_team_package.ps1 -Zip

# 连 Vivado/Vitis 工程一起（体积大，见第四节）
... -File D:\HSI_AgriEdge\tools\make_team_package.ps1 -WithVitisProjects -WithData
```

| 包内目录/文件 | 来源 | 体积 | 干什么用 |
|---|---|---|---|
| `START_DEMO.bat` | `tools\launcher\START_DEMO.bat` | 6 KB | **一键启动**：下载固件 → 等板卡 → 选权重 → 起网页并开浏览器 |
| `README_运行说明.md` | 本文件 | — | 拿到就能照着做 |
| `firmware\` | 见下 | 14.5 MB | 运行所需的 4 个固件（PL 比特流、应用 ELF、FSBL、硬件描述 XSA） |
| `firmware\tt_gcs_r1_abi4_zu5ev.bit` | `build\vivado\` | 7.8 MB | PL 配置（2020.2 综合，板测在用的那份） |
| `firmware\gcs_r1_abi4_app.elf` | `build\host\gcs_r1_abi4_vitis\...\Debug\` | 3.2 MB | PS 应用（GCS r1，串口静默） |
| `firmware\fsbl_a53.elf` | `build\host\gcs_r1_abi4_vitis\...\zynqmp_fsbl\` | 130 KB | DDR/PS 初始化 |
| `firmware\tt_gcs_r1_abi4_zu5ev.xsa` | `build\vivado\` | 3.4 MB | 硬件描述（`loadhw` 用；重建工程也需要） |
| `tools\` | `tools\` | 1.5 MB | 全部脚本：启动器、网页小地面站、验收客户端、UART/诊断工具 |
| `src\` | `src\` | 2.3 MB | PS 应用源码（含 DP 界面 `roi_canvas.cpp`）、HLS、RTL —— **改固件/改 DP UI 看这里** |
| `gcs\` | `gcs\` | 4.1 MB | 原版地面站与网页 UI 源码、三景调色板与类别表 —— **改 PC UI 看这里** |
| `model\` | `model\` | 9.7 MB | 训练/导出脚本与权重、`export_board_candidate.py` 等（重导引擎权重用） |
| `docs\` | `docs\`（去掉 `vendor\`） | 1.9 MB | `protocol.md`（协议全文）、`engine_arch.md`、板测记录、迁移说明 |
| `board\` | `board\` 的 `*.md/*.txt/*.json` | 1.1 MB | 各平台 README、检查清单、下载脚本模板（不含二进制） |
| `manual\` | `D:\FPGAgame\HSI_AgriEdge_使用手册_v2.3.*` | 0.7 MB | 使用手册（27 页）docx + pdf |

**没打进去的**（体积大、或用处不大，需要时再从主机拷）：`build\`（27 GB 构建树）、
`data\`（4.7 GB 场景立方体）、`vitis\`（1.16 GB 2020.2 工程）、`report\`（491 MB 证据）、
`sim\`（35 MB）、`docs\vendor\`（30 MB 厂商手册）、`.git\`。

## 二、队友拿到后怎么跑

前提：Windows + **Vitis/Vivado 2026.1**（只用其中的 `xsdb` 下载固件）+ ALINX AXU5EV-E 板卡。
**不需要另外装 Python**：Vivado/Vitis 自带一份完整 Python（`<安装目录>\tps\win64\python-3.x\python.exe`，
含 `http.server` / `socket` / `tkinter`），`START_DEMO.bat` 会自动找到它；
要指定的化就设 `HSI_PYTHON=D:\Anaconda\python.exe` 这类。

```bat
:: 接线：DC12V、JTAG（下载器）、网线、DP 显示器；SW1 = 0000（PS JTAG）
:: PC 网口设 192.168.1.102 / 255.255.255.0
START_DEMO.bat
```

它会依次做四件事，全程约 1～2 分钟：

1. 检查 Python（找不到就提示设 `HSI_PYTHON`；Vivado/Vitis 自带的也算）
2. 用 `xsdb` 下载固件（复位 → 编程 PL → 跑 FSBL → 下载应用），**不需要打开 Vivado/Vitis 界面**
3. 检查原版控制台依赖（`fastapi/uvicorn/pyserial/torch`，缺了会打印安装命令）
4. 起**原版控制台**（`tools\gcs_roi.py serve`，`GCS_LOCAL_DEMO=1`），等就绪后打开 `http://127.0.0.1:8765/`

> 启动器**不会**在下载后先 PING 板卡：原版控制台的连接检查要求板卡「刚启动、还没被任何程序 PING 过」
> （INFO 里 task/session 必须全为 0）。谁先 PING 谁就把会话号绑走了，控制台反而会拒连。

这时两个界面都在：

- **DP 显示器**：板卡自己画的界面（地图 / 图例 / 任务卡 / 遥测），空闲时显示「等待地面任务」
- **PC 控制台**：`http://127.0.0.1:8765/` —— 点「连接板卡」（选 JTAG）→ 框选区域或整景 → 「开始」；
  跑完在图上点任意一点就是**单点探查**（带 7×7 注意力热力图），页签里还有农情分析、地块台账、
  精度指标、闭环更新、链路与下发、历史对比、日志

> **单点探查**会同时更新 PC 结果卡和 DP 左侧的「PROBE / PL」结果卡（同一坐标、同一类别）。
> 探查要在任务完成后的约 5 分钟内做；超时后任务连接进入关闭状态（按钮会提示原因），
> 先在任务页点「恢复」，或重新开始一个任务，再探查。

常用变体：

```bat
START_DEMO.bat skipload     :: 不重新下载，只起原版控制台（板子已在跑）
START_DEMO.bat mini         :: 改用精简版控制台 8770（自带单点探查，单文件网页）
START_DEMO.bat ui           :: 只起精简版 8770（板卡已在跑、只改 UI 时用）
set HSI_WEBPORT=8771        :: 精简版端口
set HSI_SESSION=5a5a0001    :: 精简版/命令行工具用的会话号
set HSI_VITIS=D:\AMD\2026.1\Vitis
```

> **两个控制台不能同时连板卡**：板卡上电后只认一个回包地址，两边一起开会互相抢。

## 三、我和队友要改的东西分别在哪

| 想改什么 | 文件 |
|---|---|
| PC 网页界面（三张卡片、统计表、按钮） | `tools\gcs_web.py` 里的 `PAGE` 字符串（一个文件内含 HTML/CSS/JS） |
| 原版地面站网页（可作为参考/移植） | `gcs\web\`（`index.html`、`style.css`、`core.js`、`map.js`、`panels*.js`） |
| DP 显示器上的界面（地图/图例/任务卡排版） | `src\ps\s2c_roi_app\roi_canvas.cpp`、`roi_display.cpp`、`roi_labels.h`（位图字模由 `tools\generate_gcs_dp_labels.py` 生成） |
| 板端业务逻辑（任务、权重、UDP） | `src\ps\s2c_roi_app\roi_protocol.cpp`、`roi_runtime.cpp`、`main.cpp` |
| 协议本身 | `docs\protocol.md`（改协议要两端一起改：板卡 + `tools\` 里的客户端） |
| 精度/权重 | `model\`（`finetune_region.py`、`export_board_candidate.py` 等） |

改 DP 界面要重新编译 ELF 并下载；改网页界面只要重启 `gcs_web.py`（改 `tools\` 下的 Python 都不用碰板卡）。

## 四、关于“重新编译固件”的硬限制（务必先看）

- 板上的 `gcs_r1_abi4_app.elf` 是 **2020.2** 的 Vitis 工程产物，`vitis\` 里那套工程 2026.1 **打不开**；
  仓库里 2026.1 的工作区只覆盖 M1 / C3 / M2 / M3a 四条自检路线（`build\board\*_20261016*`），**不含 GCS 应用**。
- 所以：本次验证的是「2026.1 的工具链能下载并跑通 2020.2 编出来的固件」，
  以及「2026.1 重新综合的 PL 比特流与 2020.2 逐字节相同」。**改 DP/C 代码要重新出 ELF，需要有 2020.2 环境**（或用 2026.1 新建工程重编，工作量另算）。
- 只要不改固件，只调 PC 网页和协议客户端，`START_DEMO.bat` 这条链路完全够用。
- Vivado 重新综合出比特流在本机仍会崩（`0xC0000374`），现有比特流都是 2020.2 产物；四份副本哈希相同。

## 五、板测数字（2026-10-17，真板）

| 项 | 结果 |
|---|---|
| 5×3 ROI | 15/15 个字与 2026-10-09 学长演示记录逐位一致（`tools\s2c_roi_client.py` 判 PASS） |
| 64×64 ROI | 4096/4096 像素，约 18 s |
| 整幅 LongKou 400×550 | 220,000 像素 / 550 行 / 9 类全出，约 15.5 min |
| 速度 | 4.42 ms/像素（int16 引擎） |
| 详细记录 | `docs\board_demo_20261017_migration_check.md` |

## 六、常见问题

**页面顶部一直「服务未连（会自动重试）」**
网页服务没在跑。它会每 0.9 秒自动重试，服务起来后页面会自己恢复；也可以直接重跑 `START_DEMO.bat ui`。
若 `START_DEMO.bat` 报“端口 8770 已被占用”，说明已经有一个在跑，直接用浏览器打开就行。

**页面顶部显示「服务在，但板卡没回包」**
网页服务活着，但收不到板的 `STATUS`。依次查：板卡是否上电、网线、PC 网口是否 `192.168.1.102/24`、
板卡是不是已经把回包地址绑给了**另一个程序**（同一时刻只允许一个程序跟板卡说话——先关掉命令行工具再刷新页面）。

**三张卡片里没有图**
图是点「开始」跑出来才有的（空卡片会提示）。先选「64×64」点一次，18 秒后龙口那张就有图和统计。
整幅要 16 分钟。

**开始点了没反应 / 提示 `code 9`**
板卡正在跑别的任务，或这个任务号用过了。等当前任务跑完（或点「停止」），再点「开始」。

**`xsdb` 找不到**
`START_DEMO.bat` 会扫 `D:\AMD\*`、`C:\Xilinx\Vitis\*` 里的 `Vitis\bin\xsdb.bat`；
装在别处就设 `HSI_VITIS=<Vitis 目录>`。

**DP 显示器没有画面**
本目录已提供 `firmware\gcs_r1_abi4_app_linked.elf`（PC/DP 联动版，启动器第一优先）和
`firmware\gcs_r1_abi4_app_dpfix.elf`（只修 DP 黑屏，第二优先）。两者都已修复 2026.1 SDT 下
DP/DPDMA 查询配置误传设备编号 0 的问题，原固件保留。
2026-10-17 已在本板核验 `DP init_rc=0`，用户已确认显示器画面恢复（DP 转 HDMI 链路）。
“固件下载完成”本身不代表显示成功；若仍黑屏，确认显示器输入源与转接链路，先接好并打开显示器再给板卡重新下载固件。
详细记录见 `docs\dp_black_screen_20261017.md` 与 `docs\pc_dp_link_20261017.md`。

## 七、只发这个压缩包够不够

**够跑，前提是 SD 卡用板子上现在这张。** 包里已经有了：固件（`.bit`/`.elf`/FSBL/`.xsa`）、
一键启动器、网页小地面站、PC 端源码与三景词表、PS 源码（含 DP 界面）、模型与导出脚本、手册、协议。

包里**没有**、但可能用得上的东西：

| 缺什么 | 什么时候才需要 | 体积 |
|---|---|---|
| SD 卡内容（`scenes/<景>/…` 共 45 个文件，含权重包与场景数据 + `boot/jrn*.bin`） | 只在**换一张空白 SD 卡**时需要；现在这张卡已经写好了，插上就能跑 | 约 1.1 GB |
| `data\`（场景立方体等原始数据） | 重训/重导权重、或自己重刷 SD 卡 | 4.7 GB |
| `vitis\`（2020.2 工程） | 重新编译板端 ELF（含 DP 界面） | 1.16 GB |
| `build\`（27 GB 构建树） | 基本不需要 | — |
| `report\`（证据/图表） | 写报告/答辩要用 | 491 MB |
| JTAG 下载器驱动（FTDI / Digilent） | 下载器插到新电脑上时 | 系统驱动 |

需要大件时用参数重打：`-WithVitisProjects`（带 `vitis\` 与 2026.1 工作区）、`-WithData`（带 `data\`）。
SD 卡资源与 `report\` 目前不在自动打包范围内，需要时单独拷。

第一天上手还需要的**硬件**：ALINX AXU5EV-E 板卡、DC12V 电源、JTAG 下载器（板载 FTDI 或 Digilent HS1）、
网线、DP 显示器、**已写好数据的 SD 卡**。

## 八、原版控制台（学长那套 8765）怎么开

学长演示用的那套界面在仓库里：**`gcs\web\`（网页）+ `gcs\server.py`（后端）**，启动方式是
`tools\gcs_roi.py serve`，地址 **http://127.0.0.1:8765**。页签有单点探查、农情分析、地块台账、
精度指标、闭环更新、链路与下发、历史对比、日志；单点探查会连同 **7×7 注意力热力图** 一起回来。

它原本被发布门禁挡住（`approved_elf.json` / `sync.json` 缺，且要求平台必须是 2020.2 GUI 建的）。
现在用**本地演示模式**开：

```bat
START_DEMO.bat console
:: 等价于手工：
set GCS_LOCAL_DEMO=1
D:\Anaconda\python.exe tools\gcs_roi.py serve --port 8765
```

依赖（缺了控制台会起不来）：`fastapi uvicorn pyserial torch`
`D:\Anaconda\python.exe -m pip install fastapi "uvicorn[standard]" pyserial torch --index-url https://download.pytorch.org/whl/cpu`

开起来后在浏览器里点「连接板卡」→ 选 **JTAG** → 框选区域或整景 → 开始；跑完在图上点任意一点就做单点探查。

**演示模式做了什么、没做什么**（`tools\gcs_release.py` 里的 `GCS_LOCAL_DEMO`）：

| 门禁检查 | 正常发布 | 演示模式 |
|---|---|---|
| `approved_elf.json`（人工审查过的 ELF 回执） | 必须 | **跳过** |
| 平台 BSP 同步回执 `sync.json` | 必须 | **跳过** |
| 发布包 manifest 的 release_id / 源集 / XSA | 必须匹配 | **仍然必须匹配** |
| 板上 INFO 回报的 release 标签 | 必须等于上面 | **仍然必须等于** |

也就是说：它只跳过「你有没有在 GUI 里建平台并人工审查这份 ELF」，**仍然要求板子跑的就是发布包那套固件**。
启动时会打印 `!! 本地演示模式…`，产物**不能**写进验收/发布证据。

配套要求：板卡必须跑与本地演示 manifest 对应的固件。本机现用 **PC/DP 联动版**
（release `473aafa8…`，即 `firmware\gcs_r1_abi4_app_linked.elf`，`START_DEMO.bat` 第一优先下载；
配套身份在 `build\host\gcs_pc_dp_link_20261017\` 下）。2026.1 重建原版（release `1a699c42…`）
与 2020.2 产物（release `6f9b125c…`）虽然跑得动，演示模式的 release 校验对不上，**控制台会拒绝连**。

**自测一条命令**（不开浏览器也能验）：`D:\Anaconda\python.exe tools\console_smoke.py`
它会通过控制台的 WebSocket 下一个 5×3 任务并做一次单点探查，打印类别、置信度与 9 类 logits。