"""数据基座生成器 —— 为 61 个技能点生成「学习资料 + 练习题」。

流程（每个技能点）：
  1. 让模型给出 2-3 条检索查询；
  2. 联网检索（cn.bing.com + 百度百科）拿依据；
  3. 让模型基于「Rubric 锚点 + 检索依据」生成结构化教学资产。

输出：data/knowledge/<skill_point_id>.json
进度：stdout + data/knowledge/_progress.log（可另开窗口 Get-Content -Wait 观看）

用法：
  python scripts/build_knowledge.py                 # 全部 61 个（跳过已完成的）
  python scripts/build_knowledge.py --limit 3       # 只做 3 个（试跑）
  python scripts/build_knowledge.py --only C2.2     # 只做指定
  python scripts/build_knowledge.py --redo          # 重做（覆盖）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.agents.llm import DeepSeekClient  # noqa: E402
from tripcraft.contracts.enums import DIMENSION_NAMES  # noqa: E402
from tripcraft.contracts.rubric import RUBRICS  # noqa: E402
from tripcraft.contracts.skill_points import SKILL_POINTS  # noqa: E402
from tripcraft.tools.websearch import baike, research  # noqa: E402

OUT_DIR = ROOT / "data" / "knowledge"
LOG_PATH = OUT_DIR / "_progress.log"
MODULES = "行业认知 / 沟通服务 / 需求管理 / 目的地资源 / 国别文化 / 方案设计 / 视觉呈现 / 实操注意 / 入境中国"

QUERY_SYS = """你是定制师培训教研专家。针对给定技能点，给出 2-3 条用于联网检索的中文查询词，
用于查找相关的行业知识、目的地事实、政策或案例。

输出 JSON：{"queries": ["...", "..."]}
只输出 JSON。"""

BUILD_SYS = f"""你是中国定制师（含入境游）培训的资深教研专家。为给定技能点生成「学习资料 + 练习题」。

【交付要求】
1. explain：知识点讲解，250-450 字，讲清"是什么、为什么、怎么做"。
2. key_points：3-6 条关键要点，每条一句话。
3. examples：2-3 组对比示例，每组含 scene（场景）/ bad（错误做法）/ good（正确做法）。
4. resources：3 档个性化学习资源（difficulty 取 L1/L2/L3），各含 title / format（讲解/案例/话术脚本/清单）/ content（150-300 字）。
5. exercises：至少 3 题，含 2 道选择题（type=choice，options 4 个、answer 用 A/B/C/D、explain 解析）与 1 道简答题（type=short，含 reference 参考答案与 rubric_points 评分要点数组）。
6. sources：列出你实际依据的来源（title + url）；若使用了检索依据必须列出；若纯属通识可标注「依据：PRD 硬规则」。

【硬性约束】
- 内容必须围绕该技能点的 Rubric 锚点与考核定位，不得跑题。
- 知识点归属只能来自这 9 个模块：{MODULES}。
- 涉及目的地/政策/禁忌等事实，只能使用提供的检索依据；依据不足就写得保守，不得编造。
- 与 10 条行业硬规则保持一致（保险必买、先确认资源再报价等）。
- 只输出 JSON。
"""


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def build_one(sp, llm: DeepSeekClient, redo: bool) -> bool:
    out = OUT_DIR / f"{sp.id}.json"
    if out.exists() and not redo:
        log(f"跳过（已完成） {sp.id} {sp.name}")
        return True

    rubric = RUBRICS.get(sp.id)
    rblock = ""
    if rubric:
        anchors = "\n".join(f"  {a.level.value}: {a.behavior}" for a in rubric.anchors)
        rblock = (f"考核定位: {rubric.target}\n触发条件: {rubric.trigger or '（A 型，无需触发）'}\n"
                  f"锚点:\n{anchors}\n正例: {rubric.positive}\n反例: {rubric.negative}")

    sp_block = (f"技能点 {sp.id} {sp.name}\n维度: {sp.dimension.value} {DIMENSION_NAMES[sp.dimension]}\n"
                f"考点类型: {sp.checkpoint.value}\n学习资料归属: {sp.material}\n涉及步骤: "
                + "/".join(s.value for s in sp.steps) + f"\n{rblock}")

    # 1) 检索词
    try:
        q = llm.chat_json([{"role": "system", "content": QUERY_SYS},
                           {"role": "user", "content": sp_block}], temperature=0.3, max_tokens=300)
        queries = [str(x) for x in (q.get("queries") or [])][:3] or [f"{sp.name} 定制师"]
    except Exception:
        queries = [f"{sp.name} 定制师"]

    # 2) 联网检索
    hits = research([f"{sp.name} 定制师 实战"] + queries[:2], per_query=2)
    ctx_lines = [f"- {h.title}：{h.snippet}" for h in hits[:6]]
    # 目的地类技能点补一个百科词条
    if sp.id.startswith("C8") or "目的地" in sp.material:
        b = baike("中国入境旅游")
        if b:
            ctx_lines.append(f"- {b.title}：{b.snippet}")
    context = "\n".join(ctx_lines) or "（未取到检索依据，请仅依据 PRD 与通识保守撰写）"

    # 3) 生成
    user = (sp_block + "\n\n【联网检索依据】\n" + context +
            "\n\n请据此生成教学资产 JSON，结构：\n" +
            '{"skill_point_id":"","name":"","dimension":"","explain":"","key_points":[],'
            '"examples":[{"scene":"","bad":"","good":""}],'
            '"resources":[{"difficulty":"L1","title":"","format":"","content":""}],'
            '"exercises":[{"type":"choice","stem":"","options":[],"answer":"","explain":""}],'
            '"sources":[{"title":"","url":""}]}')
    data = llm.chat_json([{"role": "system", "content": BUILD_SYS},
                          {"role": "user", "content": user}], temperature=0.5, max_tokens=6000)
    if not isinstance(data, dict):
        raise ValueError("返回非 JSON 对象")
    data["skill_point_id"] = sp.id
    data["name"] = sp.name
    data["dimension"] = sp.dimension.value
    data["dimension_name"] = DIMENSION_NAMES[sp.dimension]
    data["checkpoint"] = sp.checkpoint.value
    data["generated_at"] = datetime.now().isoformat(timespec="seconds")
    data["_queries"] = queries
    data["_search_hits"] = [{"title": h.title, "url": h.url} for h in hits[:6]]

    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = list(SKILL_POINTS)
    if args.only:
        targets = [s for s in targets if s.id == args.only]
    if args.limit:
        targets = targets[: args.limit]

    llm = DeepSeekClient()
    log(f"=== 数据基座生成开始：共 {len(targets)} 个技能点 ===")
    ok = fail = 0
    t0 = time.time()
    for i, sp in enumerate(targets, 1):
        ts = time.time()
        try:
            build_one(sp, llm, args.redo)
            ok += 1
            status = "OK"
        except Exception as exc:
            fail += 1
            status = f"FAIL({type(exc).__name__})"
            log(f"失败 {sp.id}: {str(exc)[:120]}")
        used = time.time() - t0
        eta = (used / i) * (len(targets) - i) if i else 0
        log(f"[{i}/{len(targets)}] {sp.id} {sp.name} {status} | 本步 {time.time()-ts:.1f}s | "
            f"累计 {used/60:.1f}m | ETA {eta/60:.1f}m")
    log(f"=== 结束：成功 {ok} / 失败 {fail} / 共 {len(targets)} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())