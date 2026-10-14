@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "ROOT=%CD%"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo.
echo ========================================
echo   合同管理系统 - 首次安装
echo ========================================
echo 项目绝对路径：%ROOT%
echo.

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_USER=no"
set "PIP_CACHE_DIR=%ROOT%\deps-cache\pip"
set "NPM_CONFIG_FUND=false"
set "NPM_CONFIG_AUDIT=false"
set "NPM_CONFIG_CACHE=%ROOT%\deps-cache\npm"
set "npm_config_cache=%ROOT%\deps-cache\npm"
set "npm_config_prefix=%ROOT%\deps-cache\npm-prefix"
set "TMP=%ROOT%\deps-cache\tmp"
set "TEMP=%ROOT%\deps-cache\tmp"
set "PYEXE=%ROOT%\.venv\Scripts\python.exe"
set "VENVDIR=%ROOT%\.venv"
set "REQ=%ROOT%\requirements.txt"
set "FRONT=%ROOT%\frontend"
set "DIST=%FRONT%\dist\index.html"
set "PREPARE=%ROOT%\prepare_runtime.py"
set "PY="
set "NODE_OK="

if not exist "%ROOT%\deps-cache\pip" mkdir "%ROOT%\deps-cache\pip"
if not exist "%ROOT%\deps-cache\npm" mkdir "%ROOT%\deps-cache\npm"
if not exist "%ROOT%\deps-cache\npm-prefix" mkdir "%ROOT%\deps-cache\npm-prefix"
if not exist "%ROOT%\deps-cache\tmp" mkdir "%ROOT%\deps-cache\tmp"

echo [1/8] 检查 Python 3.10+
call :find_sys_python
if defined PY goto python_ready
echo 未找到 Python，尝试用 winget 安装 Python 3.12 ...
call :install_python
call :refresh_path
call :find_sys_python
if defined PY goto python_ready
echo 安装失败：需要 Python 3.10 或更高版本。
echo 请安装 Python，勾选 Add python.exe to PATH，然后重新运行本脚本。
echo https://www.python.org/downloads/
goto fail
:python_ready
echo     使用 Python：%PY%
"%PY%" --version
if errorlevel 1 goto fail

echo.
echo [2/8] 检查 Node.js / npm
call :find_node
if defined NODE_OK goto node_ready
echo 未找到 Node.js，尝试用 winget 安装 Node.js LTS ...
call :install_node
call :refresh_path
call :find_node
if defined NODE_OK goto node_ready
echo 安装失败：需要 Node.js LTS。
echo https://nodejs.org/
goto fail
:node_ready
echo     node / npm 已就绪
node --version
call npm.cmd --version
if errorlevel 1 goto fail

echo.
echo [3/8] 停止已在运行的本系统服务，避免文件被占用
call :stop_server

echo.
echo [4/8] 在项目目录创建虚拟环境
echo     %VENVDIR%
if exist "%PYEXE%" goto venv_ready
"%PY%" -m venv "%VENVDIR%"
if errorlevel 1 (
    echo 创建虚拟环境失败，尝试补装 pip 后再试 ...
    "%PY%" -m ensurepip --upgrade
    "%PY%" -m venv "%VENVDIR%"
)
if not exist "%PYEXE%" (
    echo 创建虚拟环境失败。请确认 Python 安装时带有 venv 和 pip。
    goto fail
)
:venv_ready
echo     虚拟环境：%PYEXE%

echo.
echo [5/8] 把 Python 依赖安装到项目目录
echo     包目录：%VENVDIR%
echo     pip 缓存：%PIP_CACHE_DIR%
"%PYEXE%" -m ensurepip --upgrade >nul 2>&1
"%PYEXE%" -m pip install --upgrade pip setuptools wheel --cache-dir "%PIP_CACHE_DIR%"
if errorlevel 1 goto pip_mirror
"%PYEXE%" -m pip install -r "%REQ%" --cache-dir "%PIP_CACHE_DIR%"
if errorlevel 1 goto pip_mirror
goto pip_ok
:pip_mirror
echo     默认源失败，改用清华镜像重试 ...
"%PYEXE%" -m pip install --upgrade pip setuptools wheel --cache-dir "%PIP_CACHE_DIR%" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
if errorlevel 1 goto fail
"%PYEXE%" -m pip install -r "%REQ%" --cache-dir "%PIP_CACHE_DIR%" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
if errorlevel 1 goto fail
:pip_ok
echo     正在校验关键模块 ...
"%PYEXE%" -c "import fastapi,uvicorn,sqlalchemy,jwt,argon2,openpyxl,lxml,httpx,xlrd,multipart"
if errorlevel 1 (
    echo Python 依赖安装后仍无法导入，请把上面的报错发出来。
    goto fail
)

