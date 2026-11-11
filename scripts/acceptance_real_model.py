"""真实模型链路验收（Lead 所有）——与「确定性标准案例」验收**分开记录**。

证据质量要求（监督者审查后收紧，v2）：
- **不再以 HTTP 200 判通过**：必须对返回结构做非空与有效性断言。
  开场为空、客户回复为空、scores 为空、ok=False 都不算通过。
- 保存**脱敏后的真实样本**（客户文本 / 评分条目片段），而不是只有字符数。
- 只声明真正调用过的链路：本脚本覆盖 连通性 / 训练老师 / 客户对话 / 评分；
  未覆盖的（如真实语音）明确记为未验收。
- 只做适量调用（共约 5 次），不做压测。

安全：绝不打印、写出或截图任何凭据；样本经 redact() 去手机号/邮箱/长数字。

用法：
    python -X utf8 scripts/acceptance_real_model.py
退出码：0 = 所有已覆盖链路有效；1 = 有链路无效；3 = 未配置凭据。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 沙箱下 mkdtemp 建的目录不可访问（identity 已实测），库文件直接放已存在的临时目录
os.environ.setdefault("TRIPCRAFT_VISIT_LOG_DIR", tempfile.gettempdir())
os.environ["TRIPCRAFT_DB"] = os.path.join(
    tempfile.gettempdir(), f"tripcraft-realmodel-{uuid.uuid4().hex}.sqlite")

sys.path.insert(0, str(ROOT))

RESULTS: list[dict] = []
SAMPLES: list[dict] = []
MAX_SAMPLE = 200

# 必需的**真实文本**环节：状态不是 verified 就算失败。
# partial / not_verified 一律不允许当通过（监督者明确要求）。
REQUIRED_STEPS = frozenset({
    "真实模型连通性",
    "训练链路：技能点线程快照",
    "训练链路：训练老师真实回复",
    "客户链路：发起首呼",
    "客户链路：一轮客户对话",
    "客户链路：结束首呼并登记证据",
    "评分链路",
    "评分链路：可回读评分记录",
})


def redact(text: str) -> str:
    """脱敏：手机号 / 邮箱 / 连续长数字（订单号等）。"""
    if not text:
        return ""
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text)
    out = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "<phone>", out)
    out = re.sub(r"(?<!\d)\d{10,}(?!\d)", "<number>", out)
    return out[:MAX_SAMPLE]


def rec(step: str, status: str, detail: str = "", extra: dict | None = None) -> None:
    item = {"step": step, "status": status, "detail": detail}
    if extra:
        item.update(extra)
    RESULTS.append(item)
    print(f"  [{status}] {step}" + (f" — {detail}" if detail else ""))


def sample(step: str, text: str) -> None:
    SAMPLES.append({"step": step, "redacted_sample": redact(text)})


def read_local_env_keys() -> set[str]:
    """只返回变量名，绝不返回值；复用应用自身加载器（utf-8-sig，可处理 BOM）。"""
    from tripcraft.agents.llm import load_env

    try:
        return set(load_env().keys())
    except Exception:  # noqa: BLE001
        return set()


def main() -> int:
    print("== Lead 真实模型链路验收 v2（有效性断言 + 脱敏样本） ==")
    print("不打印任何凭据；样本已脱敏。\n")

    names = read_local_env_keys()
    llm_present = "DEEPSEEK_API_KEY" in names or bool(os.environ.get("DEEPSEEK_API_KEY"))
    voice_present = "DASHSCOPE_API_KEY" in names or bool(os.environ.get("DASHSCOPE_API_KEY"))
    rec("local.env 中 DEEPSEEK_API_KEY 变量存在", "config", "present" if llm_present else "absent")
    rec("local.env 中 DASHSCOPE_API_KEY 变量存在", "config", "present" if voice_present else "absent")

    if not llm_present:
        rec("真实文本链路", "not_configured", "未配置 DEEPSEEK_API_KEY，无法验收真实模型")
        write_output()
        return 3

    from tripcraft.agents.llm import DeepSeekClient, LLMError

    # ---------- 1. 连通性 ----------
    t0 = time.time()
    try:
        client = DeepSeekClient()
        out = client.chat([{"role": "user", "content": "只回复两个字：连通"}],
                          temperature=0.0, max_tokens=16)
        dt = round(time.time() - t0, 2)
        ok = bool((out or "").strip())
        rec("真实模型连通性", "verified" if ok else "invalid",
            f"{dt}s，返回 {len(out or '')} 字符" + ("" if ok else "（空回复，判无效）"),
            {"latency_s": dt, "reply_chars": len(out or "")})
        if ok:
            sample("连通性", out)
        if not ok:
            write_output()
            return 1
    except (LLMError, Exception) as exc:  # noqa: BLE001
        rec("真实模型连通性", "failed", f"{type(exc).__name__}: {exc}")
        write_output()
        return 1

    # ---------- 2. 准备账号与订单 ----------
    from fastapi.testclient import TestClient

    from tripcraft.api.app import create_app

    c = TestClient(create_app())
    username = f"rm-{uuid.uuid4().hex[:8]}"
    pw = "RealModel1234!"
    r = c.post("/auth/register", json={"username": username, "password": pw, "display_name": username})
    if r.status_code not in (200, 201):
        rec("注册账号", "failed", f"{r.status_code}")
        write_output()
        return 1
    token = (c.post("/auth/login", json={"username": username, "password": pw}).json() or {}).get("token", "")
    headers = {"Authorization": f"Bearer {token}"}

    c.post("/practice/dispatch/generate", headers=headers, json={"count": 1})
    order_id = ""
    r = c.get("/practice/orders/available", headers=headers)
    avail = r.json() if r.status_code == 200 else []
    if avail:
        order_id = str((avail[0] or {}).get("order_id") or "")
        g = c.post(f"/practice/orders/{order_id}/grab", headers=headers)
        rec("真实链路：接单(grab)", "verified" if g.status_code == 200 else "failed",
            f"order={order_id} grab->{g.status_code}")
    if not order_id:
        rec("真实链路：取单", "failed", "拿不到订单")
        write_output()
        return 1

    # ---------- 3. 训练老师链路（真实模型） ----------
    # 真实返回结构：POST /threads/{sp}/messages → {"content": <本次 assistant 文本>, ...}
    # 注意：绝不能用 json.dumps(整个响应) 当回复——它必然 >10 字，会把「没模型输出」判成通过。
    sp = "C1.1"
    r = c.get(f"/threads/{sp}", headers=headers)
    rec("训练链路：技能点线程快照", "verified" if r.status_code == 200 else "failed",
        f"GET /threads/{sp} -> {r.status_code}")
    t0 = time.time()
    r = c.post(f"/threads/{sp}/messages", headers=headers,
               json={"text": "请用一句话讲解开场时如何做身份确认。"})
    if r.status_code != 200:
        rec("训练链路：训练老师真实回复", "failed", f"{r.status_code}: {r.text[:140]}")
    else:
        body = r.json() if isinstance(r.json(), dict) else {}
        reply = str(body.get("content") or "")
        if body.get("kind") in ("asset", "quiz"):
            reply = str(body.get("content") or "")     # 这两条分支同样以 content 承载正文
        ok = len(reply.strip()) >= 10
        rec("训练链路：训练老师真实回复", "verified" if ok else "invalid",
            f"{round(time.time()-t0,2)}s，本次 assistant 文本 {len(reply)} 字符"
            + ("" if ok else "（无有效模型输出，判无效）"))
        if ok:
            sample("训练老师回复", reply)

    # ---------- 4. 客户对话链路 ----------
    # 真实返回结构：POST /practice/orders/{id}/call → CallSession.snapshot()
    #   {"session_id","mode","lines":[{"who","text","at"}...],"turns",...}
    # 开场白 = lines 里第一条 who=="agent" 的 text（**不是** opening 字段）。
    t0 = time.time()
    r = c.post(f"/practice/orders/{order_id}/call", headers=headers)
    sid = ""
    if r.status_code != 200:
        rec("客户链路：发起首呼", "failed", f"{r.status_code}: {r.text[:140]}")
    else:
        payload = r.json() or {}
        sid = str(payload.get("session_id") or "")
        lines = payload.get("lines") or []
        opening = ""
        for ln in lines:
            if isinstance(ln, dict) and ln.get("who") == "agent" and str(ln.get("text") or "").strip():
                opening = str(ln["text"])
                break
        ok_open = len(opening.strip()) >= 5
        rec("客户链路：发起首呼", "verified" if ok_open else "invalid",
            f"{round(time.time()-t0,2)}s，agent 开场 {len(opening)} 字符"
            + ("" if ok_open else "（lines 里没有 agent 文本，判无效）"))
        if ok_open:
            sample("客户开场白", opening)

        if not sid:
            rec("客户链路：会话 ID", "failed", "响应里没有 session_id")
        else:
            t0 = time.time()
            r2 = c.post(f"/practice/call/{sid}/messages", headers=headers,
                        json={"text": "您好，我是负责您这次云南行程的定制师，方便现在沟通吗？"})
            if r2.status_code != 200:
                rec("客户链路：一轮客户对话", "failed", f"{r2.status_code}: {r2.text[:140]}")
            else:
                reply = str((r2.json() or {}).get("reply") or "")
                ok = len(reply.strip()) >= 5
                rec("客户链路：一轮客户对话", "verified" if ok else "invalid",
                    f"{round(time.time()-t0,2)}s，客户回复 {len(reply)} 字符"
                    + ("" if ok else "（空/过短，判无效）"))
                if ok:
                    sample("客户回复", reply)
            r3 = c.post(f"/practice/call/{sid}/end", headers=headers)
            rec("客户链路：结束首呼并登记证据",
                "verified" if r3.status_code == 200 else "failed", f"end->{r3.status_code}")

    # ---------- 5. 评分链路 ----------
    # 真实返回结构：POST /practice/orders/{id}/score
    #   {"ok":bool,"scored":N,"written":M,"skill_points":[...],...}  —— 没有 scores/items 字段
    # 真实评分条目另从 GET /practice/orders/{id}/scores 与 /evidence 读取核对。
    t0 = time.time()
    r = c.post(f"/practice/orders/{order_id}/score", headers=headers)
    if r.status_code != 200:
        rec("评分链路", "invalid", f"{r.status_code}: {r.text[:160]}（未拿到评分结果）")
    else:
        rep = r.json() or {}
        ok_flag = bool(rep.get("ok"))
        entries = rep.get("skill_points") or []
        scored_n = int(rep.get("scored") or 0)
        rows = []
        rs = c.get(f"/practice/orders/{order_id}/scores", headers=headers)
        if rs.status_code == 200:
            data = rs.json()
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                # 真实结构：{"order_id","dimensions":[{... "points":[{...,"evaluated":bool}]}],
                #            "average","evaluated","total"} —— 没有顶层 scores 字段
                for dim in (data.get("dimensions") or []):
                    for pt in (dim.get("points") or []):
                        if isinstance(pt, dict) and pt.get("evaluated"):
                            rows.append(pt)
        valid = ok_flag and scored_n >= 1 and len(entries) >= 1 and len(rows) >= 1
        rec("评分链路", "verified" if valid else "invalid",
            f"{round(time.time()-t0,2)}s，ok={ok_flag}, scored={scored_n}, "
            f"skill_points={len(entries)}, GET /scores 已评估点={len(rows)}"
            + ("" if valid else "（ok 假 / scored=0 / 条目为空 / 回读为空 → 判无效，不算通过）"))
        if entries:
            sample("评分条目样本", json.dumps(entries[0], ensure_ascii=False))
        if rows:
            rec("评分链路：可回读评分记录", "verified", f"{len(rows)} 个已评估技能点")
        else:
            rec("评分链路：可回读评分记录", "invalid", "GET /scores 没有已评估点，评分未落库或未回读")

    # ---------- 6. 语音：明确未验收（不计入必需项） ----------
    rec("真实语音/声学链路", "not_verified",
        "DASHSCOPE_API_KEY " + ("存在但未做声学验收" if voice_present else "不存在")
        + "；浏览器麦克风声学效果不能由文本测试冒充")

    write_output()
    # 判定：failed/invalid 一律失败；**必需的真实文本环节**只要不是 verified 也算失败
    # （partial/not_verified 不允许被当成通过）。
    bad = [x for x in RESULTS
           if x["status"] in ("failed", "invalid")
           or (x["step"] in REQUIRED_STEPS and x["status"] != "verified")]
    print(f"\n合计 {len(RESULTS)} 项；失败(含必需项未 verified)={len(bad)}")
    return 1 if bad else 0


def write_output() -> None:
    outdir = ROOT / "output" / "acceptance" / "evidence" / "lead"
    outdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "script": "scripts/acceptance_real_model.py",
        "version": 2,
        "note": "真实模型链路验收；与确定性标准案例验收分开。配置存在不等于连通；"
                "HTTP 200 不再等于通过，需结构非空与有效性。",
        "credentials_printed": False,
        "verdict_rule": "必需的真实文本环节必须 verified 才算通过；partial/not_verified 一律计为失败。"
                        "verified 判据：连通有非空回复；训练读本次 assistant content>=10 字；"
                        "首呼读 snapshot.lines 中 who=agent 的 text>=5 字；客户回复>=5 字；"
                        "评分需 ok=True 且 scored>=1 且 skill_points 非空，并能从 GET /scores 回读。"
                        "语音无密钥记未验收（不计入必需项）。",
        "steps": RESULTS,
        "desensitized_samples": SAMPLES,
    }
    (outdir / "real-model-check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 真实模型链路验收 v2（含脱敏样本）", ""]
    for r in RESULTS:
        lines.append(f"- [{r['status']}] {r['step']} — {r.get('detail', '')}")
    lines.append("")
    lines.append("## 脱敏样本")
    for s in SAMPLES:
        lines.append(f"- {s['step']}: {s['redacted_sample']}")
    (outdir / "real-model-check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
