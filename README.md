# HSI_AgriEdge

## 2026-11-01 正式提交材料

原创代码和文档采用 [MIT License](LICENSE)，第三方来源见 [说明](docs/third_party_notices.md)。新增 [16 页设计报告](report/design_report.pdf)、实现/实测证据，以及 [通用 PYNQ Overlay 接口契约预检](skill/pynq_overlay_contract/readme.md)。PYNQ Skill 已通过 7 项主机合成测试，尚无 PYNQ 真板验证；本项目主应用仍为裸机。

正式代码 ZIP：[submission-20261101 Release](https://github.com/PLzzzzyyyy/HSI_AgriEdge/releases/tag/submission-20261101)。ZIP 以 hsi_agriedge/ 为单项目根，直接包含 src/、sim/、build/、board/、data/、skill/、report/；英文小写文件名与原始布局之间可逆映射。报告的提交包复现步骤面向该 ZIP；本 GitHub 工作树保留既有文件名和运行身份，按下方原始环境步骤启动。数据附件继续使用 snapshot-20261028 Release。


无人机高光谱张量农情分析系统：基于 Zynq UltraScale+ 的张量 Transformer 边缘分类、PC 地面站与 DP 显示联动工程。

本仓库是 **2026-10-28 整理的工程快照**，主要取自当前 `HSI_AgriEdge_team_20261017` 工作目录，包含截至 10 月 26 日的板端和地面站代码，以及配套的本地演示固件。当前入口为根目录 `START_DEMO.bat`。原始运行记录保存在 [docs/original_run_notes.md](docs/original_run_notes.md)，其中旧目录、旧固件优先级及旧 Python 寻找方式以本说明和当前代码为准。

当前配套固件位于 `firmware/keys_20261018/`，身份文件为 `build/host/gcs_offline_keys_20261026_v4/manifest.json`，release ID 为 `2c861dad3ec37fbcbfcd5a08dcc56aae62d1aec2b342007f1bbaf04041b59094`。这些既有固件、身份清单和源码资产按原字节保留。其状态是 `LOCAL_DEMO_CANDIDATE_NOT_RELEASE_AUDIT`；本次整理只做文件完整性检查，未执行新电脑移植、硬件验收、固件重编译或板卡下载。

## 目录与数据附件

| 内容 | 位置 |
|---|---|
| 一键启动 | `START_DEMO.bat`、`tools/launcher/` |
| HLS、RTL、PS 应用源码 | `src/` |
| PC 后端、网页和协议 | `gcs/`、`tools/` |
| 模型及训练、导出脚本 | `model/` |
| 当前固件和本地演示身份 | `firmware/`、`build/host/gcs_offline_keys_20261026_v4/` |
| 说明、手册、已有验证记录 | `docs/`、`manual/`、`report/` |
| 文件校验清单 | `package_manifest.json`、`data_manifest.json` |

三场景输入立方体、权重和相关数据在独立附件 **`HSI_AgriEdge_data_20261028.zip`** 中。发布后从同仓库 **Releases → snapshot-20261028** 下载；本地整理包中该 ZIP 与工程文件夹并列。将它解压到仓库根目录，最终应出现 `data/scenes/longkou/`、`data/scenes/honghu/`、`data/scenes/hanchuan/`、`data/ckpt/` 等路径，避免多套一层目录。数据约 1.12 GiB，未加入普通 Git 源码历史。

**SD 卡内容不在本包内。** 现有板卡演示依赖已正确准备的 SD 卡；解压 PC 数据附件不等于完成 SD 卡制作、启动镜像生成或掉电启动验证。原始数据及上游模型的使用和再分发仍应遵守各自来源要求，本快照不新增授权声明。

## 重建 Python 环境

原机使用 Windows、Python 3.13.0，虚拟环境不随仓库复制。在仓库根目录打开 PowerShell：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe verify_package.py
# 解压数据附件后执行完整数据校验：
.\.venv\Scripts\python.exe verify_package.py --with-data
```

`requirements.txt` 的核心版本取自原机环境元数据，Torch 固定为 `+cpu` 构建，使用官方 CPU wheel 索引；它不会默认请求 CUDA 版。依赖在另一台电脑上的重新下载与安装未在本次打包中验证。Pillow 用于地块名称绘制；历史绘图和视频脚本另需 matplotlib 或 opencv-python。

`verify_package.py` 只使用 Python 标准库，读取并校验文件。它不导入产品、不启动网页服务、不连接串口或板卡。默认允许尚未安装的数据，并明确报告待安装；`--with-data` 要求数据清单全部存在且哈希一致。它的通过结果只代表包中文件与记录一致。

## 启动现有演示

所需硬件为 ALINX AXU5EV-E、DC12V 电源、JTAG、以太网、DP 显示链路及已准备好的 SD 卡。原演示配置为 PC 网口 `192.168.1.102/24`、板卡 PS JTAG 启动；实际接线及固件下载步骤见已有运行记录。

安装匹配的 Vitis/XSDB 与驱动后运行：

```powershell
# 按实际安装位置设置，不要照抄示例目录：
$env:HSI_VITIS = 'D:\AMDDesignTools\2026.1\Vitis'
.\START_DEMO.bat

# 已有固件在板卡上运行，只启动或打开地面站：
.\START_DEMO.bat skipload
```

默认启动器使用 `.venv/Scripts/python.exe`。需要使用其他已装齐依赖的解释器时，设置 `$env:HSI_PYTHON = 'C:\实际路径\python.exe'`。`HSI_VITIS` 指向包含 `bin/xsdb.bat` 的 Vitis 目录；启动器也会搜索若干常见目录。`HSI_NO_BROWSER=1` 可取消自动打开浏览器。网页地址为 `http://127.0.0.1:8765/`，日志写入 `.runtime-tmp/`。

直接运行 `START_DEMO.bat` 会尝试复位及下载板卡；`skipload` 会启动服务而不重新下载固件。启动器为已有演示使用 `GCS_LOCAL_DEMO=1` 并根据 `deployment.json` 选择配套身份，不代表已完成正式发布审查。

## 迁移与重编译限制

- `model/scenes.py` 的 `UPSTREAM` 及部分 `data/scenes/*/weights/*/board_model.json` 仍引用原机的 `D:/FPGAlearn/`、`D:/HSI_AgriEdge/` 等绝对路径。涉及上游模型推理、训练或重新导出时须核对实际模型位置；仅解压附件不能保证这些功能已经迁移完成。
- 当前地块名称绘制还依赖 Windows 字体 `C:/Windows/Fonts/NotoSansSC-VF.ttf`；代码可能优先使用原机的 Codex 缓存 Python。新电脑需检查字体、解释器及 Pillow，相关路径未在本次整理中修改。
- `build/` 和 `vitis/` 仅保留本快照所需的身份、源码引用和脚本，不是完整的可直接打开并编译的历史工作区。不同版本固件与工具链的具体情况见原始说明。
- 修改 `src/`、`gcs/`、`model/` 或被清单引用的工具会改变身份校验。应按工程的候选登记与固件流程生成新身份；不要为绕过校验而覆盖旧 manifest。原始板测记录仍只代表其记录的版本和条件。

## 发布到自己的 GitHub

本地整理结果不自动等同于在线仓库。安装官方 [GitHub CLI](https://cli.github.com/)，使用自己的账号登录：

```powershell
gh auth login --hostname github.com
powershell -NoProfile -ExecutionPolicy Bypass -File .\PUBLISH_GITHUB.ps1
```

脚本默认新建当前登录用户的公开仓库 `HSI_AgriEdge`，只提交本包清单内文件并推送，再把父目录的 `HSI_AgriEdge_data_20261028.zip` 上传到 `snapshot-20261028` Release。可用 `-Repository 用户名/HSI_AgriEdge` 明确目标。它不会自动安装工具、创建令牌、覆盖已有远端或强制推送；遇到不匹配会停止。成功后输出实际仓库和 Release 链接。

重复运行会保留同名数据附件；若同名文件体积不同则停止。GitHub 身份、网络访问和公开创建权限需要在执行机器上可用。请使用脚本最终输出的真实 URL 分享，勿将示例仓库名当作已发布链接。
