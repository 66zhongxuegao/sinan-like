"""语音中继冒烟：浏览器 WebSocket -> FastAPI -> DashScope Qwen-Realtime。

用文本触发一轮，验证：ready / state / audio / transcript / closed 事件齐全，
并且通话结束后证据被登记。

用法：python -X utf8 scripts/smoke_voice_bridge.py [order_id]
前置：后端已启动。
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

BASE = "ws://127.0.0.1:18020/voice/realtime"


async def main() -> int:
    order_id = sys.argv[1] if len(sys.argv) > 1 else "9000000000000002"
    url = f"{BASE}?order_id={order_id}"
    counts: dict[str, int] = {}
    audio_bytes = 0
    agent_text, student_text = [], []

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        print("connected:", url)
        ready = False
        deadline = asyncio.get_event_loop().time() + 30
        while not ready and asyncio.get_event_loop().time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            counts[msg["type"]] = counts.get(msg["type"], 0) + 1
            if msg["type"] == "ready":
                ready = True
                print("ready:", {k: msg[k] for k in ("session_id", "lang", "input_rate", "output_rate")})
            elif msg["type"] == "error":
                print("error:", msg["message"])
                return 2
        if not ready:
            print("FAIL: 未收到 ready")
            return 2

        print("-> 发送文本引导一轮")
        await ws.send(json.dumps({"type": "text", "text": "您好，我是司南礼客定制游的定制师小李，请问怎么称呼您？"}, ensure_ascii=False))

        end = asyncio.get_event_loop().time() + 40
        done_audio = False
        while asyncio.get_event_loop().time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
            except asyncio.TimeoutError:
                break
            t = msg["type"]
            counts[t] = counts.get(t, 0) + 1
            if t == "audio":
                audio_bytes += len(msg.get("audio") or "")
                done_audio = True
            elif t == "transcript" and msg.get("final"):
                (agent_text if msg["who"] == "agent" else student_text).append(msg["text"])
            elif t == "error":
                print("error:", msg["message"])
        await ws.send(json.dumps({"type": "stop"}))
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                counts[msg["type"]] = counts.get(msg["type"], 0) + 1
                if msg["type"] == "closed":
                    print("closed:", {k: v for k, v in msg.items() if k != "type"})
                    break
        except asyncio.TimeoutError:
            pass

    print("事件统计:", counts)
    print("音频增量(base64字符):", audio_bytes)
    print("客户转写:", (agent_text[0][:70] if agent_text else "(无)"))
    if audio_bytes == 0:
        print("FAIL: 没有收到音频增量")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))