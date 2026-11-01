# 随包测试输入与参考结果

single_pixel/ 中提供同板 PS/PL 单像素测试的归一化输入、原始返回结构和分析结果，其内容与 report/evidence/s01_single_pixel 中的冻结证据一致。

python tools/verify_submission.py 会从原始 ticks、logits 和混淆矩阵离线复算报告数字。它不导入产品服务，不操作板卡。

完整三景立方体和模型附件位于 GitHub 的 snapshot-20261028 Release。PC 大数据与 SD 镜像不重复加入受 200 MB 限制的代码交付包。
