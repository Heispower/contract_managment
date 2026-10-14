import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.utils import lan_ipv4


def process_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def pick_port(preferred):
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    raise SystemExit("从首选端口起连续 30 个端口都被占用，请先关闭占用程序后重试。")


def print_urls(port):
    print(f"本机访问：http://127.0.0.1:{port}")
    hosts = lan_ipv4()
    if hosts:
        print("局域网访问：" + "    ".join(f"http://{host}:{port}" for host in hosts))
        print("同一局域网的电脑用上面的局域网地址打开。")
    else:
        print("未检测到局域网地址。其他电脑暂时只能在本机打开。")


def allow_firewall(port):
    if os.name != "nt":
        return
    name = "合同发票编号系统"
    kwargs = {"capture_output": True}
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
        **kwargs,
    )
    result = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={port}",
            "profile=any",
        ],
        **kwargs,
    )
    if result.returncode != 0:
        print("防火墙未自动放行。若其他电脑打不开，请双击“放行局域网.bat”并允许管理员权限。")


def main():
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    pid_file = data / "server.pid"
    port_file = data / "port.txt"
    if pid_file.exists():
        old = pid_file.read_text(encoding="utf-8").strip()
        if old.isdigit() and process_alive(int(old)):
            port = port_file.read_text(encoding="utf-8").strip() if port_file.exists() else "6688"
            print("系统已在运行。")
            print_urls(port)
            print("如需重启，请先运行“关闭系统.bat”。")
            return
    preferred = int(os.environ.get("PORT", "6688"))
    port = pick_port(preferred)
    port_file.write_text(str(port), encoding="utf-8")
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    if port != preferred:
        print(f"{preferred} 已被占用，已改用端口 {port}")
    print("合同与发票编号登记管理系统已启动")
    print_urls(port)
    print("默认管理员：admin    密码：admin123")
    print("关闭方式：双击“关闭系统.bat”，或直接关闭本窗口")
    allow_firewall(port)
    app = create_app()
    try:
        app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
    finally:
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
            pid_file.unlink()


if __name__ == "__main__":
    main()
