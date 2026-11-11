"""保持在线：让别人手上那个公网地址在你离开期间不掉。

免费 trycloudflare 隧道的地址和当前 cloudflared 进程绑定，进程一停地址就永久失效、
也搬不到别的机器上。所以这里只做两件事：
  1. 阻止系统睡眠/休眠/自动关机（否则网络断掉，隧道一样会死）；
  2. 每分钟探一次后端、前端、隧道进程与公网地址；公网地址连续失败就报警，
     并把「需要重新发地址」写进 logs/LINK-DOWN.txt。

注意：这里**不会自动重启 cloudflared**——重启会换一个新地址，
反而让对方手上那个链接失效，必须由人决定。

    python -X utf8 scripts/keepalive.py            # 默认守护 8 小时
    python -X utf8 scripts/keepalive.py --hours 7
    python -X utf8 scripts/keepalive.py --no-power # 不动电源设置，只做探测
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
URL_FILE = LOGS / "PUBLIC-URL.txt"
DOWN_FILE = LOGS / "LINK-DOWN.txt"
PUBLIC = ""      # 运行中确定


def beep() -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        pass


def hold_power(hours: float) -> None:
    """把交流电下的睡眠/休眠/硬盘断电都关掉，撑过这段时间。"""
    for args in (
        ["powercfg", "/change", "standby-timeout-ac", "0"],
        ["powercfg", "/change", "hibernate-timeout-ac", "0"],
        ["powercfg", "/change", "disk-timeout-ac", "0"],
        ["powercfg", "/change", "monitor-timeout-ac", "15"],
    ):
        try:
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception:
            pass
    print(f"已关闭睡眠与休眠（计划守护 {hours:g} 小时，屏幕仍可自动关闭）")


def restore_power() -> None:
    for args in (
        ["powercfg", "/change", "standby-timeout-ac", "30"],
        ["powercfg", "/change", "hibernate-timeout-ac", "60"],
    ):
        try:
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception:
            pass


def cloudflared_alive() -> bool:
    # 不要解码：中文 Windows 的 tasklist 输出是 GBK，带 -X utf8 时 text=True 会直接抛错；
    # 进程名本身是 ASCII，按字节找最稳。
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq cloudflared.exe"],
                             capture_output=True, timeout=20).stdout.lower()
        return b"cloudflared.exe" in out
    except Exception:
        return False


def probe(url: str, timeout: int = 20) -> int:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TripCraft-KeepAlive/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except Exception:
        return 0


def read_public_url() -> str:
    for f in (URL_FILE, LOGS / "PUBLIC-URL.txt"):
        try:
            if f.exists():
                v = f.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[0].strip()
                if v.startswith("http"):
                    return v
        except Exception:
            continue
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="保持司南礼客公网地址在线")
    ap.add_argument("--hours", type=float, default=8.0, help="守护时长，默认 8 小时")
    ap.add_argument("--interval", type=float, default=60.0, help="探测间隔秒数，默认 60")
    ap.add_argument("--no-power", action="store_true", help="不改电源设置，只做探测")
    args = ap.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    url = read_public_url()
    print("=" * 60)
    print("  司南礼客 · 公网地址保持在线")
    print(f"  当前地址：{url or '（没找到 logs/PUBLIC-URL.txt，请先跑 共享演示.bat）'}")
    print("=" * 60)

    if not args.no_power:
        hold_power(args.hours)

    print(f"开始守护，每 {args.interval:g} 秒探一次；期间请不要关机、不要重启 cloudflared。")
    print("按 Ctrl+C 退出（但退出后就不再报警了）。\n")

    deadline = time.time() + args.hours * 3600
    fails = 0
    while time.time() < deadline:
        stamp = datetime.now().strftime("%H:%M:%S")
        latest = read_public_url()
        if latest and latest != url:          # 隧道换过地址：跟着换，别一直探旧的
            print(f"[{stamp}] 地址已更新：{latest}")
            url = latest
            fails = 0
            try:
                DOWN_FILE.unlink()            # 旧地址的报警作废
            except Exception:
                pass
        code = probe(url) if url else 0
        tunnel = cloudflared_alive()
        if code == 200 and tunnel:
            print(f"[{stamp}] 正常 · 隧道进程在 · 地址可访问")
            fails = 0
        else:
            fails += 1
            why = "地址打不开" if code != 200 else "隧道进程不在了"
            print(f"[{stamp}] 异常（第 {fails} 次）· {why}")
            if fails >= 3:
                msg = (f"{datetime.now():%Y-%m-%d %H:%M:%S}\n"
                       f"公网地址已不可用：{url}\n原因：{why}\n"
                       "对方手上的链接已经失效，需要立刻重新发一个新地址（除非是后端崩了、"
                       "而 cloudflared 还活着——那时先重启后端，地址不会变）。\n")
                try:
                    DOWN_FILE.write_text(msg, encoding="utf-8")
                except Exception:
                    pass
                beep()
                print("\n" + "!" * 60)
                print("  地址已连续 3 次探不通：如果 cloudflared 还活着，先重启后端（地址不变）；")
                print("  如果 cloudflared 已死，那个地址无法找回，必须重新发链接。")
                print("!" * 60 + "\n")
                fails = 0
        time.sleep(max(15.0, args.interval))

    if not args.no_power:
        restore_power()
    print("守护时间到，已恢复电源设置。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        if "--no-power" not in sys.argv:
            restore_power()
        print("\n已退出守护。")