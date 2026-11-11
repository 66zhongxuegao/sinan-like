"""公网链接打不开？一键恢复（先查源站，再查隧道）。

trycloudflare 快速隧道的地址和 cloudflared 进程绑定，进程一停地址就永久失效。
但「链接打不开」有三种完全不同的原因，处理方式也不同：

  1. 源站没起来（后端 18020 / 生产预览 4180 挂了）→ 公网返回 502，**隧道是好的，千万别换地址**；
  2. 隧道进程死了 / 校园网掐了出网 7844 → 必须重启隧道拿新地址，再同步 README 与 GitHub；
  3. 只是 README 和线上仓库不一致 → 重新发布一次即可。

顺序：先保源站 → 再看公网 → 最后才动隧道。

    python -X utf8 scripts/relink_public.py             # 只修本地，不推 GitHub
    python -X utf8 scripts/relink_public.py --publish   # 修完顺手发到 GitHub
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
FRONTEND = ROOT / "frontend"
URL_FILE = LOGS / "PUBLIC-URL.txt"
LOG = LOGS / "cloudflared-preview.log"
CF = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
BACKEND_PORT = 18020
PREVIEW_PORT = 4180
TARGET = f"http://127.0.0.1:{PREVIEW_PORT}"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- 小工具

def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def http_code(url: str, timeout: int = 25) -> str:
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tripcraft-relink"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return str(r.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception:
        return ""


def read_url() -> str:
    if not URL_FILE.exists():
        return ""
    lines = URL_FILE.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
    return lines[0].strip() if lines else ""


# ---------------------------------------------------------------- 源站

def start_backend() -> None:
    """照 scripts/start.ps1 的方式起后端（日志追加到 logs/backend.log）。"""
    with (LOGS / "backend.log").open("a", encoding="utf-8", errors="ignore") as fh:
        subprocess.Popen(["python", "-X", "utf8", "-m", "uvicorn",
                          "tripcraft.api.app:create_app", "--factory",
                          "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
                         cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
                         creationflags=NO_WINDOW)


def start_preview() -> None:
    """起生产预览（评委看的就是它，比 dev 快很多）。"""
    with (LOGS / "preview.log").open("a", encoding="utf-8", errors="ignore") as fh:
        subprocess.Popen(["cmd", "/c", "npm run preview"], cwd=str(FRONTEND),
                         stdout=fh, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)


def ensure_origin(wait_seconds: int = 60) -> bool:
    """公网要能打开，先得让「源站」活着：后端 18020 + 生产预览 4180。"""
    if not FRONTEND.joinpath("dist", "index.html").exists():
        print("[..] 没有生产构建，先跑一次 npm run build")
        subprocess.run(["cmd", "/c", "npm run build"], cwd=str(FRONTEND),
                       creationflags=NO_WINDOW)
    if not port_open(BACKEND_PORT):
        print(f"[..] 后端 {BACKEND_PORT} 没在跑，启动它")
        start_backend()
    if not port_open(PREVIEW_PORT):
        print(f"[..] 预览服务 {PREVIEW_PORT} 没在跑，启动它（生产构建）")
        start_preview()

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if port_open(BACKEND_PORT) and port_open(PREVIEW_PORT):
            if http_code(f"http://127.0.0.1:{PREVIEW_PORT}/", 10) == "200":
                print(f"[ok] 源站在线：后端 {BACKEND_PORT} + 预览 {PREVIEW_PORT}")
                return True
        time.sleep(1.5)
    print("[x] 源站起不来。先双击 一键启动.bat 看报错，再回来跑本脚本。")
    return False


# ---------------------------------------------------------------- 隧道

def kill_cloudflared() -> None:
    # 不解码输出：中文 Windows 的 taskkill 是 GBK，text=True 会直接抛 UnicodeDecodeError
    subprocess.run(["taskkill", "/f", "/im", "cloudflared.exe"], capture_output=True)


def start_tunnel() -> str:
    if not CF.exists():
        print(f"[x] 没装 cloudflared：{CF}")
        return ""
    if LOG.exists():
        LOG.unlink()
    subprocess.Popen([str(CF), "tunnel", "--url", TARGET, "--protocol", "http2",
                      "--no-autoupdate", "--logfile", str(LOG), "--loglevel", "info"],
                     creationflags=NO_WINDOW)
    print("[..] 已启动新隧道，等它拿到地址……")
    for _ in range(60):
        time.sleep(2)
        if LOG.exists():
            for line in LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "trycloudflare.com" in line and "https://" in line:
                    seg = line.split("https://", 1)[1]
                    return "https://" + seg.split()[0].strip().strip("|").strip('"')
    return ""


def wait_public(url: str, tries: int = 20, gap: float = 3.0) -> bool:
    for _ in range(tries):
        if http_code(url) == "200":
            return True
        time.sleep(gap)
    return False


# ---------------------------------------------------------------- README / 发布

def sync_readme() -> None:
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "sync_demo_url.py")],
                   cwd=ROOT)


def readme_in_snapshot() -> str:
    p = ROOT / "_publish" / "tripcraft" / "README.md"
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def publish() -> int:
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "publish_public.py")],
                       cwd=ROOT)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="改完直接发布到 GitHub")
    args = ap.parse_args()

    # 1) 源站先活着：很多「链接打不开」其实是 502（隧道好好的，源站挂了）
    if not ensure_origin():
        return 1

    url = read_url()
    code = http_code(url)
    print(f"当前公网地址：{url or '（没有记录）'}  →  HTTP {code or '打不开'}")

    if code == "200":
        print("[ok] 隧道是活的，地址不用换。对方手上的链接继续有效。")
        if args.publish and url not in readme_in_snapshot():
            print("[..] 线上仓库的 README 不是这个地址，重新发布一次")
            return publish()
        if args.publish:
            print("[ok] 线上仓库的 README 已同步。")
        return 0

    # 2) 源站好的、公网不通 → 才是隧道的问题
    print("[..] 源站正常但公网不通，重启隧道并换新地址")
    kill_cloudflared()
    time.sleep(2)
    new_url = start_tunnel()
    if not new_url:
        print("[x] 没拿到新地址：多半是本机出网 7844 被封（校园网/公司网常见）。")
        print("    换个网络（手机热点）或开代理的 TUN 模式再跑本脚本；旧地址不用动。")
        return 1

    if not wait_public(new_url):
        print(f"[x] 新地址 {new_url} 还是打不开，先不发布——别再换链接了。")
        print("    查这两处：源站 curl http://127.0.0.1:4180 是否 200；cloudflared 日志里有没有 edge 连接失败。")
        return 1

    print(f"[ok] 新地址已能打开：{new_url}")
    URL_FILE.write_text(new_url + "\n", encoding="utf-8")
    sync_readme()
    if not args.publish:
        print("（没加 --publish，只改了本地 README；要同步给评委再加 --publish）")
        return 0
    return publish()


if __name__ == "__main__":
    raise SystemExit(main())
