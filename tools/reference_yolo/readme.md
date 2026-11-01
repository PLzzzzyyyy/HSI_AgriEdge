# reference_yolo：pose6d_fpga/tools 的只读参考脚本

原样复制，注释与默认路径仍指向 `D:\FPGAlearn\pose6d_fpga`。

- `jtag_run.tcl`：XSCT 下载 ELF、跑、读内存探针的模板（A9 目标，地址表对应该项目的 mem_map.h）。ZU5EV 上改 A53 目标与地址。
- `sync_bsp_driver.py`：HLS 驱动改版后同步进 Vitis 平台 BSP 的三处副本。
- `patch_cosim_axi_master.py`：2020.2 cosim 的 AXI master 仿真模型补丁。
