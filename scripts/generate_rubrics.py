"""Rubric 生成器 —— 调用 DeepSeek 按《Rubric生成要求》分批生成。

用法：
    python scripts/generate_rubrics.py --batch s2_domestic
    python scripts/generate_rubrics.py --batch s2_inbound

输出：data/rubrics_raw/<batch>.json（原始输出，供审计与校验）
密钥：从 local.env 读取 DEEPSEEK_API_KEY，不写入任何文件。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tripcraft.contracts.enums import DIMENSION_NAMES, STEP_NAMES  # noqa: E402
from tripcraft.contracts.skill_points import SKILL_POINTS_BY_ID  # noqa: E402

RAW_DIR = ROOT / "data" / "rubrics_raw"

BATCHES: dict[str, list[str]] = {
    # 第一批：M1 垂直切片「S2 首呼」涉及的 9 个技能点
    "s2_domestic": ["C1.1", "C1.2", "C1.3", "C1.6", "C2.1", "C2.2"],
    "s2_inbound": ["C8.1", "C8.2", "C8.4"],
    # 其余：按维度补齐（避免重复；s2 批次已覆盖的点不再列入）
    "dim_c1_rest": ["C1.4", "C1.5", "C1.7", "C1.8"],
    "dim_c2_rest": ["C2.3", "C2.4", "C2.5", "C2.6", "C2.7"],
    "dim_c3": ["C3.1", "C3.2", "C3.3", "C3.4", "C3.5", "C3.6", "C3.7", "C3.8", "C3.9"],
    "dim_c4": ["C4.1", "C4.2", "C4.3", "C4.4", "C4.5", "C4.6", "C4.7", "C4.8"],
    "dim_c5": ["C5.1", "C5.2", "C5.3", "C5.4", "C5.5", "C5.6", "C5.7", "C5.8"],
    "dim_c6": ["C6.1", "C6.2", "C6.3", "C6.4", "C6.5", "C6.6", "C6.7"],
    "dim_c7": ["C7.1", "C7.2", "C7.3", "C7.4", "C7.5", "C7.6", "C7.7"],
    "dim_c8_rest": ["C8.3", "C8.5", "C8.6", "C8.7"],
}


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


HARD_RULES = """1. 同一客户可能同时派给 3 位定制师，联系慢了就丢单。
2. 派单信息经常缺失，必须电话首呼补问。
3. 系统要求 1 小时内打电话、4 小时内上传方案。
4. 必须先确认酒店、车、票、导游等资源，再给客户确定报价。
5. 资源可先付约 80% 预留，最后结全款。
6. 定制游必须买保险。
7. 方案最终做成 PPT，再转 PDF 发给客户。
8. 行前 1–2 天发出团通知书。
9. 行中客户不会找地接社，最终都找定制师，定制师是全程第一责任人。
10. 行后要拿地接结算单和自己的报价逐项核对，再付尾款。"""

MODULES = "行业认知 / 沟通服务 / 需求管理 / 目的地资源 / 国别文化 / 方案设计 / 视觉呈现 / 实操注意 / 入境中国"

GOLD = """C2.2 预算口径识别（B 型）：
M1 全程未追问预算，直接按「性价比高」做方案/报价；
M2 只问「预算多少」，客户答「性价比高」就停止；
M3 追问「人均还是总价」，但没确认区间、是否含大交通；
M4 问到人均/总价+区间，但未二次复述确认；
M5 追问并量化确认（人均/总价+区间+是否含大交通），复述得到确认。
positive：「您的预算是人均还是整团总价？大概区间？含不含机票高铁？」并复述确认。
negative：客户说「性价比高」就当成预算已明确，报价被否定。
evidence_required：引用 S2 通话转写中关于预算的问答原文。
knowledge：需求管理·期望管理——「性价比高 ≠ 预算明确」。"""


def skill_block(ids: list[str]) -> str:
    lines = []
    for sid in ids:
        sp = SKILL_POINTS_BY_ID[sid]
        steps = "/".join(s.value for s in sp.steps)
        lines.append(
            f"{sp.id} {sp.name} | 维度 {sp.dimension.value} {DIMENSION_NAMES[sp.dimension]} | "
            f"{sp.checkpoint.value} 型 | 步骤 {steps} | 考核定位：{sp.target}"
        )
    return "\n".join(lines)


def build_prompt(ids: list[str]) -> str:
    return f"""你是中国定制师（含入境游）培训的资深教研专家，擅长把「实战能力」拆成可观测、可打分的评估标准。

【任务】
为我给定的每一个技能点，生成一条 BARS 评分标准（Rubric），输出严格 JSON 数组。

【本系统背景】
这是一个「定制师全流程模拟实战系统」：学员在倒计时、预算、资源、突发事件压力下，连续交付真实工作物。评分由 AI 评分 Agent 按 Rubric 逐字对照学员的通话转写/消息记录/交付物。

【技能点信息】
{skill_block(ids)}

【必须遵守的行业硬规则】
{HARD_RULES}

【知识点只能来自这 9 个模块】
{MODULES}

【输出 JSON 结构（数组，每个技能点一个对象）】
[
  {{
    "skill_point_id": "",
    "name": "",
    "dimension": "",
    "checkpoint": "A 或 B",
    "steps": [],
    "target": "",
    "trigger": "B 型必填；A 型为 null",
    "anchors": {{ "M1": "", "M2": "", "M3": "", "M4": "", "M5": "" }},
    "positive": "",
    "negative": "",
    "evidence_required": "",
    "knowledge": "",
    "sources": []
  }}
]

【硬性质量规则】
1. 锚点必须是「可观测行为」——能从通话转写/消息/交付物里看到或读到；禁止「表现较好/沟通能力强/理解到位」这类评价。每条锚点必须是完整描述（建议 15 字以上），写清「做到了/没做到什么 + 具体动作或话术或字段」，禁止只写一个短语（如「未发出团通知书」）。
2. M1–M5 必须在同一根轴上单调递进，相邻档必须可区分。
3. positive 必须是可直接照说的台词模板；negative 必须是真实常见错误。
4. evidence_required 必须写明「引用哪一步的什么记录」。
5. knowledge 只能写「模块·知识点」，模块必须来自上面 9 个。
6. B 型必须有 trigger；A 型 trigger 为 null。
7. 涉及目的地/签证/宗教禁忌/支付等事实必须联网核对并给出处；查不到就写 "待核实"，不得编造。
8. 不得与上面 10 条硬规则冲突。

【金标准（模仿此粒度）】
{GOLD}

【输出要求】
- 只输出 JSON 数组，不要解释、不要 Markdown 代码块。
- 输出前自检：锚点 5 个且可观测、单调递进、B 型有 trigger、正例可照说、反例真实、证据具体、知识点合法。
"""


def call_deepseek(env: dict[str, str], prompt: str) -> str:
    key = env.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise SystemExit("local.env 缺少 DEEPSEEK_API_KEY")
    base = env.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = env.get("LLM_MODEL", "deepseek-chat")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 8000,
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, choices=sorted(BATCHES))
    args = ap.parse_args()

    ids = BATCHES[args.batch]
    print(f"批次 {args.batch}：{len(ids)} 个技能点 -> {', '.join(ids)}")
    prompt = build_prompt(ids)
    env = load_env()
    print("调用 DeepSeek 生成中 ...")
    out = call_deepseek(env, prompt)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{args.batch}.json"
    path.write_text(out.strip() + "\n", encoding="utf-8", newline="\n")
    print(f"原始输出已保存: {path.relative_to(ROOT)} ({len(out)} 字符)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())