@echo off
rem ---------------------------------------------------------------------------
rem 用正确的许可证层启动 Vivado 2026.1（打开 ZU5EV 工程需要 BASIC 层）
rem
rem 工具位置：默认在本机 D:\AMD 下的版本目录里自动查找（例如 D:\AMD\2026.1），
rem           也可以用 TT_AMD_ROOT / TT_VIVADO_ROOT 指到别处。
rem
rem 背景：本机 license 文件里同时含 ALVEO 与 BASIC 两层，Vivado 默认挑 ALVEO，
rem       于是只认 Alveo 板卡，打开本项目工程会报 part not found。
rem       本脚本先把 BASIC 层单独写成副本，再用 XILINXD_LICENSE_FILE 指过去。
rem       原许可证文件不会被修改。
rem
rem 用法： tools\vivado\launch_vivado.bat            只开 Vivado
rem        tools\vivado\launch_vivado.bat <工程.xpr>  顺带打开某个工程
rem ---------------------------------------------------------------------------
setlocal

set "REPO=%~dp0..\.."
pushd "%REPO%" >nul
set "REPO=%CD%"
popd >nul

rem ---- 找 Vivado：TT_VIVADO_ROOT > D:\AMD\<版本> 里最新的一个 ----
set "VIVADO="
if defined TT_VIVADO_ROOT set "VIVADO=%TT_VIVADO_ROOT%\bin\vivado.bat"
if defined VIVADO if exist "%VIVADO%" goto :vivado_ready

set "AMD_ROOT=D:\AMD"
if defined TT_AMD_ROOT set "AMD_ROOT=%TT_AMD_ROOT%"
for /f "delims=" %%d in ('dir /b /ad /o-n "%AMD_ROOT%" 2^>nul') do (
  if not defined VIVADO if exist "%AMD_ROOT%\%%d\Vivado\bin\vivado.bat" set "VIVADO=%AMD_ROOT%\%%d\Vivado\bin\vivado.bat"
)
if not defined VIVADO goto :no_vivado

:vivado_ready
set "LIC=%REPO%\build\host\lic\vivado_basic.lic"
if exist "%LIC%" goto :lic_ready

echo [1/2] 生成 BASIC 层许可证副本 ...
set "PY=D:\Anaconda\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%REPO%\tools\vivado\make_basic_license.py"
if errorlevel 1 exit /b 1

:lic_ready
set "XILINXD_LICENSE_FILE=%LIC%"
echo [2/2] 启动 Vivado：%VIVADO%
echo       工程里的器件请用 xczu5ev-sfvc784-2-i（与板卡一致）

if "%~1"=="" (
  call "%VIVADO%"
) else (
  call "%VIVADO%" "%~f1"
)
endlocal
exit /b 0

:no_vivado
echo [错误] 没找到 Vivado。
echo        默认会在 "%AMD_ROOT%\<版本>\Vivado\bin\vivado.bat" 里找；
echo        装在别处请先 set TT_VIVADO_ROOT=D:\你的安装目录\Vivado
endlocal
exit /b 1