"""路径与运行参数。数据库、上传文件都落在项目目录内。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 固定 8001。8000 已被本机其他程序占用。
PORT = int(os.environ.get("CONTRACT_PORT", "8001"))
DB_PATH = os.environ.get("CONTRACT_DB", str(DATA_DIR / "contract.db"))
JWT_SECRET = os.environ.get("CONTRACT_JWT_SECRET", "contract-system-local-secret-key-32")
JWT_HOURS = 24
# demo：允许管理员使用种子密码。formal：首次登录强制修改 admin 默认密码。
DEPLOY_MODE = os.environ.get("CONTRACT_DEPLOY_MODE", "demo")
