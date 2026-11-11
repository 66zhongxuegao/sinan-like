"""学习路线管家：从初始画像与学习需求生成线性优先级路线。

路线只负责“先学什么、后学什么”，不改动能力分。每次生成/调整都写入 memory，
因此刷新页面后仍可恢复当前路线与对话记录。
"""

from __future__ import annotations

import json
import re
import time

from ..contracts.enums import DIMENSION_NAMES, Dimension
from ..contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID
from .adaptive_diagnosis import candidate_probes, constrained_route, prerequisite_ready
from .experience_compiler import get_skill_graph

ROUTE_TYPE = "learning_route"
ROUTE_SIZE = 16

DEMAND_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("报价", "价格", "预算", "毛利", "利润", "成本", "算价"), ("C5",), "需求涉及报价与利润"),
    (("亲子", "孩子", "带娃", "老人", "长辈", "家庭"), ("C3", "C6", "C7"), "需求涉及家庭或特殊人群"),
    (("入境", "外宾", "外语", "英语", "签证", "跨文化", "海外"), ("C8", "C1"), "需求涉及入境与跨文化服务"),
    (("酒店", "车队", "用车", "导游", "票务", "资源"), ("C4",), "需求涉及资源整合"),
    (("行程", "路线", "方案", "景点", "节奏"), ("C3",), "需求涉及方案设计"),
    (("首呼", "沟通", "信任", "客户", "话术"), ("C1", "C2"), "需求涉及客户沟通"),
    (("突发", "应急", "投诉", "延误", "超售", "取消"), ("C6", "C1"), "需求涉及应急与投诉处理"),
    (("合同", "保险", "合规", "时限", "流程", "风险"), ("C7",), "需求涉及合规效率"),
    (("需求", "挖掘", "确认", "预算口径"), ("C2",), "需求涉及需求洞察"),
)

TIERS = (
    ("foundation", "先补基础", "画像里的低分项先稳住，不带着短板进入下一步", "#e08a1e"),
    ("focus", "当前重点", "与你的学习需求最贴近，建议接下来优先练", "#2577e3"),
    ("grow", "能力提升", "基础稳定后扩展，形成完整处理链路", "#12a76a"),
    ("apply", "巩固应用", "用实战与复盘把已经掌握的能力固化", "#94a3b8"),
)

STAGE_LABELS = {
    "S0": "规则交底", "S1": "抢单接单", "S2": "首呼沟通", "S3": "需求确认",
    "S4": "资源询价", "S5": "行程方案", "S6": "分项报价", "S7": "客户反馈",
    "S8": "成交录单", "S9": "行前准备", "S10": "行中应急", "S11": "结算回访", "S12": "复盘提升",
}


def _base_score(store, user_id: str, sp_id: str, abilities: dict) -> float:
    row = abilities.get(sp_id) or {}
    teach = float(row.get("teach") or 0)
    real = float(row.get("real_v") or 0)
    if teach or real:
        return max(teach, real) if real else teach
    dim = sp_id.split('.', 1)[0]
    base = (store.baseline(user_id) or {}).get(dim)
    return float((base or {}).get('value') or 0)


def _demand_hits(demand: str) -> tuple[set[str], list[str]]:
    dims: set[str] = set()
    reasons: list[str] = []
    text = str(demand or '').strip()
    for words, hit_dims, reason in DEMAND_RULES:
        if any(word.lower() in text.lower() for word in words):
            dims.update(hit_dims)
            if reason not in reasons:
                reasons.append(reason)
    return dims, reasons


def _reason_for(sp, score: float, demand_dims: set[str], demand: str) -> str:
    dim = sp.dimension.value
    if dim in demand_dims:
        return f"与你的需求直接相关，当前画像 {score:.0f} 分，建议先建立这条处理链路。"
    if score < 60:
        return f"初始画像仅 {score:.0f} 分，是当前最明显的薄弱环节。"
    if score < 75:
        return f"当前 {score:.0f} 分，具备基础但还不稳定，适合紧跟基础项练习。"
    return f"当前 {score:.0f} 分，放在后半段用于巩固和迁移到实战。"


