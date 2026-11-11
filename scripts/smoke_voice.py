"""实时语音冒烟：真实连接 DashScope Qwen-Realtime，文本引导一轮。

用法：python scripts/smoke_voice.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 把 local.env 灌进环境变量（不打印任何密钥）
for line in (ROOT / "local.env").read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from tripcraft.voice.realtime_qwen import (  # noqa: E402
    QwenRealtimeClient,
    build_scene_voice_instructions,
    resolve_env,
)

scene = {
    "opening": "客户刚接起电话，正在说明想去哪、几个人。",
    "location": "电话沟通",
    "stage_title": "首呼与需求挖掘",
    "objective": "问清人数、日期、预算口径与住宿意向",
    "situation": "你时间不多，说话直接，预算只肯说「性价比高」。",
}
customer = {"name": "Kenji", "nationality": "日本", "age": "42", "gender": "男"}
ins = build_scene_voice_instructions(scene, customer, "en")

api_key, url, model = resolve_env()
print("目标主机:", url.split("/")[2])
print("模型:", model)
print("指令已构造:", len(ins), "字符")

seen: list[str] = []


def on_event(ev: dict) -> None:
    t = ev.get("type", "")
    seen.append(t)
    if t in ("session.updated", "response.audio_transcript.done", "response.text.done",
             "error", "ws_error"):
        print("EVENT", t, json.dumps(ev, ensure_ascii=False)[:300], flush=True)


client = QwenRealtimeClient(api_key, url, model, ins, voice="Jennifer", on_event=on_event)
print("连接中 ...")
client.connect()
if not client.wait_ready(25):
    print("失败：25 秒内未收到 session.updated")
    print("已收到事件类型:", sorted(set(seen))[:15])
    client.close()
    sys.exit(2)
print(">>> session 已就绪，发送文本引导")
client.ask_text("Good morning! I am your trip designer. May I ask a few questions?")
time.sleep(20)
client.close()
print(">>> 收到事件类型:", sorted(set(seen))[:20])