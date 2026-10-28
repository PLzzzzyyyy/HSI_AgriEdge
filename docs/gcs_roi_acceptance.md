# 原地面站真实板端 ROI 与 DP 验收入口

> **2026-10-10交接更新：** 本文下面保留固定ROI阶段操作历史。正式小ROI已由用户操作验收通过；当前仓库已含尚未完成、未部署的整景/PROBE扩展，用户Vitis仍为已验收的24源ELF9a1cd013…。不要直接按旧固定参数检查/同步器运行WIP。最新目标是全部GCS功能/S3完成后统一DP，实际验收后才第一版收工。先读 [最新交接](gcs_20261010_next_handoff.md)。


## 当前范围与状态（2026-10-10）

复用原 `gcs/`，不是另做静态 HTML；用户已确认不存在并行会话，gcs 写权限已移交。
初始目标为固定 LongKou/v2、原点(0,0)、宽5高3真实推理正式显示；用户随后要求尽量对齐
PC推理功能并增加DP，明确暂不需要DC功率计。当前已实现固定ROI正式UI + 同结果DP，
**新增App Build已由用户完成，实机执行/正式界面/DP联合验收仍待本次新启动及回执**。
不把当前范围称为完整v1、整景、OA、性能、长稳或完整PC功能对齐。

## 单条启动 / 操作

```powershell
D:\pytorch\python.exe -B tools\gcs_roi.py serve
```

固定 `http://127.0.0.1:8765`。入口先核端口，已有本版服务则复用；其他服务占用就停止，
不抢端口、不改防火墙/网卡、不自动打开设备。启动默认PC源，板卡门禁未授权。
原网页顶栏数据源指示 → 链路页 → 选择“板卡 UDP” → 应用。
选择本身不发UDP；固定ROI表格应15格“未收到”，开始按钮不可用。

### 用户Build/冷启动（人工）

- 现有 `vitis/s2c_roi_app` 和 `s1b_m3a_plat` 原样复用。2026-10-10用户确认自动Build关闭，
  已将main、runtime.cpp/.h和新增canvas/display.cpp/.h同步；24/24 SHA一致，配置/lscript不变。
- 用户15:38:50–15:38:54增量Build：4编译单元、11对象链接；0error/0warning/2note。
  `-O2 -std=c++14 -mcpu=cortex-a53 -ffp-contract=off -ffunction-sections -fdata-sections -Wall -Wextra -Werror`、
  `-lm --gc-sections`保留。ELF SHA256
  `9a1cd0132d6b6d89123ad35a85c2c99b8992404c32e7421f371c2f851dba88c7`。
- 已通过只读ELF审核，不重Build。由用户执行匹配M3a平台的独立冷启动与下载，不能热接管旧App。
  launch应为当前ELF、A53_0、匹配bit/PS init/FSBL、Reset entire system；不修改旧launch。
- 显示器先开机接DP；UART0独占，关闭自动发送/宏/重连重发。完整r1提示后用PC系统CSPRNG现取：
  `D:\pytorch\python.exe -c "import secrets; print(format(secrets.randbits(32), '08x'))"`。
  人工仅发一次8位hex+LF/CRLF；不得复用e4196b84或e86a03b1；r1所有预算、错误锁闩不变。
- 等SD loaded1/cleanup0、DP init_rc0、READY，提供完整UART及新boot_id，明确
  **“新版业务App已按流程启动”**。此前不授权、不发板端任务。
- DP `init_rc=0`只表示配置及链路检查成功，不代表画面验收；应看到READY和15个NO RESULT。
  init_rc1=初始化失败、2=3秒HPD未到、3=训练/链路失败、4=帧地址非法、5=重复初始化、6=画面参数错误。
  无自动DP重训。DP失败可独立诊断，不把GCS成功等同于DP成功。

### 确认后解锁与用户点击

只有收到用户上述确认和本次新ID，才执行（这条只是授权本机界面，不发送板端UDP）：

```powershell
D:\pytorch\python.exe -B tools\gcs_roi.py authorize --boot-id <新8位hex> --board-started
```

用户在原网页选择板卡源并点击 **开始**；任务自动固定LongKou/v2、(0,0)、宽5高3。
每boot一次且在发包前持久化消费记录；页面重复点、切来源、服务重启均不重发START。
目标严格 `192.168.1.10:5010`，临时本机UDP端口、5秒身份握手/30秒总接收界限、250ms PING。
只允许PING/一次START；不STOP、不ROWREQ、不探查/上传/换模型、不推理回退。

