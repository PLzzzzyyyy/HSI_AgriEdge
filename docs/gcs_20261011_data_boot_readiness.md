# 第一轮数据配套与独立启动准备门禁

**2026-10-11 17:30 当前停点**：45数据/模型及旧cube_i16已PC回读通过；随后按本轮重建/继续准备授权，将新文件系统作为本次新安装，确认双journal不存在后只provision一次并独占写入两64B初始journal，fsync及大小/SHA/字段/配对/CRC通过。JTAG首测SD配套齐备，用户可先连GCS串口再下载运行新平台/v3 ELF，提供BUILD/SD IDENTITY/READY；助手不再写卡、不Build/同步。身份回执sd_identity_01，证据sd_prepare。BOOT.BIN、真实SD冷启动/扫描/掉电持久化和A～G/T仍待，后续不能恢复已用卡的初始journal；下面17:20“journal缺失”是历史。

**2026-10-11 17:20 当前更新**：本次用户明确授权助手重建SD并复制电脑原件。F现29.110GiB FAT32/单active MBR/0x0C，45文件1150149380B实际已写卡并通过独立PC大小/SHA/CRC回读，另保留旧cube_i16。旧第一分区原始镜像和4文件备份、旧cube不可读FAIL及0B卷守卫FAIL全部留存，证据`../report/gcs_roi/20261011_sd_prepare/review.md`。两个journal与BOOT.BIN仍缺，尚未provision、下载/上电或板端SD验收；下一确认新安装身份。平台/正式v3 ELF已PASS且未变，不再Build/同步；下方较早“无新平台/未复制/未备份”等为历史，不能覆盖本停点。PC文件校验不等于冷启动、SD持久化或第一轮通过。

**12:21收尾更新**：用户要求等原后台结束后交接；完整RTL cosim已于12:17 PASS，12:18任务进程退出。未继续export/system/新测试。最新入口 `gcs_20261011_round1_resume.md`，不是第一轮完成或部署就绪。

**2026-10-11 本轮实施更新**：SD双64字节journal启动预约/读回/失败关闭、UART RX-only、显式SD INFO发现及BIF/本地provision/boot bundle/只读核验工具已写候选；最后SD发现组尚未测。未生成BOOT.BIN/初始journal分发包、未复制或核验卡内45文件、无新平台/ELF/真实冷启动。boot bundle依赖尚未完成的G新版审查，不可拿旧24源App/旧XSA打包。FAT整卡回滚/克隆与物理掉电持久性不由RAM测试证明，初始journal不得覆盖已用卡。当前恢复 `gcs_20261011_round1_resume.md`，下文为前阶段本地清单/历史欠项。

**2026-10-11 09:57许可更新**：用户已明确授权上一盘点的E/F/T2必要实现，尤其F脱PC身份来源/持久记录/掉电失败门禁及必要启动契约，见 `gcs_20261011_implementation_handoff.md`。以下本地数据及未生成镜像/未写卡/未实测事实不变；原“待专项确认”为历史状态，实际写卡/启动模式/上下电仍由用户执行。

2026-10-11。这里只核本地输入/模型文件并列出未来 SD 目标路径；**没有写卡、同步源文件、生成 BOOT.BIN、Build App 或操作板卡**。独立启动身份、真实注意力、涉及公共接口的细分计时仍待用户专项确认，第一轮候选尚未全齐。

## 可复现的本地核验入口

```powershell
D:/pytorch/python.exe -B tools/gcs_data_inventory.py --out build/host/gcs_data_inventory/<新目录>/local_data.json
```

输出文件必须是 `build/host` 下不存在的新文件；工具没有 copy/sync、SD/串口/网络、bootgen 或 Vitis 路径。它重新核 cube 的现有 meta SHA、实际 CRC/尺寸与三景输入契约，验证每个所选模型两包及其来源，并列出每个未来目标文件的大小/SHA/CRC。坏文件、缺文件、路径/契约不符会报错，不能生成空清单“成功”。

当前核对：**3 个 cube、7 个完整配对模型，共 45 个数据文件、1,150,149,380 字节**。这是本地选定清单的总字节，不是卡容量/卡上占用的测量，也不包含启动镜像、FAT开销或尚未授权的持久身份文件。

App使用 FatFs 逻辑卷 `1:/`；下表目标均相对该卷，**不是 Windows 盘符或授权立即执行的复制命令**。实际写卡由用户在最终候选/文件门禁齐备后执行。

### 输入文件

| 相对目标 | 字节 | CRC32 | 输入契约 |
|---|---:|---|---|
| scenes/longkou/cube_f32.bin | 243794880 | bf3b60c5 | H550×W400，270波段，3像素零边，9类 |
| scenes/honghu/cube_f32.bin | 491428080 | 857ba1a6 | H940×W475，270波段，3像素零边，22类 |
| scenes/hanchuan/cube_f32.bin | 408139560 | 66ed4ccc | H1217×W303，去原末4波段后270波段，3像素零边，16类 |

这些是既有高斯/全局归一化后的float32输入，不是传感器原反射率、板回传或PC推理结果。完整SHA在生成清单中；本轮还由编译后的私有C++场景表与Python清单契约交叉核对，不能把“路径相同”当数据相同。

### 模型目录

