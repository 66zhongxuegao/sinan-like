"""检查确定性训练卡是否按技能点分派（C2.2 / C6.1 / 未登记技能点）。

用法：python -X utf8 output/demo-rehearsal-20261017/_check_cards.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tripcraft.services import scenario_service as sc  # noqa: E402

case = sc.get_case("hk-huang-yunnan-5d")
llm = sc.ScenarioLLM(case)
ok = True
stems = {}
for sp in ("C2.2", "C6.1", "C3.1"):
    sys_teacher = sc._TEACHER_SIG + "\n【本次技能点】x（" + sp + "）"
    lecture = llm.chat([{"role": "system", "content": sys_teacher}, {"role": "user", "content": "讲义"}])
    sys_q = sc._QUESTION_SIG + "\n【本次技能点】x（" + sp + "）"
    quiz = json.loads(llm.chat([{"role": "system", "content": sys_q}, {"role": "user", "content": "出题"}]))
    sys_a = sc._ASSET_SIG + "\n【本次技能点】x（" + sp + "）"
    asset = llm.chat([{"role": "system", "content": sys_a}, {"role": "user", "content": "生成讲义"}])
    first = lecture.splitlines()[0]
    stems[sp] = quiz["stem"]
    if sp == "C6.1":
        # 讲义与资源必须是 C6.1·快速响应安抚；题干必须是突发情景（车辆故障），且不是 C2.2 那道预算题
        right = ("快速响应安抚" in lecture and "快速响应安抚" in asset
                 and ("车" in quiz["stem"] or "突发" in quiz["stem"]))
    elif sp == "C3.1":
        right = "通用教案" in first                      # 未登记技能点必须显式标注通用教案
    else:
        right = "预算口径" in lecture and "预算" in quiz["stem"]
    ok = ok and right
    print(f"{sp}: 讲义首行={first[:44]!r}")
    print(f"     题干={quiz['stem'][:56]!r} 答案={quiz['answer']} 资源首行={asset.splitlines()[0][:40]!r}")
    print(f"     {'OK' if right else 'NG'} 卡片与技能点匹配")
distinct = len({stems['C2.2'], stems['C6.1']}) == 2
ok = ok and distinct
print(f"\nC2.2 与 C6.1 题干不同: {'OK' if distinct else 'NG'}")

# ---- 定向：行程方案反馈必须按实际渲染内容给（D4 博物馆=要求改；D4 翠湖短线=认可） ----
case_json = json.loads((Path(__file__).resolve().parents[2] / "data" / "scenario" / "standard_case.json")
                       .read_text(encoding="utf-8"))["cases"][0]
v1_line = "D4 | 08:30 | 动车 2 小时 | 云南省博物馆·翠湖 | 午 汽锅鸡 | 昆明滇池四星 | 导游·周"
v2_line = "D4 | 09:00 | 动车 2 小时 + 专车 30 分 | 翠湖短线·斗南花市手工体验 | 午 汽锅鸡 | 昆明滇池四星 | 导游·周"
r1 = json.loads(llm._deliverable_feedback(
    "sig", "我是黄先生。定制师发来的「行程方案」内容：\n" + v1_line))["reply"]
r2 = json.loads(llm._deliverable_feedback(
    "sig", "我是黄先生。定制师发来的「行程方案」内容：\n" + v2_line))["reply"]
rules = case_json.get("plan_feedback_rules") or {}
for name, good in [
    ("V1（D4=博物馆）→ 要求修改原文", r1 == rules.get("v1_reply") and "博物馆" in r1),
    ("V2（D4=翠湖短线+花市手工）→ 认可调整原文", r2 == rules.get("v2_reply") and "翠湖短线" in r2),
    ("V1 与 V2 反馈不同", r1 != r2),
    ("V2 反馈不再提博物馆", "博物馆" not in r2),
]:
    ok = ok and good
    print(f"{'OK' if good else 'NG'} {name}")
print("V1 反馈:", r1)
print("V2 反馈:", r2)
print("\n结论:", "全部匹配" if ok else "存在不一致")
raise SystemExit(0 if ok else 1)
