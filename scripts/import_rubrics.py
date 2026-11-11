"""Rubric 导入与校验 —— 把大模型生成的 JSON 校验后入库。

用法：
    python scripts/import_rubrics.py                # 处理 data/rubrics_raw/*.json
    python scripts/import_rubrics.py --file x.json  # 处理单个文件

校验通过后写入 tripcraft/contracts/data/rubrics.json（打包数据）。
不通过的技能点会被列出原因，且不写入。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.contracts.enums import CheckpointType  # noqa: E402
from tripcraft.contracts.skill_points import SKILL_POINTS_BY_ID  # noqa: E402

RAW_DIR = ROOT / "data" / "rubrics_raw"
OUT_PATH = ROOT / "tripcraft" / "contracts" / "data" / "rubrics.json"

MODULES = ("行业认知", "沟通服务", "需求管理", "目的地资源", "国别文化",
           "方案设计", "视觉呈现", "实操注意", "入境中国")

# 模糊评价词（锚点里出现即判不合格：这是评价，不是可观测行为）
VAGUE_WORDS = ("表现较好", "表现良好", "表现优秀", "表现一般", "沟通能力强",
               "能力较强", "能力较弱", "理解到位", "综合表现", "态度良好",
               "做得不错", "处理得当", "较为专业")

REQUIRED = ("skill_point_id", "steps", "target", "anchors", "positive",
            "negative", "evidence_required", "knowledge")
LEVELS = ("M1", "M2", "M3", "M4", "M5")


def strip_code_fence(text: str) -> str:
    """去掉可能的 ```json 包裹。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def extract_json(text: str):
    """从文本中提取第一个 JSON 数组或对象。"""
    t = strip_code_fence(text)
    for opener, closer in (("[", "]"), ("{", "}")):
        i = t.find(opener)
        j = t.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("无法从输出中解析出 JSON")


def validate_rubric(obj: dict) -> list[str]:
    """返回错误列表；空列表表示通过。"""
    errors: list[str] = []
    for key in REQUIRED:
        if key not in obj or obj[key] in (None, "", []):
            errors.append(f"缺字段: {key}")
    sp_id = obj.get("skill_point_id", "")
    sp = SKILL_POINTS_BY_ID.get(sp_id)
    if sp is None:
        errors.append(f"未知技能点: {sp_id}")
        return errors

    anchors = obj.get("anchors") or {}
    if not isinstance(anchors, dict):
        errors.append("anchors 必须是对象")
    else:
        if set(anchors) != set(LEVELS):
            errors.append(f"anchors 必须恰好含 M1-M5，实际: {sorted(anchors)}")
        vals = [str(anchors.get(m, "")).strip() for m in LEVELS]
        for m, v in zip(LEVELS, vals):
            if len(v) < 8:
                errors.append(f"{m} 锚点过短/缺失: {v!r}")
        for a, b in zip(vals, vals[1:]):
            if a and a == b:
                errors.append("相邻档锚点重复")
        joined = " ".join(vals)
        hit = [w for w in VAGUE_WORDS if w in joined]
        if hit:
            errors.append(f"锚点含模糊评价词: {hit}")

    trigger = obj.get("trigger")
    if sp.checkpoint is CheckpointType.B_EVENT and not (trigger or "").strip():
        errors.append("B 型考点必须给 trigger")
    if sp.checkpoint is CheckpointType.A_DELIVERABLE and (trigger or "").strip():
        errors.append("A 型考点 trigger 应为 null/空")

    knowledge = str(obj.get("knowledge", ""))
    if not any(m in knowledge for m in MODULES):
        errors.append(f"knowledge 未引用 9 个学习模块之一: {knowledge!r}")

    return errors


def load_raw(path: Path) -> list[dict]:
    obj = json.loads(strip_code_fence(path.read_text(encoding="utf-8")))
    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list):
        raise ValueError("原始文件应为数组或对象")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="单个原始 JSON 文件")
    args = ap.parse_args()

    files = [Path(args.file)] if args.file else sorted(RAW_DIR.glob("*.json"))
    if not files:
        print(f"未找到原始文件（{RAW_DIR}）")
        return 1

    existing: dict[str, dict] = {}
    if OUT_PATH.exists():
        src = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        existing = {r["skill_point_id"]: r for r in src}

    total_ok = total_fail = 0
    for f in files:
        try:
            items = load_raw(f)
        except Exception as exc:
            print(f"[{f.name}] 解析失败: {exc}")
            total_fail += 1
            continue
        for obj in items:
            sp_id = obj.get("skill_point_id", "?")
            errors = validate_rubric(obj)
            if errors:
                total_fail += 1
                print(f"[不合格] {sp_id}")
                for e in errors:
                    print(f"    - {e}")
                continue
            total_ok += 1
            existing[sp_id] = obj
            print(f"[通过] {sp_id} {obj.get('name', '')}")

    if total_ok:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = sorted(existing.values(), key=lambda x: x["skill_point_id"])
        OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(f"\n已写入 {OUT_PATH.relative_to(ROOT)}（共 {len(data)} 条）")

    print(f"\n通过 {total_ok} | 不合格 {total_fail}")
    return 0 if total_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())