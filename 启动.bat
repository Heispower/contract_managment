@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "ROOT=%CD%"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"
set "PYEXE=%ROOT%\.venv\Scripts\python.exe"
set "PORT="

echo 项目绝对路径：%ROOT%

if exist "%PYEXE%" goto have_python
if exist "%ROOT%\pydeps\" (
    set "PYTHONPATH=%ROOT%\pydeps"
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)
if exist "%PYEXE%" goto have_python
echo 还没有安装依赖。请先双击 安装依赖.bat，完成后再启动。
if /i not "%~1"=="nopause" pause
exit /b 1

:have_python
if not exist "%ROOT%\frontend\dist\index.html" (
    echo 前端尚未构建。请先双击 安装依赖.bat，完成后再启动。
    if /i not "%~1"=="nopause" pause
    exit /b 1
)

if not defined CONTRACT_PORT set "CONTRACT_PORT=8001"
set "PORT=%CONTRACT_PORT%"

powershell -NoProfile -Command "$ids = @(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach ($id in $ids) { if ($id) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } }" >nul 2>&1

echo 合同管理系统启动中。本机 http://127.0.0.1:%PORT%
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%B in ("%%A") do echo 局域网 http://%%B:%PORT%
)
netsh advfirewall firewall add rule name="合同管理系统%PORT%" dir=in action=allow protocol=TCP localport=%PORT% profile=any >nul 2>&1
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:%PORT%/"
"%PYEXE%" -m uvicorn backend.app.main:app --host 0.0.0.0 --port %PORT%
if errorlevel 1 echo 启动失败。请先运行 安装依赖.bat，或双击 关闭.bat 后再试。
if /i not "%~1"=="nopause" pause
