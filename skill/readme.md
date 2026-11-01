# 可复用技能包

对应选题指南 §3.3.5.2。每一项均包含可执行内容，以及适用范围、用法、失效条件、已验证效果与提炼来源。

| 技能 | 用途 | 当前验证范围 |
|---|---|---|
| [resource_summary](resource_summary/readme.md) | 汇总 Vivado / HLS 资源及时序，避免 BRAM 单位、黑盒和范围混用 | 已有 7 系列与 UltraScale+ 工程记录；当前实现报告可离线复算 |
| [factory_psu_extract](factory_psu_extract/readme.md) | 从厂商 BD 提取 PS 配置，检查初始化差异与平台生成 | 已有 Zynq-7000 / Zynq UltraScale+ 主机工具验证记录 |
| [pynq_overlay_contract](pynq_overlay_contract/readme.md) | 面向 PYNQ 的 Overlay / ip_dict 合同预检，检查 IP、版本、地址范围、参数和文件哈希 | 7 项主机合成测试通过；两个无关设计；未进行 PYNQ 真板验证 |

## 复用入口

前三项各自的 readme.md 给出最小命令、输入要求和失败条件。PYNQ 检查器不绑定农情分类、AXU5EV-E、固定物理地址或特定 IP 名称；换题目或板卡时更换合同与对应 Overlay 即可复用方法。通用性不代表同一位流可以跨板使用。

本队主应用为裸机实现。PYNQ Skill 是独立附加工具，不能把它写成主应用已采用 PYNQ，也不能把主机合成测试写成 PYNQ 板级验收。是否获得加分由评审确定。

原有技能总览作为历史材料保存在 docs/legacy_skill_overview.md，并用于还原原始运行树；本目录索引以本文件为准。