每个 `scenes/<scene>/weights/<tag>/` 包含：

```text
weights_all.bin    # kind0拼接的投影因子段
cls_token.bin      # kind0
pos_embed.bin      # kind0
classifier_w.bin   # kind0
classifier_b.bin   # kind0
weights_engine.bin # kind1 int16 TTE2
```

| 场景 / UI版本 | 实际tag | kind0字节 | kind1字节 | kind1 CRC32 |
|---|---|---:|---:|---|
| LongKou / v2 | v2 | 458724 | 480576 | 27231983 |
| LongKou / v1 | v1_board | 458724 | 480576 | deae4b31 |
| LongKou / hold3 | hold3 | 458724 | 480576 | 83389cc2 |
| LongKou / v3 | v3_board | 458724 | 480576 | ddf16522 |
| LongKou / v3_ft50 | v3ft50_board | 458724 | 480576 | a125aa33 |
| HongHu / v1 | v1 | 596368 | 480576 | 6b5e2b66 |
| HanChuan / v1 | v1 | 532840 | 480576 | 390cc0d0 |

- LongKou/v1原目录曾缺完整companion SHA。现在用**同一个原checkpoint**独立导出 `v1_board`，没有改/补造原目录登记、没有换权重；新kind1 SHA与原v1文件逐字一致：`15925d2dd8e273cc291f0a2d4a10ddde0bd02d27fa5c558d6b678df95bdf4e51`。原目录仍按旧来源不足拒绝本地上传资格，UI v1指向新完整候选。
- hold3/v3/v3_ft50均由既有checkpoint导出，没有新训练。配对包可上传不代表已登记/已持久化/已激活，更不证明旧/新任务实测效果。
- 不复制`.pth`、隐藏`.stage_*`、int8目录、PC参考预测/成绩到这份板端数据清单。DP字体为已有编译内字库，不需分发字体二进制到卡。
- 冷启动必须重新读真实SD字节/CRC/配对；不能根据本清单或模型文件夹名称伪造扫描成功。FAT临时文件+sync/close/rename不是绝对掉电原子事务。

## BOOT.BIN / 独立启动尚未完成的依赖

| 必需项 | 当前可准备内容 | 最终放行需要的证据 |
|---|---|---|
| PS/PL硬件平台 | 列出版本/哈希关系，不用旧产物冒充新版 | E注意力授权后需要的新IP/完整实现/XSA及资源/时序/契约一致性 |
| FSBL / PMUFW / PL bitstream / App ELF | 保留各自来源和工具版本位置，当前不选取旧ELF打包 | 最终全候选统一同步后，用户Build的日志/ELF，以及与所选XSA匹配的配套启动产物 |
| BIF / BOOT.BIN | 可准备参数与门禁说明，本轮未生成可烧录镜像 | 每段加载/执行核与地址正确，镜像组成逐个哈希；不省略应有段，不拿只通过语法当链接/镜像验收 |
| boot身份 | 原r1 PC→UART来源保持，未改公共契约 | 用户确认不依赖PC串口的来源、持久记录/掉电失败门禁；实现及真实冷启动验证 |
| SD文件 | 本地45文件清单已经有精确输入与包身份 | 用户复制/验证实际卡内字节及重启扫描，不覆盖旧版本、失败不得报成功 |
| 启动模式/脱PC运行 | 记录后续人工操作与观测点 | 用户确认并执行启动模式、断电/上电，不经PC注入身份/调试下载后启动；实际DP/身份/约定任务入口证据 |

现在不能为了得到一个BOOT.BIN先使用旧24源App或旧XSA。最终源清单、同步器和ELF审查只在全部候选齐备后适配并统一同步。当前资料不构成独立启动完成证明。

## 测量准备与仍待确认项

- 已有计算指标来自任务步内 `PS准备 + 引擎等待 + 等待回调`，LOAD_W/PROBE/前台DP/UDP/暂停/SD不混入；它不是纯PL耗时。不能拿PC端到端耗时替代这列。
- 本轮私有 `ModelSd` 在已完成的FatFs分块之间泵现有网络/定时器，并分块累计cube CRC，避免主动制造长时间无服务区间。这是生命周期通信保障，不是启动旧性能优化。一次FatFs/BSP调用实际阻塞多久仍须板测；不可由块大小推断毫秒或宣称S3已通过。
- `S3 max_gap/max_service`来自整个任务泵（含setup/PROBE/前台），等待回调接收数只是其中一项。核验器保留原阈值并如实标通信证据，不能通过缩窄scope抹掉长gap。
- PS取窗/embed、driver/cache/PL等待的更细内部计时仍待公共模块/driver扩展授权；真实12层注意力及不依赖PC身份的另两项授权同样未获得。不以logits/PC/MODE_DUMP特征充注意力。
- 第二轮只做验收矩阵/复现/性能归因方案准备；USB鼠标、性能提速与P2均不实施。完整验收矩阵见 `gcs_20261011_acceptance_matrix.md`。

08:47补充：已在不改公共数值/driver的私有App层实现前台分项记录，见 `gcs_20261011_timing_scope.md`。它仍含内部PS/引擎等待，不能拆出纯PL，也不关闭上面的T2专项授权/实际测量缺项；没有改变BOOT/独立身份/用户操作门禁。
