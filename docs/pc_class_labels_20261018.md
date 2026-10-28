# PC 三景类别中文显示

PC 的龙口、洪湖、汉川统一使用中文类别，共 9、22、16 类。图例、光标、单点结果及概率轴、种植结构、地块台账、每类精度和混淆矩阵、闭环对比图，以及农情导出报告均使用同一顺序的中文显示名。

词表在 `gcs/class_labels_zh.json`，每项绑定原始 0 基类别编号、英文名称和颜色。`gcs/display_labels.py` 校验顺序及颜色后提供翻译；`/api/scene/{name}` 保留原 `classes`，另附 `display_classes`。模型、调色板原文件和原始板端 CLASS 不改。页面的 `clsName()` / `classNames()` 统一使用中文显示字段。

洪湖、汉川名称与已部署 DP 中文词表一致。洪湖蔬菜使用英文类名的对应显示译名，例如小白菜、青菜、小青菜仍是三个独立类别，不合并 ID。

验证：`tools/tests/test_display_labels.py` 检查 47 类与 DP 对齐、原始字段不变和错误顺序/颜色拒绝；`tools/tests/test_class_names.js` 执行实际前端名称函数并检查概率、评测和闭环图表入口；原按键下发与单点流程回归通过。配套 App 编译通过、0 应用警告。

中文显示首次配套包为 `build/host/gcs_keys_pc_zh_20261018_v4`，身份为 `53811d65287758438ddb10adc4ca69141e1c94d63cb6bda7171403e4bc82e337`。随后更新到 `build/host/gcs_cross_scene_probe_20261018_v5`，修复切景后的单点任务绑定，继续保留本中文词表。PS 源集合及硬件 XSA 相同，重新构建用于绑定更新后的 PC 资产身份。详见 `docs/cross_scene_probe_20261018.md`；旧版套件备份在 `firmware/keys_20261018_v3`、`firmware/keys_20261018_v4`。

应用后在 PC 网页按 Ctrl+F5 刷新，再切换场景即可查看。此为本地演示构建，沿用原按键操作与 DP 布局。
