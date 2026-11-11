"""校准集结构审计（PRD 25.2 覆盖率要求）。

不是为了评测，而是为了回答「这套校准集本身够不够格」：
  技能点分层 / 难度分层 / 难例集 / 语言与客源覆盖。
"""

from __future__ import annotations

from collections import Counter

MIN_PER_SKILL_POINT = 2      # 每个技能点至少 N 条样本
MIN_MARKETS = 2              # 至少覆盖 2 个客源国
MIN_LANGUAGES = 2            # 至少覆盖 1 门入境语言 + 中文
HARD_KEYWORDS = ("难例", "反例", "边界", "红线")
REQUIRED_LEVELS = ("M1", "M2", "M3", "M4", "M5")


def audit_dataset(samples: list[dict], min_per_sp: int = MIN_PER_SKILL_POINT) -> dict:
    total = len(samples)
    per_sp: Counter = Counter()
    levels: Counter = Counter()
    markets: Counter = Counter()
    langs: Counter = Counter()
    hard = 0
    for s in samples:
        for sp in s.get("skill_point_ids", []):
            per_sp[sp] += 1
        for lab in s.get("labels", []):
            levels[lab.get("level", "")] += 1
        markets[s.get("source_market", "")] += 1
        langs[s.get("language", "")] += 1
        if any(k in (s.get("difficulty") or "") or k in (s.get("note") or "") for k in HARD_KEYWORDS):
            hard += 1

    missing_levels = [lv for lv in REQUIRED_LEVELS if levels.get(lv, 0) == 0]
    thin = sorted(sp for sp, n in per_sp.items() if n < min_per_sp)

    gaps: list[str] = []
    if missing_levels:
        gaps.append(f"缺少掌握度档位样本: {'、'.join(missing_levels)}")
    if thin:
        gaps.append(f"以下技能点样本不足 {min_per_sp} 条: {'、'.join(thin)}")
    if len(markets) < MIN_MARKETS:
        gaps.append(f"客源市场不足 {MIN_MARKETS} 个")
    if len(langs) < MIN_LANGUAGES:
        gaps.append(f"语言覆盖不足 {MIN_LANGUAGES} 种（入境游至少要覆盖 1 门非中文）")
    if hard == 0:
        gaps.append("没有难例（反例命中 / 边界档 / 跨文化红线）")
    if total < 30:
        gaps.append(f"样本总量偏少（{total} 条）")

    return {
        "samples": total,
        "skill_points": len(per_sp),
        "per_skill_point": dict(sorted(per_sp.items())),
        "min_per_skill_point": min_per_sp,
        "thin_skill_points": thin,
        "levels": {lv: levels.get(lv, 0) for lv in REQUIRED_LEVELS},
        "missing_levels": missing_levels,
        "markets": dict(markets.most_common()),
        "languages": dict(langs.most_common()),
        "hard_cases": hard,
        "gaps": gaps,
        "passed": not gaps,
    }