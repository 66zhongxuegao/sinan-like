"""校准集读写。"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLES = ROOT / "data" / "calibration" / "samples.jsonl"
DEFAULT_REPORT = ROOT / "data" / "calibration" / "report.json"

_PUNCT = re.compile(r"[\s，。、；：？！,.;:?!\"'“”‘’（）()【】\[\]—\-…]+")


def normalize_text(text: str) -> str:
    """去掉空白与标点，用于「证据是否真的出自原文」的比对。"""
    return _PUNCT.sub("", (text or "")).lower()


def load_samples(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else DEFAULT_SAMPLES
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def save_samples(samples: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else DEFAULT_SAMPLES
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return p


def save_report(report: dict, path: str | Path | None = None) -> Path:
    p = Path(path) if path else DEFAULT_REPORT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return p