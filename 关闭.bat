@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not defined CONTRACT_PORT set "CONTRACT_PORT=8001"
set "PORT=%CONTRACT_PORT%"
echo 正在关闭合同管理系统，端口 %PORT%
powershell -NoProfile -Command "$ids = @(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); if ($ids.Count -eq 0) { Write-Host '当前没有服务在运行' } else { foreach ($id in $ids) { Stop-Process -Id $id -Force; Write-Host ('已结束进程 ' + $id) } }"
echo 关闭完成。
if /i not "%~1"=="nopause" pause