板端真实START后LOAD_W→取窗/embed→M3a；结果只取CPU已提交区域。DP先显示RUNNING，
当前同步调用内不伪造逐像素进度；完成后显示15格与本次boot/session/task。
GCS按实收唯一像素计进度，**ACK关联 + 15唯一像素 + 匹配DONE**并经短有界队列排空后才显示完成。
错身份/模型、旧任务、缺行、冲突重复或失败ACK不能成为成功；重复相同数据不增像素。
没有类别训练映射证据提升，因此对外显示零基编号；颜色只作编号区分。

### SD材料

本轮无需新增。原卡逻辑盘1，`scenes/longkou/`：

|路径|字节|CRC32|
|---|---:|---|
|cube_f32.bin|243794880|BF3B60C5|
|weights/v2/cls_token.bin|10584|C85F498E|
|weights/v2/pos_embed.bin|63504|F5113FAE|
|weights/v2/weights_engine.bin|480576|27231983|

DP绘图由源码生成，不读PNG/字体/预存分类图。完整LongKou立方体已在原卡，但这**不等于**
当前App已支持整景调度。后续整景/任意ROI原则上不用补这四文件；Test100评测、多场景/模型若实施，
还要明确掩码/数据包和版本CRC清单，不能把未知文件随便放卡或宣称已具备。

## 验证与证据

```powershell
D:\pytorch\python.exe -B tools\gcs_roi.py test
D:\pytorch\python.exe -B tools\test_gcs_roi_dp.py
node tools\check_gcs_roi.cjs C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright
```

以上仅新增离线单元、实际BSP语法、锁定界面检查，不能冒充板测；不跑旧基线。
浏览器锁定检查必须在尚未授权、没有当前任务时做。板测后仅观察当前真实任务：

```powershell
node tools\check_gcs_roi.cjs C:/Users/86187/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright --live
D:\pytorch\python.exe -B tools\gcs_roi.py verify --run-dir build\host\gcs_roi\attempt_<时间> --uart <本次完整UART文件> --ui report\gcs_roi\20261010_formal\ui_acceptance.json
```

`verify`严格只读：回放本次UDP→核保存JSON→逐字核UART→核DOM/API/下载结果；历史参考仅作比较，
绝不补数据。`formal_acceptance`不含DP目视验收，DP须另外保存用户照片/目视回执并核15格、身份和状态。
原始运行每次新目录：session.json、packets.jsonl（逐包hex/方向/peer/时间）、summary.json、results.csv。
界面JSON/CSV导出由实际按钮触发。证据汇总 `report/gcs_roi/20261010_formal/`，首份失败不得覆盖。

## PC功能对齐差距（不以按钮存在冒充实现）

|原PC功能|当前真实板源|下一所需|
|---|---|---|
|固定ROI分类、置信度、任务状态、导出|已实现；本次实机待验收|核本次UART/UDP/DOM/DP|
|任意ROI、整景推扫|目前拒绝，绝不调用PC代跑|私有参数/结果缓冲/分段ROW及有界调度；不改旧driver数值|
|Test100/OA/混淆矩阵|目前拒绝|批准真实板任务语义、掩码材料、实测后另验|
|单点logits、7×7邻域|目前禁止PC探查回退|使用已存在M3a LOGITS接口的私有任务/收包集成与实测|
|注意力热图|不支持真板输出|不能把PC参考混入板源；保留明确未支持|
|多模型、权重上传、微调后重跑|板源当前不支持|单独完成版本/CRC/持久化与切换生命周期，不能隐式解锁|
|暂停/停止/补传/断线恢复|本次子集未实现|保留协议既有设计，另做可验证实现|
|DP同结果监视|已实现并用户Build；待本次显示回执|照片/目视和身份/15格核对|
|功率/温度/能耗/性能|未测；用户暂不接DC表|不显示0，不用NaN转0或未置PHY位推断线|

旧同步S3等待期服务限制仍在，没有修改或宣称修复；DMA超时永久停车、外部PL复位+App重启、
CPU成功前缀、补卡不追溯、原dump/OA/性能/长稳未覆盖、P2暂停/G2旧OOC FAIL全部保留。
本轮新增DP硬件流程复用C3，不重跑C3彩条基线，不把主机像素测试当DP实测。
