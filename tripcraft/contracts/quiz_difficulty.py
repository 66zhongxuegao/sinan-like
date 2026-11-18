"""教学题难度规格（L1–L5）—— 把「难度」从 Prompt 里的一句形容词变成可执行、可校验的参数。

为什么要有这份契约：
  以前出题 Prompt 只写「L3 进阶：带两个干扰点」，模型生成后不做任何检查，结果常见
  「三短一长」「正确答案最长最具体」「题干一两句话」——学员不用懂业务也能猜对，
  难度分档在学员体感上几乎没有区别。

现在每一档都规定四个维度，并由 `validate_question` 在出题后逐项核对：
  1. 题干长度（情景复杂度）       stem_min / stem_max（按字数，去空白）
                                  区间按真实模型产出与手机阅读量校准：L5 上限 400 字≈手机一屏半
  2. 干扰条件数量                 distractors：题干里与正确决策无关、但看起来相关的信息
  3. 关键约束数量                 constraints：必须同时满足 / 需要取舍的条件
  4. 选项近似度                   option_ratio：最长选项 / 最短选项 的上限；
                                  越高档选项越像，差别只在一个关键细节或先后顺序

注意：这里的 L1–L5 是教学题难度，与订单任务的 `contracts.enums.DifficultyLevel`（PRD 四档）是两套口径。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuizDifficultySpec:
    level: str
    name: str
    stem_min: int
    stem_max: int
    distractors: int          # 题干中必须埋入的干扰条件条数
    constraints: int          # 题干中必须同时满足 / 需要取舍的关键约束条数
    option_ratio: float       # 选项长度：最长 / 最短 的上限
    option_min: int           # 每个选项最少字数（太短的选项无法做出近似度）
    scenario: str             # 情景复杂度说明（给出题模型）
    option_style: str         # 选项近似度说明（给出题模型）


QUIZ_DIFFICULTY: dict[str, QuizDifficultySpec] = {
    "L1": QuizDifficultySpec(
        "L1", "基础", 60, 130, 0, 1, 1.8, 8,
        "单一客户、单一需求、信息完整，直接对应一个标准动作。",
        "错误选项是新手常见的明显错误做法（如跳过确认、直接报价），但句式与长度要和正确项相近。"),
    "L2": QuizDifficultySpec(
        "L2", "简单辨析", 110, 190, 1, 2, 1.6, 12,
        "在基础情景上加入 1 条看似相关、实际不影响决策的干扰信息；有 2 个需要同时照顾的条件。",
        "至少 1 个错误选项「做对了一半」：照顾了一个条件却漏掉另一个；四个选项句式一致。"),
    "L3": QuizDifficultySpec(
        "L3", "进阶取舍", 150, 250, 2, 3, 1.4, 16,
        "加入 2 条干扰信息；3 个关键约束里至少有 2 个互相冲突，必须比较取舍。",
        "至少 2 个选项在业务上都说得通，区别在于优先级或先后顺序；不能靠「谁更完整」判断。"),
    "L4": QuizDifficultySpec(
        "L4", "高阶压力", 200, 320, 3, 3, 1.3, 20,
        "加入 3 条干扰信息，并叠加时间压力 / 资源紧张 / 客户情绪升级中的至少一种；3 个关键约束需要排序处理。",
        "四个选项都像专业做法、都包含合理动作，差别只在一个关键细节（时机、对象、顺序或遗漏的一步）。"),
    "L5": QuizDifficultySpec(
        "L5", "高压综合", 260, 400, 4, 4, 1.25, 24,
        "多个冲突同时发生：4 条干扰信息、4 个关键约束（含时间、成本、客户关系、合规中的至少三类），需要排优先级并给出书面闭环。",
        "四个选项都是结构相同的多步处置方案（同样的步数、同样的句式），只在一个关键步骤的顺序或取舍上不同。"),
}

LETTERS = ("A", "B", "C", "D")
# 学员不应看到的内部评分词
_INTERNAL_WORDS = re.compile(r"M[1-5]|Rubric|档位|难度\s*L?[1-5]|\bL[1-5]\b", re.I)
# 「以上都对 / 以上皆是」之类的选项会让题目失去区分度
_CATCH_ALL = re.compile(r"以上(都|皆|均|全)")


def spec_for(level: str) -> QuizDifficultySpec:
    return QUIZ_DIFFICULTY.get(str(level or "").upper(), QUIZ_DIFFICULTY["L1"])


def text_len(s: str) -> int:
    """按字数计：去掉空白与常见标点外的空格，中文/英文字符各算 1。"""
    return len(re.sub(r"\s+", "", str(s or "")))


def _target_min(spec: QuizDifficultySpec) -> int:
    """报给模型的目标下限比校验下限高约 20%（模型通常少写 10%~20%）。"""
    return min(spec.stem_max, int(spec.stem_min * 1.2))


def render_spec_prompt(spec: QuizDifficultySpec, answer_letter: str) -> str:
    """出题用的硬性参数（拼进 user 消息）。"""
    return (
        f"本题难度：{spec.level}（{spec.name}）。请严格按下列参数出一道**情景单选题**：\n"
        f"- 情景：{spec.scenario}\n"
        f"- 题干长度：{_target_min(spec)}–{spec.stem_max} 字（情景描述 + 最后一句提问），"
        f"少于 {spec.stem_min} 字会被退回重写。\n"
        f"- 干扰条件：恰好 {spec.distractors} 条，必须**原文写进题干**，并逐条抄到 design.distractor_conditions。\n"
        f"- 关键约束：至少 {spec.constraints} 条，逐条写到 design.key_constraints。\n"
        f"- 选项：4 个，{spec.option_style}\n"
        f"- 选项长度：每个不少于 {spec.option_min} 字；最长选项不超过最短选项的 {spec.option_ratio} 倍；"
        f"正确选项的字数要排在四个选项的**中间**（既不是最长也不是最短），也不能是最具体、最面面俱到的那个。\n"
        f"- 正确答案必须能由题干中的某条关键约束**唯一推出**，把依据写到 design.answer_basis"
        f"（哪条约束决定了答案、最接近的错误选项违反了哪一条）；做不到唯一就换一个情景。\n"
        f"- 正确答案放在 {answer_letter} 位置（answer 填 \"{answer_letter}\"）。"
    )


def validate_question(q: dict, spec: QuizDifficultySpec) -> list[str]:
    """逐项核对出题结果，返回问题清单（空列表＝合格）。只做确定性检查，不调模型。"""
    issues: list[str] = []
    if str(q.get("type") or "") != "choice":
        issues.append("题型必须是情景单选题（type=choice）")
        return issues
    stem = str(q.get("stem") or "")
    n = text_len(stem)
    # 下限留 10% 余量：模型普遍略少写，信息密度够即可，不为几十个字多等一轮重出
    if n < int(spec.stem_min * 0.9):
        issues.append(f"题干只有 {n} 字，{spec.level} 至少需要 {spec.stem_min} 字：请再补充约 {_target_min(spec) - n} 字的情景细节"
                      "（时间节点、人物关系、已发生的沟通），不要删减已有条件")
    elif n > int(spec.stem_max * 1.15):
        issues.append(f"题干 {n} 字，超过 {spec.level} 上限 {spec.stem_max} 字，请精简")

    design = q.get("design") if isinstance(q.get("design"), dict) else {}
    distractors = [str(x) for x in (design.get("distractor_conditions") or []) if str(x).strip()]
    present = [d for d in distractors if _appears_in(d, stem)]
    if len(present) < spec.distractors:
        issues.append(f"题干中可核对到的干扰条件 {len(present)} 条，{spec.level} 需要 {spec.distractors} 条"
                      "（干扰条件要原文写进题干）")
    constraints = [str(x) for x in (design.get("key_constraints") or []) if str(x).strip()]
    if len(constraints) < spec.constraints:
        issues.append(f"关键约束 {len(constraints)} 条，{spec.level} 需要至少 {spec.constraints} 条")
    # 选项越像越容易出现「两个都说得通」的争议题：正确答案必须能由某条关键约束唯一推出
    if not str(design.get("answer_basis") or "").strip():
        issues.append("缺少 design.answer_basis：写明正确答案由题干中哪一条关键约束唯一推出、"
                      "最接近的错误选项违反了哪一条")

    options = [str(x) for x in (q.get("options") or [])]
    if len(options) != 4 or any(not o.strip() for o in options):
        issues.append("必须是 4 个非空选项")
        return issues
    lens = [text_len(o) for o in options]
    if min(lens) < spec.option_min:
        issues.append(f"最短选项只有 {min(lens)} 字，{spec.level} 每个选项至少 {spec.option_min} 字")
    if min(lens) > 0 and max(lens) / min(lens) > spec.option_ratio:
        issues.append(f"选项长短差距过大（最长 {max(lens)} 字 / 最短 {min(lens)} 字），"
                      f"{spec.level} 需在 {spec.option_ratio} 倍以内，避免「三短一长」")
    letter = str(q.get("answer") or "").strip().upper()[:1]
    if letter not in LETTERS:
        issues.append("answer 必须是 A/B/C/D")
    else:
        mine = lens[LETTERS.index(letter)]
        others = [x for i, x in enumerate(lens) if LETTERS[i] != letter]
        # 比例与绝对字数都超出才算「靠长度能猜」：短选项差两三个字不构成提示
        if mine > max(others) * 1.08 and mine - max(others) >= 4:
            issues.append(f"正确选项 {letter} 有 {mine} 字，其他选项最长 {max(others)} 字，学员可以靠长度猜对："
                          f"请把 {letter} 精简到 {max(others)} 字以内，或把其余选项补充到与它相近的长度")
    if any(_CATCH_ALL.search(o) for o in options):
        issues.append("不要使用「以上都对 / 以上皆是」类选项")
    if _INTERNAL_WORDS.search(stem + " ".join(options)):
        issues.append("题干或选项出现了内部评分词（M1–M5 / Rubric / 档位 / 难度级别）")
    return issues


def _appears_in(fragment: str, stem: str) -> bool:
    """干扰条件是否真的写进了题干：允许措辞微调，取任一连续 6 字片段命中即可。"""
    f = re.sub(r"[\s，。、；：,.;:！!？?“”\"']", "", fragment)
    s = re.sub(r"[\s，。、；：,.;:！!？?“”\"']", "", stem)
    if not f:
        return False
    if f in s:
        return True
    k = 6 if len(f) >= 6 else len(f)
    return any(f[i:i + k] in s for i in range(0, len(f) - k + 1))


_LETTER_REF = re.compile(r"(选项|选|答案是?|答案为)\s*([A-D])|([A-D])\s*(项|选项)")


def place_answer(q: dict, target: str) -> dict:
    """把正确选项换到指定位置（与原位置互换），并同步改写讲解里的选项字母引用。"""
    letter = str(q.get("answer") or "").strip().upper()[:1]
    if letter not in LETTERS or target not in LETTERS or letter == target:
        return q
    i, j = LETTERS.index(letter), LETTERS.index(target)
    opts = list(q.get("options") or [])
    if len(opts) != 4:
        return q
    opts[i], opts[j] = opts[j], opts[i]
    swap = {letter: target, target: letter}

    def fix(m: re.Match) -> str:
        if m.group(2):
            return m.group(1) + swap.get(m.group(2), m.group(2))
        return swap.get(m.group(3), m.group(3)) + m.group(4)

    out = dict(q, options=opts, answer=target)
    if out.get("explain"):
        out["explain"] = _LETTER_REF.sub(fix, str(out["explain"]))
    design = out.get("design")
    if isinstance(design, dict) and isinstance(design.get("option_traps"), dict):
        traps = dict(design["option_traps"])
        a, b = traps.get(letter), traps.get(target)
        if a is not None or b is not None:
            traps[target], traps[letter] = a, b
        out["design"] = dict(design, option_traps=traps)
    return out
