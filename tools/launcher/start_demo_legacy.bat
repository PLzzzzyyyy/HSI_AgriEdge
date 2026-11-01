@echo off
chcp 936 >nul
setlocal EnableExtensions
title 农情分析 · 一键启动（板卡 + DP 显示器 + PC 控制台）

rem =====================================================================
rem  默认：下载固件 -> 起「原版控制台」(http://127.0.0.1:8765) -> 开浏览器
rem
rem  用法：
rem    START_DEMO.bat            完整：下载固件 + 原版控制台
rem    START_DEMO.bat skipload   板子已在跑：只起原版控制台
rem    START_DEMO.bat mini       改用精简版控制台 8770（自带单点探查，轻量）
rem    START_DEMO.bat ui         只起精简版 8770（板子已在跑、只改界面时用）
rem
rem  可选环境变量：
rem    HSI_PYTHON   指定 python.exe
rem    HSI_VITIS    指定 Vitis 目录（含 bin\xsdb.bat）
rem    HSI_WEBPORT  精简版端口，默认 8770
rem    HSI_NO_BROWSER=1   不自动开浏览器
rem    HSI_NOPAUSE=1      结束不等待按键
rem =====================================================================

set "MODE=%~1"
if "%MODE%"=="" set "MODE=console"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
rem 打包后 START_DEMO.bat 在包根目录；放在 tools\launcher 里调试时也能找到包根
if not exist "%ROOT%\tools\gcs_web.py" if exist "%ROOT%\..\..\tools\gcs_web.py" set "ROOT=%ROOT%\..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "SESSION=%HSI_SESSION%"
if "%SESSION%"=="" set "SESSION=5a5a0001"
set "WEBPORT=%HSI_WEBPORT%"
if "%WEBPORT%"=="" set "WEBPORT=8770"
set "CONSOLEPORT=8765"
if not defined GCS_LOCAL_DEMO_BUNDLE if exist "%ROOT%\build\host\gcs_pc_dp_link_20261017\manifest.json" set "GCS_LOCAL_DEMO_BUNDLE=%ROOT%\build\host\gcs_pc_dp_link_20261017"

echo ================================================================
echo   无人机高光谱张量农情分析系统 · AXU5EV-E 一键启动
echo   目录 %ROOT%
echo   模式 %MODE%
echo ================================================================
echo.

rem ---------- [1/4] Python ----------
set "PY="
if defined HSI_PYTHON if exist "%HSI_PYTHON%" set "PY=%HSI_PYTHON%"
if not defined PY if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY if exist "D:\Anaconda\python.exe" set "PY=D:\Anaconda\python.exe"
if not defined PY if exist "D:\Anaconda3\python.exe" set "PY=D:\Anaconda3\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
rem Vivado/Vitis 自带的 Python（<安装目录>\tps\win64\python-3.x）：队里只装了两个 V 的机器也能直接跑
if not defined PY for %%B in ("D:\AMDDesignTools" "C:\AMDDesignTools" "C:\AMD") do for /d %%D in ("%%~B\*") do if not defined PY for /d %%P in ("%%~fD\tps\win64\python-*") do if not defined PY if exist "%%~fP\python.exe" set "PY=%%~fP\python.exe"
if not defined PY for /d %%D in ("D:\AMD\*") do if not defined PY for /d %%P in ("%%~fD\tps\win64\python-*") do if not defined PY if exist "%%~fP\python.exe" set "PY=%%~fP\python.exe"
if not defined PY for /d %%D in ("C:\Xilinx\*") do if not defined PY for /d %%P in ("%%~fD\tps\win64\python-*") do if not defined PY if exist "%%~fP\python.exe" set "PY=%%~fP\python.exe"
if not defined PY for /d %%D in ("C:\Xilinx\Vitis\*") do if not defined PY for /d %%P in ("%%~fD\tps\win64\python-*") do if not defined PY if exist "%%~fP\python.exe" set "PY=%%~fP\python.exe"
if not defined PY for %%I in (python.exe) do if not defined PY if exist "%%~$PATH:I" set "PY=%%~$PATH:I"
if not defined PY (
    echo [错误] 没找到 python.exe。装 Vivado/Vitis 的机器自带（tps\win64\python-3.x），也可设 HSI_PYTHON 指向任意 Python 3。
    goto :fail
)
echo [1/4] Python  %PY%

rem ---------- [2/4] 下载固件 ----------
if /i "%MODE%"=="ui" (
    echo [2/4] 跳过下载（模式 ui）
    goto :after_download
)
if /i "%MODE%"=="skipload" (
    echo [2/4] 跳过下载（模式 skipload）
    goto :after_download
)
set "XSD="
if defined HSI_VITIS if exist "%HSI_VITIS%\bin\xsdb.bat" set "XSD=%HSI_VITIS%\bin\xsdb.bat"
if not defined XSD if defined XILINX_VITIS if exist "%XILINX_VITIS%\bin\xsdb.bat" set "XSD=%XILINX_VITIS%\bin\xsdb.bat"
if not defined XSD for %%I in (xsdb.bat) do if exist "%%~$PATH:I" set "XSD=%%~$PATH:I"
if not defined XSD for %%B in ("D:\AMDDesignTools" "C:\AMDDesignTools" "C:\AMD") do for /d %%D in ("%%~B\*") do if not defined XSD if exist "%%~fD\Vitis\bin\xsdb.bat" set "XSD=%%~fD\Vitis\bin\xsdb.bat"
if not defined XSD for /d %%D in ("D:\AMD\*") do if not defined XSD if exist "%%~fD\Vitis\bin\xsdb.bat" set "XSD=%%~fD\Vitis\bin\xsdb.bat"
if not defined XSD for /d %%D in ("C:\Xilinx\Vitis\*") do if not defined XSD if exist "%%~fD\bin\xsdb.bat" set "XSD=%%~fD\bin\xsdb.bat"
if not defined XSD (
    echo [错误] 没找到 xsdb.bat。装 Vitis 2026.1，或设 HSI_VITIS 指向 Vitis 目录。
    echo        板子已经在跑的话：START_DEMO.bat skipload
    goto :fail
)
for %%I in ("%XSD%\..\..") do set "HSI_VITIS=%%~fI"
echo [2/4] 下载固件（约 30~60 秒，板卡会复位；DP 会重新亮起来）
echo       Vitis %HSI_VITIS%
rem 必须用 call：xsdb.bat 是批处理，直接调用会把控制权交给它，后面步骤就不执行了
if not exist "%ROOT%\.runtime-tmp" mkdir "%ROOT%\.runtime-tmp"
set "HSI_DOWNLOAD_RESULT=%ROOT%\.runtime-tmp\download_%RANDOM%_%RANDOM%.ok"
call "%XSD%" "%ROOT%\tools\launcher\dl_gcs_demo.tcl"
if errorlevel 1 (
    echo [错误] 下载失败。检查：JTAG 线、板卡上电、SW1=0000、下载器驱动。
    goto :fail
)

rem xsdb.bat may discard the Tcl process exit code; require its success receipt.
if not exist "%HSI_DOWNLOAD_RESULT%" (
    echo [错误] 未收到固件下载成功回执，请检查上方 XSDB 错误。
    goto :fail
)
del /q "%HSI_DOWNLOAD_RESULT%" >nul 2>nul

:after_download
echo.

rem ---------- 精简版分支 ----------
if /i "%MODE%"=="mini" goto :mini
if /i "%MODE%"=="ui" goto :mini

rem ---------- [3/4] 依赖检查（原版控制台要 fastapi/uvicorn/pyserial/torch）----------
"%PY%" -c "import fastapi,uvicorn,serial,torch,numpy,scipy,websockets" 2>nul
if errorlevel 1 (
    echo [3/4] 原版控制台缺少依赖。执行下面这条安装（约 250 MB，只需一次）：
    echo       "%PY%" -m pip install fastapi "uvicorn[standard]" pyserial numpy scipy websockets torch --extra-index-url https://download.pytorch.org/whl/cpu
    goto :fail
)
echo [3/4] 依赖 OK

rem ---------- 板卡不能被两个控制台同时占 ----------
set "PORTBUSY="
for /f "delims=" %%L in ('netstat -ano ^| findstr ":%WEBPORT% " ^| findstr "LISTENING"') do set "PORTBUSY=1"
if defined PORTBUSY (
    echo [提示] 精简版控制台正在 :%WEBPORT% 上跑，它占着板卡的回包地址。
    echo        原版控制台连不上或任务起不来时，先把那个窗口关掉再重跑本脚本。
)

rem ---------- [4/4] 起原版控制台 ----------
set "PORTBUSY="
for /f "delims=" %%L in ('netstat -ano ^| findstr ":%CONSOLEPORT% " ^| findstr "LISTENING"') do set "PORTBUSY=1"
echo [4/4] 原版控制台 http://127.0.0.1:%CONSOLEPORT%/  （GCS_LOCAL_DEMO=1，本地演示模式）
if defined PORTBUSY (
    echo       端口 %CONSOLEPORT% 已在监听，直接复用已有窗口
) else (
    set "GCS_LOCAL_DEMO=1"
    start "原版控制台" /D "%ROOT%" "%PY%" -u "tools\gcs_roi.py" serve --port %CONSOLEPORT%
    echo       等控制台就绪（最多 40 秒）…
    "%PY%" "%ROOT%\tools\wait_http.py" --url "http://127.0.0.1:%CONSOLEPORT%/" --timeout 40 --quiet
    if errorlevel 1 goto :fail
)
if defined HSI_NO_BROWSER (
    echo       HSI_NO_BROWSER 已设置，不自动开浏览器
) else (
    start "" "http://127.0.0.1:%CONSOLEPORT%/"
)
goto :summary

rem ---------- 精简版：等板卡 -> 选权重 -> 起 8770 ----------
:mini
echo [3/4] 等板卡回 STATUS（最多 90 秒）…
"%PY%" "%ROOT%\tools\board_wait.py" --session %SESSION% --timeout 90
if errorlevel 1 (
    if /i not "%MODE%"=="ui" (
        echo [错误] 板卡没回包。检查网线、本机 IP 是否 192.168.1.102/24、防火墙。
        goto :fail
    )
    echo [警告] 没等到板卡，继续起网页
)
echo [4/4] 选权重并起精简版控制台 http://127.0.0.1:%WEBPORT%/
if /i not "%MODE%"=="ui" "%PY%" "%ROOT%\tools\board_model.py" --session %SESSION%
set "PORTBUSY="
for /f "delims=" %%L in ('netstat -ano ^| findstr ":%WEBPORT% " ^| findstr "LISTENING"') do set "PORTBUSY=1"
if defined PORTBUSY (
    echo       端口 %WEBPORT% 已在监听，直接复用
) else (
    start "精简版控制台" /D "%ROOT%" "%PY%" -u "tools\gcs_web.py" --no-browser --web-port %WEBPORT% --session %SESSION%
    timeout /t 5 >nul
)
if defined HSI_NO_BROWSER (
    echo       HSI_NO_BROWSER 已设置，不自动开浏览器
) else (
    start "" "http://127.0.0.1:%WEBPORT%/"
)

:summary
echo.
echo ================================================================
if /i "%MODE%"=="mini" goto :summary_mini
if /i "%MODE%"=="ui" goto :summary_mini
echo   启动结果（DP 以显示器实际画面为准）：
echo     · DP 显示器：初始化成功后显示板卡界面（地图 / 图例 / 任务卡 / 遥测）
echo     · PC 控制台：http://127.0.0.1:%CONSOLEPORT%/
echo.
echo   控制台里依次点：
echo     1) 「连接板卡」- 启动方式选 JTAG
echo     2) 「链路与下发」里查权重、必要时激活
echo     3) 框选区域或选整景 - 「开始」
echo     4) 跑完在地图上点任意一点 = 单点探查（含注意力热力图）
echo.
echo   注意：本地演示模式，未做发布审查，产物不能当验收证据。
echo   要用精简版（8770）：START_DEMO.bat mini  （与原版不能同时连板卡）
goto :summary_end
:summary_mini
echo   精简版控制台：http://127.0.0.1:%WEBPORT%/
echo   区域选 64x64 点「开始」最快（约 18 秒）；整幅 LongKou 约 16 分钟。
echo   地图上点任意一点 = 单点探查。
:summary_end
echo ================================================================
echo.
if not defined HSI_NOPAUSE pause
exit /b 0

:fail
echo.
echo 启动失败，按上面的提示处理；详细排查见 README_运行说明.md 与手册第 8 章。
if not defined HSI_NOPAUSE pause
exit /b 1
