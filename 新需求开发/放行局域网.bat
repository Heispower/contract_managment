@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "PORT=6688"
if exist "data\port.txt" set /p PORT=<"data\port.txt"
netsh advfirewall firewall delete rule name="合同发票编号系统" >nul 2>&1
netsh advfirewall firewall add rule name="合同发票编号系统" dir=in action=allow protocol=TCP localport=%PORT% profile=any
if errorlevel 1 (
  echo 放行失败。请确认已点“是”允许管理员权限。
) else (
  echo 已放行 TCP %PORT%，同一局域网的电脑可以访问。
)
pause
