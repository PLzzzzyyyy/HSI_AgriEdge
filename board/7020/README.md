# board/7020：Zynq-7020 版本的实测记录（只读）

来源 `D:\TT_HSI_FPGA` master a348f0a 的 `docs/results/` 与 `board_results/`。串口记录 `board_uart_*.txt` 是板上输出，JSON 是构建与审计元数据，`block_pc_preview/` 是 PC 参考预览（其中 `host_validation.json` 记的源码路径是旧仓库布局，不要拿它做新仓库的陈旧性校验），`board_prediction.bmp` 是板上渲染后经 XSCT 读出的 64×64 块预测图。

最终状态：IP v1.4 + PS round 5b，单 patch 37.5 ms，双 patch 流水 24.3 ms/像素，4096 像素与 PC 定点参考逐像素一致。ZU5EV 的结果另建目录。
