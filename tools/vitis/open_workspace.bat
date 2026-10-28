@echo off
rem Open one of the repo 2026.1 Vitis workspaces.
rem Vitis is searched under D:\AMD\<version> (e.g. D:\AMD\2026.1);
rem override with TT_AMD_ROOT or TT_VITIS_ROOT.
rem Usage: tools\vitis\open_workspace.bat [M1|C3|M2|M3A|<workspace dir name>]
setlocal

set "REPO=%~dp0..\.."
pushd "%REPO%" >nul
set "REPO=%CD%"
popd >nul

set "VITIS="
if defined TT_VITIS_ROOT set "VITIS=%TT_VITIS_ROOT%\bin\vitis.bat"
if defined VITIS if exist "%VITIS%" goto :vitis_ready

set "AMD_ROOT=D:\AMD"
if defined TT_AMD_ROOT set "AMD_ROOT=%TT_AMD_ROOT%"
for /f "delims=" %%d in ('dir /b /ad /o-n "%AMD_ROOT%" 2^>nul') do (
  if not defined VITIS if exist "%AMD_ROOT%\%%d\Vitis\bin\vitis.bat" set "VITIS=%AMD_ROOT%\%%d\Vitis\bin\vitis.bat"
)
if not defined VITIS goto :no_vitis

:vitis_ready
set "WS=%~1"
if not defined WS set "WS=chk_m1_20261016b"
if /I "%WS%"=="M1"  set "WS=chk_m1_20261016b"
if /I "%WS%"=="C3"  set "WS=periph_ws_20261016"
if /I "%WS%"=="M2"  set "WS=chk_m2_20261016b"
if /I "%WS%"=="M3A" set "WS=chk_m3a_20261016"

set "DIR=%REPO%\build\board\%WS%"
if not exist "%DIR%" (
  echo [ERROR] workspace not found: %DIR%
  echo         available: chk_m1_20261016b  periph_ws_20261016  chk_m2_20261016b  chk_m3a_20261016
  exit /b 1
)

echo Opening Vitis workspace: %DIR%
echo Vitis: %VITIS%
call "%VITIS%" -w "%DIR%"
endlocal
exit /b 0

:no_vitis
echo [ERROR] Vitis not found under "%AMD_ROOT%\<version>\Vitis\bin\vitis.bat"
echo         set TT_VITIS_ROOT=D:\your_install\Vitis if installed elsewhere
endlocal
exit /b 1