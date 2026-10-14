@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PORT=6688"
if exist "data\server.pid" (
  for /f "usebackq delims=" %%i in ("data\server.pid") do taskkill /PID %%i /F >nul 2>nul
  del /f /q "data\server.pid" >nul 2>nul
)
if exist "data\port.txt" (
  for /f "usebackq delims=" %%i in ("data\port.txt") do set "PORT=%%i"
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%"') do (
  echo %%a | findstr /r "^[0-9][0-9]*$" >nul && taskkill /PID %%a /F >nul 2>nul
)
echo 已关闭端口 %PORT% 上的系统进程。
pause