echo.
echo [6/8] 把前端依赖安装到项目目录并构建
echo     包目录：%FRONT%\node_modules
echo     npm 缓存：%NPM_CONFIG_CACHE%
cd /d "%FRONT%"
if exist "%FRONT%\package-lock.json" (
    call npm.cmd ci --prefix "%FRONT%" --cache "%NPM_CONFIG_CACHE%"
    if errorlevel 1 call npm.cmd ci --prefix "%FRONT%" --cache "%NPM_CONFIG_CACHE%" --registry https://registry.npmmirror.com
    if errorlevel 1 call npm.cmd install --prefix "%FRONT%" --cache "%NPM_CONFIG_CACHE%"
) else (
    call npm.cmd install --prefix "%FRONT%" --cache "%NPM_CONFIG_CACHE%"
)
if errorlevel 1 (
    echo     默认 npm 源失败，改用 npmmirror 重试 ...
    call npm.cmd install --prefix "%FRONT%" --cache "%NPM_CONFIG_CACHE%" --registry https://registry.npmmirror.com
)
if errorlevel 1 goto fail
call npm.cmd run build --prefix "%FRONT%"
if errorlevel 1 goto fail
cd /d "%ROOT%"
if not exist "%DIST%" (
    echo 前端构建完成，但找不到 frontend\dist\index.html
    goto fail
)

echo.
echo [7/8] 创建运行目录
echo [8/8] 生成字段清单并初始化数据库
"%PYEXE%" "%PREPARE%"
if errorlevel 1 goto fail

echo.
echo ========================================
echo   安装完成。依赖都在项目目录内：
echo   %ROOT%\.venv
echo   %FRONT%\node_modules
echo   以后直接双击 启动.bat
echo   浏览器打开 http://127.0.0.1:8001
echo   演示账号 admin / 123456
echo ========================================
echo.
if /i not "%~1"=="nopause" pause
exit /b 0

:fail
echo.
echo 安装失败。请确认：
echo   1. 已安装 Python 3.10+ 和 Node.js LTS，并加入 PATH
echo   2. 本机可以访问互联网（下载 pip / npm 包）
echo   3. 关闭杀毒软件对项目目录的拦截后重试
echo.
if /i not "%~1"=="nopause" pause
exit /b 1

:find_sys_python
set "PY="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
    goto :eof
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "PY=%%I"
    goto :eof
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PY=%LocalAppData%\Programs\Python\Python313\python.exe"
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" set "PY=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
goto :eof

:find_node
set "NODE_OK="
where node >nul 2>&1
if errorlevel 1 goto :eof
where npm >nul 2>&1
if errorlevel 1 goto :eof
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" 2>nul
if errorlevel 1 (
    echo     当前 Node.js 版本过低，需要 18 或更高。
    goto :eof
)
set "NODE_OK=1"
goto :eof

:install_python
where winget >nul 2>&1
if errorlevel 1 (
    echo     本机没有 winget，无法自动安装 Python。
    goto :eof
)
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
goto :eof

:install_node
where winget >nul 2>&1
if errorlevel 1 (
    echo     本机没有 winget，无法自动安装 Node.js。
    goto :eof
)
winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
goto :eof

:refresh_path
set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%LocalAppData%\Python\pythoncore-3.14-64;%ProgramFiles%\nodejs;%ProgramFiles(x86)%\nodejs;%PATH%"
goto :eof

:stop_server
powershell -NoProfile -Command "$ports = 8001; $envPort = [Environment]::GetEnvironmentVariable('CONTRACT_PORT'); if ($envPort) { $ports = [int]$envPort }; $ids = @(Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach ($id in $ids) { if ($id) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } }"
goto :eof
