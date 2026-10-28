# M3a / D4a 当前入口

## 2026-10-16 Vitis 2026.1 构建入口（迁移后）

```powershell
$ws = 'D:/HSI_AgriEdge/build/board/chk_m3a_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/check_xsa_platform.py D:/HSI_AgriEdge/build/board/m3a_sources_20261007/tt_m3a_zu5ev/tt_m3a_zu5ev.xsa $ws psu_cortexa53_0 tt_engine
& D:/AMD/2026.1/Vitis/bin/vitis.bat -s D:/HSI_AgriEdge/tools/vitis_py/build_m3a_app.py $ws D:/HSI_AgriEdge/build/board/m3a_sources_20261007/tt_m3a_zu5ev
```

- 冻结包（prepare_m3a_sources.py 产出）原样作输入；tt_engine 驱动不在 BSP，由脚本从平台
  hw_artifacts 暂存导入；冻结源码里的 `#include "xtime_l.h"` 由垫片转发到 `xiltimer.h`。见
  `docs/vitis2026_migration.md` §4.6。
- 本轮构建结果（2026-10-16）：平台 `build/board/chk_m3a_20261016/chk_plat` 生成通过；
  `test_m3a` BUILD PASS、0 告警（`test_m3a.elf`）。未上板。


## 下一轮计划（2026-10-07，尚未执行）
入口 **`docs/m3_next_round_plan.md`**。按收益优先安排：先建立阶段耗时/共享资源/端口与P=1/2/3调度模型，再做INT8打包小核和可复用的多上下文流水，减少必要的片上搬运；根据瓶颈决定是否补PS双缓冲或M3b。INT16 P=2作为可行回退，不能保证INT8/流水自动翻倍。下次开始从S0起步，不恢复停止的overlap_v2，不重测已过项目、不覆盖串行XSA/App；由用户完成最终Vitis Build/下载。

## 2026-10-07 当前：串行真板基线通过，优化只评估
- 用户完整UART已验收：数值零mismatch；n1含embed LOGITS 3.628719ms；n16含embed CLASS 3.626181ms/patch。120个samples/12组汇总全部复算匹配；完整用户Build日志已从Vitis工程只读找回，无需再索要。报告 `report/perf_m3.md`，证据 `20261007_acceptance/manifest.json`。
- 用户最新要求先评估收益再决定；评估见 **`report/m3_optimization_assessment.md`**。INT8已有QAT/整数参考/全集精度，不等于已有INT8 HLS或板上加速；当前串行FULL已无层间DDR往返，PS embed差分只约6.4%。
- 曾启动独立overlap候选v2，12层CSim通过后进入综合分析，已按用户新要求停止。没有综合完成/RTL/时序/新XSA结果，不续跑。运行前旧v1的open_project路径错误已留证据，目录 `20261007_optimization_assessment/`。保留默认0及串行XSA/App不变，M1/M2/C3不重测，SYSMON暂缓。

## 2026-10-07 串行测试 App / 导入包

当前操作说明见 **[app_readme.md](app_readme.md)**：独立 `m3a_plat` + `test_m3a`，由用户 Vitis Build/下载。源码 `src/ps/m3a/`；仅打包入口 `tools/prepare_m3a_sources.py`；包检查 `tools/test_m3a_sources.py`；主机/编译检查 `tools/test_m3a_app.py`。

交付包 `build/board/m3a_sources_20261007/`（另有同名 zip）；检查证据 `board/m3/20261007_app_preflight/`。复用原串行 XSA，未重跑 HLS/Vivado，未创建/修改用户 Vitis 工程。App 自动做完整权重、LOGITS/CLASS、DUMP/续算及 n=1/3/16 测试，默认 12 组计时、每组 10 次；两种 scope 都用同一 A patch。**M3a 真板数值/性能仍待用户回传，主机计时是合成测试数据，不是性能。**

以下为过程历史，旧“尚无 App / XSA”“正在构建”不代表当前状态。

## 最新用户决定：先上串行M3a，再做优化
先准备已有串行XSA的黄金向量测试App/源码包，由用户Build/下载，首轮验证正确性、单次延迟与批吞吐，计时范围区分预embed输入和含PS embed。现有XSA无需重建，哈希见20261007_system_impl/manifest.json；当前无后台任务。

并行候选TT_M3_OVERLAP=1只通过主机套件，默认0，已保留但暂不综合/导出。build/hls/run_m3a_overlap.tcl未执行；候选证据20261007_overlap_candidate_host。当前HLS源码已含候选，与串行XSA旧快照并非逐字节一致；串行硬件源码入口a82e6b2/旧snapshot，不把候选源码当作已过RTL/时序的版本。

正常FULL没有层间DDR中间结果往返，但仍有输入/首次权重/寄存器/输出交互；DUMP例外。M2→M3a的总收益不能全称为去交互收益，后续再用独立对照区分并行和交互开销。

## 2026-10-07 16:10 更新：系统实现完成，尚待测试App
200MHz系统时序PASS：WNS+0.067ns/TNS0、WHS+0.010ns/THS0、WPWS1.000ns，check_timing十二类均0；Vivado退出0。LUT57060、FF69804、BRAM113.5、URAM20、DSP620。证据 `20261007_system_impl/manifest.json` 及原报告/log，普通告警保留。

XSA `build/vivado/tt_m3a_zu5ev.xsa` 已生成并检查ZIP CRC、配套bitstream、PS init和驱动内容；无需再综合或重建。主/子Vivado进程已结束。下一步准备M3a专用黄金向量测试App/源包，再由用户Build/下载；此刻不能拿M2 ELF替代，尚无M3板上结果。以下运行中描述保留为历史。

