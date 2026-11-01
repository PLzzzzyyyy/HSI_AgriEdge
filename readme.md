# 无人机高光谱张量农情分析系统

2026 AMD 自主选题初级组，光谱拾穗 / Gleaners。正式提交包，整理日期 2026-11-01。

公开仓库：https://github.com/PLzzzzyyyy/HSI_AgriEdge 。原创部分采用 MIT，见 `license`；第三方内容的来源与权利见 `docs/third_party_notices.md`。

## 推荐目录与交付内容

| 目录 | 内容 |
|---|---|
| src/ | HLS / RTL / PS 源码 |
| sim/ | 主机参考、黄金向量和 HLS testbench |
| build/ | 构建脚本、冻结身份、原始路径映射 |
| board/ | 板卡说明、已有上板记录 |
| data/ | 数据安装说明；大数据附件独立下载 |
| skill/ | 资源汇总、PS 配置抽取、通用 PYNQ 接口预检 |
| report/ | 16 页设计报告、协作记录、实现报告和实测证据 |

gcs/、model/、tools/、firmware/、docs/、manual/ 分别保留地面站、模型、工具、固件、文档和手册，属于本项目扩展目录；不再包含多棵历史工程。

## 从解包到运行

归档文件名全部规范化为小写英文。原已验证源码与固件内容保持原字节，原逻辑文件名写在 `build/delivery_metadata/layout_map.json`，不会为改文件名而改写冻结身份。不要直接执行规范化树里的原启动器；先还原运行树：

```text
python tools/verify_submission.py
python tools/materialize_runtime.py --output D:/hsi_agriedge_runtime_20261101
cd D:/hsi_agriedge_runtime_20261101
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe verify_package.py
```

`--output` 必须是不存在且与提交树分离的目录。还原工具逐项核对 SHA256，不启动产品、不操作板卡。还原后按原 README.md 设置 Vitis / XSDB、网络和显示链路，再运行 START_DEMO.bat。工程原始环境为 Windows；其他系统的工具链与硬件运行仍需独立验证。

PC 数据附件位于 GitHub Releases 的 `snapshot-20261028`：下载 `HSI_AgriEdge_data_20261028.zip` 解压到**还原后的运行根目录**，再运行 `python verify_package.py --with-data`。数据不随本源码 ZIP 重复打包；SD 镜像仍需另行准备，不能把 PC 数据附件当作 SD 镜像。

## 工程证据与技能包

设计报告：`report/design_report.pdf` / `report/design_report.md`。当前资源及时序报告：`report/evidence/s02_current_implementation/`。同板 PS/PL 单像素比较：`report/evidence/s01_single_pixel/`。精度与完整预测统计：`report/evidence/s04_accuracy/`。

`skill/resource_summary/` 和 `skill/factory_psu_extract/` 是已有可跨项目复用技能。新增 `skill/pynq_overlay_contract/` 面向 PYNQ、不绑定本题或板卡，含两个不同设计、可执行检查器、正负例和测试记录。仅通过主机合成数据测试，尚无 PYNQ 真板验证；本队主应用仍为裸机，不能声称其采用了 PYNQ。通用 PYNQ 加分由赛事评审确定。

## 验证范围

文件/归档校验、运行树还原和原始计时/精度复算通过不等于新的硬件验收。原报告中历史快照路径可通过布局映射定位；当前解包、还原和启动步骤以本 readme.md 为准。已有外部 checkpoint、字体、绝对工具路径和空白 SD 复现限制按报告保留。


## 本次合并交付

最终单文件 RAR：GitHub Releases → complete-delivery-20261101 → hsi_agriedge_complete_delivery_20261101.rar。总包约 68.5 MB，包含推荐项目结构，以及 packages/ 中的 engineering_package.zip、skill_package.zip、design_report.zip 和 pynq_overlay_contract.zip。

本仓库直接保留源码、固件、技能和报告，压缩分包只发布在 Release，总 RAR 解压后可直接核验，不必再解开这些重复分包。data/reference/ 提供随包小型输入和参考结果；build/reports/ 提供当前实现报告；board/current/ 为当前上板入口。

指南逐条对照及独立复现边界见 docs/competition_requirements.md。源代码树使用 package_manifest.json 核验；总 RAR 额外使用 deliverable_manifest.json 核验全部文件与嵌套 ZIP。旧版多树历史 RAR 不作为正式单项目提交包混入。
