# 构建脚本与实现报告

- hls/run_gcs_round1.tcl：稳定 K7 / DB18 / ABI4 / OVERLAP=0 的综合与 cosim 路线。
- vivado/：系统构建、厂商 PS 配置及约束。
- reports/current_implementation/：当前 KEY ECO 位流的资源、时序、DRC、路由和配对哈希记录。
- delivery_metadata/layout_map.json：小写归档名与原始逻辑路径的字节级映射。

先按根 readme.md 还原独立运行树，再执行原构建流程。原稳定 HLS / 系统工具为 2020.2，当前 PS 与 KEY ECO 为 2026.1；报告第 12 章明确记录版本和外部依赖。旧脚本目标 xazu5ev -1 与当前实现报告 xczu5ev -2 不可混认。此包不声称已在干净电脑重建并完成新的板级验收。
