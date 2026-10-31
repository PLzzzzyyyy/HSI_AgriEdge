# 通用 PYNQ Overlay 接口契约预检

## 1. 适用范围

面向 PYNQ 的 Overlay / ip_dict 工作流。在更换题目、IP 或板卡后，检查期望的 IP 路径、VLNV 版本、最小 AXI 地址范围及参数是否匹配。没有固定物理基址、农情模型、AXU5EV-E 或本队应用依赖。完整目录可独立复制到另一项目，采用本项目原创部分的 MIT 许可。

离线模式只需 Python 3 标准库；PYNQ 模式需已支持目标板的 PYNQ 环境及该板对应的 `.bit` 和同名 `.hwh`。不能把本队裸机位流直接当成通用 PYNQ Overlay。

## 2. 使用方法

从仓库根目录执行两个不同设计的离线示例：

```text
python skill/pynq_overlay_contract/inspect_overlay.py --contract skill/pynq_overlay_contract/examples/accelerator_contract.json --ip-dict skill/pynq_overlay_contract/examples/accelerator_ip_dict.json
python skill/pynq_overlay_contract/inspect_overlay.py --contract skill/pynq_overlay_contract/examples/gpio_contract.json --ip-dict skill/pynq_overlay_contract/examples/gpio_ip_dict.json
python skill/pynq_overlay_contract/test_contract.py
```

预期：两个示例 result=PASS，scope=OFFLINE_IP_DICT_CONTRACT_NOT_BOARD_VALIDATION；测试退出 0。用 accelerator 合同检查 gpio 元数据则退出 1，提示缺少 IP。

真实 PYNQ 环境：复制示例合同并填写实际 IP 路径、VLNV、必要参数；用标准库 hashlib 计算自己配套 bit/hwh 的 SHA256，写入合同 `assets.bit_sha256` / `assets.hwh_sha256`，再执行：

```text
python inspect_overlay.py --contract my_contract.json --bitfile /path/to/my_overlay.bit
```

脚本先检查文件哈希，再调用 `Overlay(bitfile, download=False)`，只读取 `ip_dict`。本工具不下载位流、不启动 IP、不访问 MMIO。PYNQ 初始化本身仍需要合适设备和运行时，不承诺完全不触达设备。正常结果 scope=PYNQ_METADATA_ONLY_NO_DOWNLOAD_OR_MMIO。记录 PYNQ 版本、板卡、合同、bit/hwh 哈希及完整 JSON，才能证明该实际设计的预检结果。

## 3. 失效条件

- 元数据正确不证明电路功能、时序、DMA、缓存或数据流正确，也不能确认板上已经加载的是该位流。
- 要求完整明确 VLNV；跨版本驱动兼容性不能仅靠放宽版本检查推定。
- 参数名称和表示来自实际 ip_dict；不同工具版本若改变参数表示，需人工检查并调整合同。
- 仅支持完整 Overlay 元数据检查，不处理部分重配置、设备树安装或可重配置分区切换。
- 合成 JSON 可以伪造，因此离线 PASS 只说明合同检查器工作，不能当真板验证。
- 必须使用适合目标板的位流与 PYNQ 环境；“通用”指脚本和合同方法可迁移，不指位流跨板兼容。

## 4. 已验证效果

2026-11-01 在 Windows 主机 Python 上完成标准库测试：两个不相关的合成设计（向量加速器、层级 GPIO）、基址迁移、缺失 IP、错误版本、地址范围不足/未对齐/无效类型、参数不符、bit/hwh 哈希不符，以及真实 CLI 的正确退出码。适配器替身验证 Overlay 构造显式使用 download=False，且哈希失败发生在构造前。

本次没有 PYNQ 真板、没有真实 Overlay 下载或实际 IP 功能测试。验证回执 `validation.json` 记录测试数量与范围。该技能可作为通用 PYNQ 技能材料提交，是否获得加分由赛事评审决定；不能宣称已完成多板真机验证。

## 5. 提炼来源与官方接口依据

来自本项目反复遇到的“工程文件存在但接口/产物版本不配对”“返回码或元数据通过不等于硬件功能通过”的观察，抽象为题目无关的接口合同和可失败检查；它是 2026-11-01 新增扩展，不能倒填到此前已验证 Skill 历史。

官方接口依据（2026-11-01 查阅）：

- [PYNQ Overlay 文档](https://pynq.readthedocs.io/en/latest/pynq_libraries/overlay.html)
- [pynq.overlay API](https://pynq.readthedocs.io/en/latest/pynq_package/pynq.overlay.html)

真实用户日志见仓库 `report/llm_log/20261101_submission.md`，本次验证失败和修正按实际记录保留。