def _ordered_skills(store, user_id: str, demand: str) -> tuple[list[dict], dict]:
    abilities = store.abilities(user_id)
    demand_dims, demand_reasons = _demand_hits(demand)
    rows = []
    for sp in SKILL_POINTS:
        score = _base_score(store, user_id, sp.id, abilities)
        dim = sp.dimension.value
        demand_boost = 60 if dim in demand_dims else 0
        # 先补底层需求洞察、沟通与合规，再进入资源、方案、报价和行中。
        foundation = {"C2": 4, "C1": 3, "C7": 2, "C3": 2, "C4": 1, "C5": 1, "C6": 0, "C8": 0}.get(dim, 0)
        rows.append({
            "id": sp.id, "name": sp.name, "dimension": dim,
            "dimension_name": DIMENSION_NAMES[sp.dimension],
            "score": round(score, 1), "checkpoint": sp.checkpoint.value,
            "material": sp.material, "target": sp.target,
            "stage": sp.steps[0].value if sp.steps else "",
            "stage_name": STAGE_LABELS.get(sp.steps[0].value if sp.steps else "", "实战"),
            "score_for_order": (100 - score) + demand_boost + foundation,
            "reason": _reason_for(sp, score, demand_dims, demand),
        })
    # 需求命中的维度轮换取前两项，再补画像缺口；避免同一条线占满前几档。
    pools = {dim: [r for r in sorted(rows, key=lambda r: (-r["score_for_order"], r["score"], r["id"]))
                   if r["dimension"] == dim] for dim in sorted(demand_dims)}
    chosen: list[dict] = []
    for pick in range(2):
        for dim in sorted(pools):
            if pick < len(pools[dim]) and pools[dim][pick]["id"] not in {x["id"] for x in chosen}:
                chosen.append(pools[dim][pick])
    for row in sorted(rows, key=lambda r: (-r["score_for_order"], r["score"], r["id"])):
        if len(chosen) >= ROUTE_SIZE:
            break
        if row["id"] not in {x["id"] for x in chosen}:
            chosen.append(row)
    chosen = chosen[:ROUTE_SIZE]
    for index, row in enumerate(chosen, 1):
        row["order"] = index
    return chosen, {"demand_dims": sorted(demand_dims), "demand_reasons": demand_reasons}


def _group(items: list[dict]) -> list[dict]:
    tier_count = len(TIERS)
    base = len(items) // tier_count
    extra = len(items) % tier_count
    out, cursor = [], 0
    for index, (key, label, hint, color) in enumerate(TIERS):
        size = base + (1 if index < extra else 0)
        chunk = items[cursor:cursor + size]
        cursor += size
        out.append({"key": key, "label": label, "hint": hint, "color": color,
                    "items": chunk, "count": len(chunk)})
    return out


