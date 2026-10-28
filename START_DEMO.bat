@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
if not exist "%ROOT%tools\launcher\start_demo.py" set "ROOT=%~dp0..\..\"
for %%I in ("%ROOT%.") do set "ROOT=%%~fI"
if /i "%~1"=="mini" goto :legacy
if /i "%~1"=="ui" goto :legacy
set "PY=%ROOT%\.venv\Scripts\python.exe"
if defined HSI_PYTHON set "PY=%HSI_PYTHON%"
if not exist "%PY%" (
    echo ERROR: Python environment not found: %PY%
    pause
    exit /b 1
)
"%PY%" -u "%ROOT%\tools\launcher\start_demo.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" if not defined HSI_NOPAUSE pause
exit /b %RESULT%
:legacy
call "%ROOT%\tools\launcher\START_DEMO_legacy.bat" %*
exit /b %ERRORLEVEL%
