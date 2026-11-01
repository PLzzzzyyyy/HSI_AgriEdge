# 当前上板工程与运行入口

板卡为 ALINX AXU5EV-E，当前部署身份为 firmware/keys_20261018/deployment.json，配套固件与冻结源按原字节保留。

1. 先执行 python tools/verify_submission.py。
2. 按根 readme.md 用 tools/materialize_runtime.py 还原独立运行树。
3. 安装依赖、配置匹配的 Vitis/XSDB、JTAG、网口、DP 链路与已准备好的 SD 卡。
4. 在还原后的根目录执行 START_DEMO.bat；只重开控制台时执行 START_DEMO.bat skipload。

实际按键、DP 状态、固件身份及历史实测记录位于 report/evidence/s07_deployment、s08_offline_keys、s09_dp_status。软件哈希核验和历史数据复算不能代替新一轮板级测试。