## 2026-10-07 15:26 更新：完整RTL PASS，系统实现运行中
完整12层、三patch LOGITS/CLASS、续算、PROJ全部逐位通过，Vitis退出0；证据 `20261007_full_cosim/manifest.json`。三patch LOGITS 1989538拍，按200MHz折算3.3159ms/patch，仅RTL结果，不是板上或端到端性能。

随后启动独立M3a系统实现：`build/vivado/build_m3a_zu5ev.tcl`，主PID4200，日志 `build/host/m3a_system_20261007/vivado.log`，退出状态 `exit_code.txt`；工程 `build/vivado/tt_m3a_zu5ev`。先核对进程/日志，不重启。脚本先检查完整cosim、快照/导出来源，再构建；拒绝覆盖已有输出，WNS未过不导XSA。

目前尚未得到系统时序结果，也未有M3板上App可下载。下面旧“完整RTL运行中”保留为过程历史；下一步系统结果→测试App/源包→用户Build下载。

## 2026-10-07 第一阶段：驱动主机验证完成，完整RTL验证运行中

**尚无M3a真板结果、配套系统XSA或可交付Vitis App，不要把新驱动加入已验收M2应用，不要创建/下载M3平台。** G-M2已通过，留作基线；M1/M2/C3不重跑，SYSMON继续暂缓。

### 本次新增
- `src/ps/tt_m3a.h/.cpp`：独立同步FULL驱动，M3a int16/18位激活专用；完整权重包LOAD_W，CLASS/LOGITS/FEAT、DUMP、层区间。没有改变M2驱动/HLS契约。
- `sim/host/test_m3a_driver.cpp`：真实驱动通过带寄存器/cache时序检查的传输层调用HLS C模型，对n6_engine逐位；另用错误注入测试LOAD_W和计算超时、错误M2位宽、引擎错误、非法地址/容量/重叠。
- `tools/test_m3a_driver.py`：可重复主机测试，标准库，无平台/板卡动作，不删除旧输出。执行 `python tools/test_m3a_driver.py`；缺省工具路径见脚本，按需传--cxx/--hls-include。

### 主机已验证（不是RTL/板上）
正式套件8阶段通过：驱动严格语法检查、主机编译、6个运行场景。正向HLS模型覆盖A/B/A三patch的32槽LOGITS、CLASS类别+置信度与奇数末字、12层DUMP各层、从第5层续算FEAT；全部逐位。检查DMA写界和cache调用次序。另用Vitis2020.2 AArch64编译器及现有生成API头做-fsyntax-only/-Werror通过，未Build应用/ELF。

### 驱动调用约束
1. 与M2驱动不能同时拥有同一个IP；单线程调用，初始化前硬件须空闲/由用户完成匹配M3平台初始化。
2. `tt_m3a_init(device_id)`后加载**完整**weights_engine.bin（480576B），不是M2仅填投影的包。头部检查magic、版本2、ncls、16位；LOAD_W返回契约版本3、激活18位、小数12位才接受。
3. 输入每patch按31808B跨距打包int16，使用黄金参考的内存序，不是连续无padding的15876元素数组。输出大小用`tt_m3a_output_bytes`计算，包含64B cache隔离padding；所有DMA跨度必须低于4GiB、基址64B对齐，输入输出不重叠。
4. CLASS/LOGITS必须到第11层；DUMP只允许FEAT。层号从0开始。DUMP布局为层优先、patch次之。
5. max_polls为轮询次数上限，不是毫秒或硬件看门狗。超时不终止DMA：不作废输出、不复用缓冲、不再写寄存器；须外部PL复位并重启应用。软件init不能清除此故障。
6. 这是串行功能基线，未实现异步重叠、双库或前端CUBE/int8，不承诺性能。

### 当前RTL任务（恢复前先核实进程/日志，不重复启动）
- cwd `D:/HSI_AgriEdge`；HLS PID8908 / xsim PID35288；最后观察2026-10-07 14:45，14/20事务，仍运行。
- 命令：`D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat -f D:/HSI_AgriEdge/build/host/m3a_full_20261007/cosim_full.tcl -l D:/HSI_AgriEdge/build/host/m3a_full_20261007/vitis_hls.log`。
- 日志 `build/host/m3a_full_20261007/console.log`；脚本显式TT_TB_LAYERS=12。复用`tt_engine_m3_k7`原综合RTL，启动前313个源码/testbench/golden与快照逐字节相同。旧1层log已保存；未重新综合或Vivado实现。
- 完成必须核对本次log的layers=12、12层输出/批LOGITS+CLASS/层5..11对比均0、COSIM finished PASS；不能看旧.done或单一结束返回码。depth=0工具告警保留，未擅自忽略或重综合。

### 接下来
1. 等本次完整RTL结果；失败则先保存诊断，不能声称M3通过。
2. 核对完整RTL拍数与资源。旧OOC：LUT56693、BRAM18=227（113.5 BRAM36）、URAM20、DSP620、4.906ns@5ns；只是IP OOC，不是整板时序。
3. 决定是否必要的存储/调度优化；成批验证后准备M3系统构建、黄金向量板上测试App与源包，再由用户Build/下载。现有M2平台不可用于M3功能。

证据 `20261007_driver_preflight/manifest.json`，报告 `../../report/m3a_preflight.md`。提交定位 `git log -1 -- src/ps/tt_m3a.cpp`。
