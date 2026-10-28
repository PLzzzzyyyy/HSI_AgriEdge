# 2026-10-09 S1a已实现并通过主机验证，停止于此

- 起点f6a1919，新增PS ROI模块及针对性主机测试；串行N6、已加载DDR预处理HWC→取窗归一化→PS embed→FULL CLASS→RAM结果。未接SD/独立App/地面站/DP，未改HLS/旧driver/数值函数，未启动硬件工具，不覆盖XSA和用户平台/App。
- 47个非法输入、8个ROI/批量成功用例、严格主机编译、6模式PASS。真实PS数值对独立参考与既有函数；真实driver接合成MMIO/CLASS，非PL或板上通过。超时输出页不可访问，input/patch只读；上层session阻止再次准备/读回DMA缓冲。错误只保留完成前缀。
- 代码src/ps/system/m3a_roi.h/.cpp；测试sim/host/test_m3a_roi.cpp；复现tools/test_m3a_roi.py（新out目录）。报告report/system_s1a_roi.md，入库证据report/system_s1a/20261009_roi_host_r4/，原产物build/host/m3a_roi_20261009_s1a_r4/。没有后台任务待交接。
- 新坑：MinGW链接旧tt_net数值函数仍要求未使用的legacy投影符号，主机仅用fail-fast陷阱补齐，禁止为了链接通过接入M2 owner。旧源码/driver不动；独立App最终链接尚未验证。
- P2/2ms仍暂停，G2和旧OOC FAIL保留，未重跑任何旧任务；旧3.626181ms不是当前ROI端到端性能。
- 下一步只是等待用户确认S1b范围（SD加载/独立App准备），不是自动开始。后续S1c真板ROI、心跳/地面站、DP各分轮。用户Build/下载；本轮本地commit、不push。原计划docs/system_20261009_m3a_first_handoff.md其余边界继续适用。
- 共用进度/CODEX快照、双方可访问项目memory和索引同步；提交定位git log -1 -- src/ps/system/m3a_roi.cpp。技能候选已写协作日志，未擅改独占skill/；无新依赖、外部代码或许可变更。
