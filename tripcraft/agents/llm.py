"""LLM 客户端（DeepSeek）—— 生成层的统一入口。

设计（PRD 第 8 章三层判断、DECISIONS D-008）：
- 本模块只负责「生成」与「结构化抽取」，不做门控/算术（那些是硬编码）。
- 密钥只从 local.env 读取，不落库、不打印。
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = ROOT / "local.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


class LLMError(RuntimeError):
    pass


class DeepSeekClient:
    """DeepSeek Chat 客户端（OpenAI 兼容）。"""

    def __init__(self, env: dict[str, str] | None = None, timeout: float = 120.0) -> None:
        env = load_env() if env is None else env
        self._key = env.get("DEEPSEEK_API_KEY", "")
        if not self._key:
            raise LLMError("缺少 DEEPSEEK_API_KEY（请写入 local.env）")
        self._base = env.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self._model = env.get("LLM_MODEL", "deepseek-chat")
        self._timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.7,
             max_tokens: int = 2000, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._base + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._key},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                data = json.load(r)
        except Exception as exc:  # 网络/鉴权错误统一抛出
            raise LLMError(f"LLM 调用失败: {type(exc).__name__}: {exc}") from exc
        return data["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.2,
                  max_tokens: int = 4000):
        """要求模型输出 JSON，并做健壮解析。"""
        text = self.chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
        return parse_json(text)


def parse_json(text: str):
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("无法解析模型返回的 JSON")