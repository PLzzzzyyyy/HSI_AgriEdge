# reference：pose6d_fpga 的只读参考代码

来源 `D:\FPGAlearn\pose6d_fpga\vitis\app\src`（2026-08-30 状态），原样复制，注释里的路径仍指向那个仓库。

- `net_udp.cpp / .h`：lwIP 裸机 UDP 发送，7020 上千兆分包实测零丢包。ZU5EV 的 PS 网口是 GEM，lwIP 适配层和 BSP 参数要按 psu 平台重配，本项目地面站协议（PLAN §5.5、E2）在此基础上新写。
- `qspi_io.cpp / .h`：QSPI 权重加载。本项目权重与立方体走 SD 卡（PLAN §14），只作参考。

正式代码写在 `src/ps/` 的新文件里，不直接改这两份。
