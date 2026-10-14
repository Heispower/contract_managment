@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo  合同与发票编号登记管理系统
echo  依赖会安装到本目录的 venv 和 packages
echo ========================================
set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py -3"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo 未找到 Python。请先安装 Python 3.10 或更高版本，并加入 PATH。
    pause
    exit /b 1
  )
)
if not exist "venv\Scripts\python.exe" (
  echo 正在创建本目录虚拟环境 venv ...
  !PY! -m venv venv
  if errorlevel 1 (
    echo 创建虚拟环境失败。
    pause
    exit /b 1
  )
)
if not exist "packages" mkdir packages
if not exist "logs" mkdir logs
if not exist "data" mkdir data
echo 正在下载依赖到 packages ...
venv\Scripts\python.exe -m pip install -U pip
venv\Scripts\python.exe -m pip download -r requirements.txt -d packages
if errorlevel 1 (
  echo 下载依赖失败，请检查网络后重试。
  pause
  exit /b 1
)
echo 正在把依赖安装进本项目 venv ...
venv\Scripts\python.exe -m pip install --no-index --find-links=packages -r requirements.txt
if errorlevel 1 (
  echo 安装失败。
  pause
  exit /b 1
)
echo.
echo 安装完成。
echo   venv      本项目运行环境
echo   packages  离线安装包
echo 接下来请双击“启动系统.bat”。
pause