def build_route(store, user_id: str, demand: str = "", messages: list[dict] | None = None) -> dict:
    items, meta = _ordered_skills(store, user_id, demand)
    tiers = _group(items)
    top = items[:3]
    focus = "、".join(f"{x['id']} {x['name']}" for x in top)
    summary = (f"管家根据你的当前画像，把 {focus} 放在最前。"
               + (f" 你的需求是「{demand.strip()}」，路线已把这部分相关技能提前。" if demand.strip() else
                  " 还没有输入具体需求，先用画像短板给出通用起步路线。"))
    # 保留现有画像排序作为“可执行的教学路线”，同时把技能图约束和主动诊断
    # 作为独立字段暴露出来；前端可先渐进展示，不破坏已有 16 条路线契约。
    abilities = store.abilities(user_id)
    graph = get_skill_graph()
    graph_plan = constrained_route(
        abilities, graph, size=ROUTE_SIZE, demand_dims=meta.get("demand_dims", []))
    probes = candidate_probes(abilities, limit=5)
    graph_items: dict[str, dict] = {}
    for item in items:
        sid = item["id"]
        missing = []
        for prior in graph.prerequisites_of(sid):
            prior_row = abilities.get(prior) or {}
            if float(prior_row.get("teach") or 0.0) < 45.0:
                missing.append(prior)
        graph_items[sid] = {
            "ready": prerequisite_ready(sid, abilities, graph),
            "missing_prerequisites": missing,
            "risk_level": graph.node(sid).risk_level if graph.node(sid) else "unknown",
        }
    graph_summary = graph.summary()
    constraints = {
        "method": "skill_graph_topological_constraint_v1",
        "graph_nodes": graph_summary["nodes"],
        "graph_edges": graph_summary["edges"],
        "prerequisite_edges": sum(1 for e in graph.edges if e.kind == "prerequisite"),
        "next_best_probe": probes[0] if probes else None,
        "probes": probes,
        "graph_plan": graph_plan,
        "items": graph_items,
    }
    route_id = f"route-{user_id}-{int(time.time() * 1000)}"
    return {
        "route_id": route_id, "user_id": user_id, "demand": demand.strip(),
        "generated_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "summary": summary, "tiers": tiers, "items": items,
        "focus": [x["id"] for x in top], "meta": meta,
        "graph_constraints": constraints,
        "messages": list(messages or []),
    }


def save_route(store, user_id: str, route: dict) -> None:
    store.add_memory(user_id, ROUTE_TYPE, json.dumps(route, ensure_ascii=False),
                     source_thread="learning-route", importance=1.0)


def latest_route(store, user_id: str) -> dict | None:
    row = store.latest_memory(user_id, ROUTE_TYPE)
    if not row:
        return None
    try:
        route = json.loads(row.get("content") or "{}")
    except (TypeError, ValueError):
        return None
    return route if isinstance(route, dict) and route.get("items") else None


def generate_route(store, user_id: str, demand: str = "") -> dict:
    route = build_route(store, user_id, demand)
    route["messages"] = [{"role": "butler", "text": route["summary"]}]
    save_route(store, user_id, route)
    return route


def _revision_dims(text: str, words: tuple[str, ...]) -> set[str]:
    dims: set[str] = set()
    for clause in re.split(r"[，,；;。\n]+", text or ""):
        if any(word in clause for word in words):
            dims.update(_demand_hits(clause)[0])
    return dims


def revise_route(store, user_id: str, message: str) -> dict:
    current = latest_route(store, user_id) or generate_route(store, user_id, "")
    text = str(message or "").strip()
    if not text:
        return current
    combined = "；".join(x for x in (current.get("demand", ""), text) if x)
    route = build_route(store, user_id, combined, messages=current.get("messages") or [])
    demote_dims = _revision_dims(text, ("放到后面", "放后面", "最后", "往后", "不着急", "先不学", "降低优先级"))
    promote_dims = _revision_dims(text, ("放到前面", "放前面", "优先", "先学", "最前", "提前", "更着急"))
    if demote_dims or promote_dims:
        promoted = [x for x in route["items"] if x["dimension"] in promote_dims and x["dimension"] not in demote_dims]
        demoted = [x for x in route["items"] if x["dimension"] in demote_dims]
        middle = [x for x in route["items"] if x["dimension"] not in promote_dims and x["dimension"] not in demote_dims]
        route["items"] = promoted + middle + demoted
        for index, item in enumerate(route["items"], 1):
            item["order"] = index
        route["tiers"] = _group(route["items"])
        if promote_dims:
            names = "、".join(DIMENSION_NAMES[Dimension(dim)] for dim in sorted(promote_dims))
            route["summary"] += f" 已优先安排{names}相关节点。"
        if demote_dims:
            names = "、".join(DIMENSION_NAMES[Dimension(dim)] for dim in sorted(demote_dims))
            route["summary"] += f" 已按你的要求把{names}相关节点往后排。"
    route["messages"] = list(current.get("messages") or []) + [
        {"role": "user", "text": text},
        {"role": "butler", "text": route["summary"]},
    ]
    route["revision"] = text
    save_route(store, user_id, route)
    return route
