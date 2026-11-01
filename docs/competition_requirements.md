# 选题指南逐项对照与交付范围

核对日期：2026-11-01。依据为用户提供的 AMD 赛道选题指南，SHA256：c6ad82acd4f7bdcd13bd412e232ed85d05f2a87dd5e2cdd04f9d219f88b569fc。

## 赛道适用关系

本作品属自主选题初级组，采用 §3.3.5 的交付要求。§3.1.5 是 RTL/HLS 本地智能体赛道的方案、模型、基线与设计报告要求；本项目借鉴其架构、选择理由、失败分析和复现写法，不虚构独立智能体、Docker 服务、run_baseline 或题集评测成绩。

## 交付矩阵

| 条款 | 包内位置 | 核对结果与边界 |
|---|---|---|
| §3.3.3.3 开源与再分发协议 | license、docs/third_party_notices.md、公开 GitHub 仓库 | 本项目原创部分为 MIT；第三方条款仍适用 |
| §3.3.5.1 源码与工程 | src/、build/、board/、tools/、firmware/ | HLS / RTL / PS 源、脚本、固件身份和上板入口齐备 |
| §3.3.5.1 仿真、实现与实测 | sim/、build/reports/、report/evidence/、data/reference/ | 随附原始证据并提供离线复算；没有新增板测 |
| §3.3.5.2 技能包 | skill/ | 三个独立目录，均有说明和可执行内容 |
| 通用 PYNQ 加分材料 | skill/pynq_overlay_contract/ | 不绑定本队题目或板卡；主机测试 7 项通过，PYNQ 真板验证未做 |
| §3.3.5.3 设计报告 | report/design_report.pdf、report/design_report.md | 已有 16 页完整报告；第 1～13 章覆盖指南七类内容 |
| 大模型协作与纠错 | report/llm_log/、report/evidence/s10_collaboration/ | 保留真实来源与本轮整理记录，不补造历史 |
| §3.3.5.4 目录 | src/ sim/ build/ board/ data/ skill/ report/ | 单项目根 hsi_agriedge，正文外的文件名均为小写英文/数字/下划线/连字符及扩展名 |
| 扩展目录对照 | 根 readme.md | gcs/ model/ tools/ firmware/ docs/ manual/ packages/ 均有用途说明 |

## 已知复现边界

报告第 12 章保留 2020.2 / 2026.1 工具差异、原机绝对路径、外部 checkpoint、字体和 SD 依赖。运行树还原与文件校验不能证明已在全新电脑、空白 SD 上完成从零重建。此项限制不能靠新增说明文件消除；本轮不宣称已经完成。

## 总包及分包

总 RAR 包直接包含推荐结构，并在 packages/ 中同时提供 engineering_package.zip、skill_package.zip、design_report.zip、pynq_overlay_contract.zip。工程 ZIP 是可独立核验的完整工程提交树，已包含技能和报告；后两类分包便于单独审阅，无需把它们相互嵌套。完整数据附件不重复打包。
