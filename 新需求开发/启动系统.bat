@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo 尚未安装依赖，请先双击“一键安装依赖.bat”。
  pause
  exit /b 1
)
if not exist "logs" mkdir logs
if not exist "data" mkdir data
echo 正在启动，请勿关闭本窗口。关闭系统请另开“关闭系统.bat”。
echo.
venv\Scripts\python.exe run.py
echo.
echo 服务已停止。
pause
