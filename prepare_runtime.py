"""安装依赖.bat 第 7、8 步：建目录、写字段清单、初始化数据库。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

from backend.app.main import startup
from backend.app.services.export_profile import build_field_workbook, template_dir

(ROOT / "data" / "uploads").mkdir(parents=True, exist_ok=True)
field_file = template_dir() / "表单字段.xlsx"
field_file.write_bytes(build_field_workbook())
print("项目绝对路径", ROOT)
print("已准备", field_file)
startup()
print("数据库已就绪")
