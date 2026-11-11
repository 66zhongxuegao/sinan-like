"""从唯一数据源生成演示用「字段复制表 HTML」（单文件、简洁、可一键复制）。

用法：
    python -X utf8 output/demo-rehearsal-20261017/_gen_copy_html.py

数据来源：
  · data/scenario/standard_case.json（交付物字段 / 逐日行程 / 结算 / 复盘 / 训练卡 / IM 话术）
  · tripcraft/agents/profiler.py 的 QUIZ（12 题初测）+ 脚本里的固定选项映射
  · scripts/acceptance_standard_case.py 的 INCIDENT_REPLIES（行中事件固定回话）
不引入任何外观精修；只做可复制的表格与按钮。
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tripcraft.agents.profiler import QUIZ  # noqa: E402

OUT = ROOT / "output" / "demo-rehearsal-20261017" / "演示字段复制表.html"
CASE = json.loads((ROOT / "data" / "scenario" / "standard_case.json").read_text(encoding="utf-8"))["cases"][0]
DOCS = CASE["documents"]
PLAN = CASE["plan"]

# 12 题初测：按维度选固定选项（与验收脚本 CHOICE_BY_DIM 一致）
CHOICE_BY_DIM = {"C1": "a", "C2": "a", "C3": "c", "C4": "a", "C5": "a", "C6": "c", "C7": "a", "C8": "a"}

_script = (ROOT / "scripts" / "acceptance_standard_case.py").read_text(encoding="utf-8")
_m = re.search(r"INCIDENT_REPLIES = \{(.*?)\n\}", _script, re.S)
INCIDENT_REPLIES = dict(re.findall(r'"([A-Z\-]+)":\s*"([^"]+)"', _m.group(1))) if _m else {}

e = html.escape


def kv_table(rows: list[tuple[str, object]], title: str) -> str:
    out = [f"<h3>{e(title)} <button class='cp' data-copy-table>复制本表</button></h3>", '<table class="kv">']
    for k, v in rows:
        if v is None:
            continue
        val = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
        out.append(f'<tr><th>{e(str(k))}</th>'
                   f'<td><span class="v" contenteditable="true">{e(val)}</span>'
                   f'<button class="cp" data-copy-target>复制</button></td></tr>')
    out.append("</table>")
    return "\n".join(out)


def rows_table(rows: list[dict], title: str) -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    out = [f"<h3>{e(title)} <button class='cp' data-copy-table>复制本表</button></h3>",
           '<table class="grid"><thead><tr>',
           "".join(f"<th>{e(c)}</th>" for c in cols), "<th>复制</th></tr></thead><tbody>"]
    for r in rows:
        cells = "".join(f'<td><span class="v" contenteditable="true">{e(str(r.get(c, "")))}</span></td>'
                        for c in cols)
        line = "\t".join(str(r.get(c, "")) for c in cols)
        out.append(f'<tr>{cells}<td class="cpc">'
                   f'<button class="cp" data-copy-value="{e(line)}">复制本行</button></td></tr>')
    out.append("</tbody></table>")
    return "\n".join(out)


parts: list[str] = []

# ---- 身份与环境 ----
parts.append(kv_table([
    ("成品学员", (CASE.get("isolation") or {}).get("demo_display_name")),
    ("① 成品查看账号（最终交付用，保留不清空）", (CASE.get("isolation") or {}).get("demo_account_username")),
    ("② 现场从零账号（不预创建，现场注册演示“注册”）", (CASE.get("isolation") or {}).get("replay_account_username")),
    ("③ 排查留存账号（早前记录，保留不改；交付查看不用）", (CASE.get("isolation") or {}).get("debug_account_username")),
    ("口令（三个账号相同）", (CASE.get("isolation") or {}).get("demo_account_password")),
    ("前端", "http://127.0.0.1:15181"),
    ("后端", "http://127.0.0.1:18920"),
], "0. 演示身份（① 成品 verified / ② 现场 replay / ③ 排查留存 show）"))

parts.append("<h3>0b. 现场前置（工作人员）与 B0 步骤</h3>")
parts.append("<ul>"
             "<li><b>前置（工作人员做）</b>：运行 <code>启动标准演示.ps1</code> 启动内部演示实例："
             "后端 18920 / 前端 15181 / 库 .dsh-run\\codex-review\\preview.sqlite，启动期声明 "
             "<code>TRIPCRAFT_SCENARIO_MODE=offline</code> + <code>TRIPCRAFT_DEMO_TOURIST=on</code> + "
             "<code>TRIPCRAFT_BOOTSTRAP_ORDERS=1</code>。只有这个入口会把随机游客替换成固定黄先生。</li>"
             "<li>普通双击 <b>司南礼客桌面版.bat</b> = 正常模式（18010/5180，随机游客 + 真实模型链路），"
             "不做任何替换。</li>"
             "<li><b>B0（现场）</b>：正常注册 → 「消息中心」待接单里客人应为 <b>黄先生 / 云南</b> → 点 <b>抢单</b>。"
             "<b>不再有 /demo 导入页</b>，也不需要任何导入步骤。</li>"
             "<li>先做 12 题初测 + C6.1 学习不会丢单：演示实例里未接单的固定单可续期；已抢单 / 已完成不回退。</li>"
             "<li>公开界面（登录/注册/首页/导航）不再有「标准案例」入口；内部排查页 /demo 仅演示实例可访问。</li>"
             "</ul>")

# ---- 案例事实 ----
t = CASE["tourist"]
parts.append(kv_table([(k, t[k]) for k in (
    "customer", "source_market", "language", "documents", "party", "dates", "days", "budget",
    "transport", "hotel", "special", "decision", "intent")], "1. 标准案例事实（黄先生 · 云南 5 日）"))

# ---- 12 题初测 ----
qrows = []
for i, q in enumerate(QUIZ, 1):
    key = CHOICE_BY_DIM[q["dim"]]
    picked = next((o for o in q["options"] if o["key"] == key), {})
    qrows.append({"题号": i, "维度": q["dim"], "题干": q["title"],
                  "点这个字母": "ABCD"[q["options"].index(picked)] if picked else "?",
                  "选项文案（照抄点选）": picked.get("label", "")})
parts.append(rows_table(qrows, "2. 初始画像测评 12 题（逐题按“点这个字母”选）"))
parts.append(f"<p class='n'>提交后期望维度基线：C1 95 · C2 95 · C3 25 · C4 95 · C5 95 · C6 25 · C7 95 · C8 95</p>")

# ---- 训练卡 ----
for sp, card in (CASE.get("training_cards") or {}).items():
    if not isinstance(card, dict) or "quiz" not in card:
        continue
    parts.append(f"<h3>3. 学习卡 {e(sp)}（{e(card.get('name',''))}）</h3>")
    parts.append(f"<pre contenteditable='true'>{e(card.get('lecture_text',''))}</pre>")
    parts.append(rows_table([{"项": "题干", "值": card["quiz"]["stem"]},
                             {"项": "正确选项", "值": card["quiz"]["answer"]}], f"{sp} 题卡"))
    parts.append("<ul>" + "".join(f"<li contenteditable='true'>{e(o)}</li>" for o in card["quiz"]["options"]) + "</ul>")
parts.append("<p class='n'>学习说明：<b>C6.1 是主路径必需</b>（做题练到教学掌握度 ≥60 才能解锁行中"
             "换车事件：每轮 点「做题」→ 点「发送」→ 选 B → 交卷，共 5 轮）；"
             "C2.2 讲义/题卡为<b>可选</b>展示（不影响解锁）。</p>")

# ---- 首呼 / IM 话术 ----
fc = CASE["first_call"]
_cl = fc["customer_lines"]
parts.append(rows_table(
    [{"顺序": "opening（你还没说话）", "我（学员）说": "（点「点击拨打」后客户先开口）", "客户固定回复": _cl[0]}]
    + [{"顺序": f"你的第 {i + 1} 句", "我（学员）说": s,
        "客户固定回复": _cl[min(i + 1, len(_cl) - 1)] + ("（末句之后保持上一句）" if i + 1 >= len(_cl) else "")}
       for i, s in enumerate(fc["student_lines"])],
    "4. 首呼逐句（实测顺序：opening 先，之后你每发一句客户回下一句，末句后保持）"))
parts.append(rows_table([{"场景": "客户服务群（客户）", "我方发送 / 客户固定回复": CASE["im_lines"]["customer_hub"]},
                         {"场景": "资源对接群（地接）", "我方发送 / 地接固定回复": CASE["im_lines"]["supplier"]},
                         {"场景": "司导沟通群（导游）", "我方发送 / 导游固定回复": CASE["im_lines"]["guide"]}],
                        "5. IM 固定话术"))

# ---- 交付物字段 ----
def doc_rows(name: str, title: str) -> str:
    d = DOCS.get(name) or {}
    rows = []
    for k, v in d.items():
        if isinstance(v, list):
            continue
        rows.append((k, v))
    out = kv_table(rows, title)
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out += rows_table(v, f"{title} · {k}（逐行）")
    return out

parts.append(doc_rows("requirement_sheet", "6. 《需求确认单》字段"))
rq = CASE.get("resource_quote_doc") or {}
parts.append(kv_table([(k, v) for k, v in rq.items() if not isinstance(v, list)], "7. 《资源询价记录》字段"))
parts.append(rows_table(rq.get("compare") or [], "《资源询价记录》· 比价（≥2 家）"))

parts.append("""<h3>8. 《行程方案》V1（客户会反馈的版本：D4 = 博物馆）</h3>""")
parts.append(kv_table([(k, PLAN.get(k)) for k in ("title", "dates", "people", "vehicle", "hotel",
                                                  "tickets_v1", "insurance", "entry", "backup", "note", "freeform")],
                      "《行程方案》· 契约字段（V1 与 V2 相同部分）"))
parts.append(rows_table(PLAN["v1_days"], "《行程方案》V1 · 逐日（D4=云南省博物馆·翠湖）"))
parts.append(rows_table(PLAN["days"], "《行程方案》V2 · 逐日（D4 已按客户反馈改为翠湖短线 + 花市手工）"))
parts.append(rows_table(PLAN["sections"], "《行程方案》· 方案小节（创建方案页点“添加小节”逐条填）"))
parts.append(rows_table(
    [{"版本": "V1（D4=云南省博物馆·翠湖）", "客户固定反馈": (CASE.get("customer_replies") or {}).get("行程方案", "")},
     {"版本": "V2（D4=翠湖短线·斗南花市手工体验）",
      "客户固定反馈": (CASE.get("customer_replies") or {}).get("行程方案_已按反馈修改", "")}],
    "8b. 行程方案客户反馈（按实际渲染内容给：D4 未改→要求修改；已改→明确认可）"))

parts.append(doc_rows("quotation", "9. 《分项报价》字段（成本 10850 是预估，写进“内部核算说明”）"))
parts.append(doc_rows("contract", "10. 《合同与保险》字段"))
parts.append(doc_rows("departure_notice", "11. 《出团通知书》字段"))
parts.append(doc_rows("settlement", "12. 《地接结算核对单》字段（『地接结算』=资源方成本，『我方报价』=销售价，差异为负=毛利）"))
parts.append(doc_rows("review", "13. 《回访与复盘记录》字段"))

# ---- 行中事件回话 ----
order = ["INC-RESOURCE-VAGUE", "INC-CUSTOMER-OBJECTION", "INC-VEHICLE-BREAKDOWN", "INC-PRE-TRIP-GAP"]
channel = {"INC-RESOURCE-VAGUE": "资源对接群", "INC-CUSTOMER-OBJECTION": "客户（客户服务群）",
           "INC-VEHICLE-BREAKDOWN": "司导沟通群", "INC-PRE-TRIP-GAP": "司导沟通群"}
parts.append(rows_table([{"事件": k, "会话": channel.get(k, ""), "我方发送（固定）": INCIDENT_REPLIES.get(k, "")}
                         for k in order if k in INCIDENT_REPLIES] + [
                            {"事件": k, "会话": "", "我方发送（固定）": v}
                            for k, v in INCIDENT_REPLIES.items() if k not in order],
                        "14. 行中事件固定回话（4 起，按会话逐条发）"))

# ---- 评分与画像 ----
parts.append(rows_table([{"技能点": "C1.1", "采纳分数": 84}, {"技能点": "C1.7", "采纳分数": 77},
                         {"技能点": "C2.1", "采纳分数": 80}, {"技能点": "C3.1", "采纳分数": 72},
                         {"技能点": "C4.1", "采纳分数": 77}, {"技能点": "C4.4", "采纳分数": 82},
                         {"技能点": "C5.1", "采纳分数": 79}, {"技能点": "C5.5", "采纳分数": 83},
                         {"技能点": "C6.1", "采纳分数": 79}, {"技能点": "C8.3", "采纳分数": 80},
                         {"技能点": "C8.4", "采纳分数": 81}],
             "15. 评分待复核 11 条（逐条点“采纳”；verified 实测 11 条已采纳）"))
parts.append("<p class='n'><b>以下为 verified 账号真实页面实测值</b>（订单 9000000000000009 已结清；"
             "证据 output/demo-rehearsal-20261017/verified-browser/progress.json）。<br>"
             "画像对比：初始 C1 95 / C2 95 / C3 25 / C4 95 / C5 95 / C6 25 / C7 95 / C8 95；"
             "当前 C1 91.4 / C2 92.9 / C3 30.2 / C4 91.1 / C5 91.5 / C6 32.7 / C7 95.0 / C8 90.9。<br>"
             "真实分数趋势：做题 5 题 · 正确 5 · 准确率 100% · 均分 92；实战 11 条评分 · 均分 79.5。</p>")
parts.append("<p class='n'>账目：客户收入 12690 · 资源口径成本 11030 · 实际毛利 1660（13.08%）· 损失 0 · "
             "客户尾款 9690 · 临时换车 400 由车队承担（我方应付 0 / 我方承担 0，已自动定责）。</p>")
parts.append("<p class='n'>财务页按钮口径：群里回复「差额由车队承担」后财务已自动定责，所以"
             "<b>首次进入财务页也可能直接显示「重新结账留档」</b>（不代表已经结过账）；"
             "首次若显示「结账并留档」同理。点顶部这个按钮，<b>直到出现「已结账留档」回执</b>（含实际毛利/毛利率）即完成。</p>")

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>司南礼客 · 标准案例演示字段复制表（林晓 / 黄先生 云南 5 日）</title>
<style>
 body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:16px;line-height:1.5;color:#222}}
 h1{{font-size:18px}} h3{{margin:18px 0 6px;font-size:15px;border-bottom:1px solid #ddd;padding-bottom:3px}}
 table{{border-collapse:collapse;width:100%;margin:4px 0 10px}}
 th,td{{border:1px solid #ccc;padding:3px 6px;font-size:13px;vertical-align:top;text-align:left}}
 table.kv th{{width:230px;background:#f6f6f6}}
 table.grid th{{background:#f6f6f6}}
 pre{{white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;padding:8px;font-size:13px}}
 .n{{color:#555;font-size:13px}}
 .bar{{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:6px 0}}
 .hint{{color:#777;font-size:12px}}
 button.cp{{font-size:12px;padding:1px 6px;margin-left:6px;cursor:pointer}}
 td.cpc{{white-space:nowrap;width:70px}}
 .flashed{{background:#dff5df}}
</style>
</head>
<body>
<div class="bar">
  <h1>司南礼客 · 标准案例演示字段复制表（唯一数据源：data/scenario/standard_case.json）</h1>
  <div class="hint">配套完整脚本（同目录）：<a href="./完整演示脚本.txt">完整演示脚本.txt</a>（逐步操作、预期、失败处理）。
  每个字段/每行右侧有「复制」按钮（点一下就进剪贴板）；表头「复制本表」复制整张表。
  不支持剪贴板 API 时（例如 file:// 直接打开）会自动回退为选中文本，按 Ctrl+C 即可。</div>
</div>
{chr(10).join(p for p in parts if p)}
<script>
// 复制：优先 navigator.clipboard；失败回退到"选中文本 + execCommand('copy')"，file:// 也能用。
function tcFlash(el) {{
  el.classList.add('flashed');
  setTimeout(function () {{ el.classList.remove('flashed') }}, 600);
}}
function tcFallbackCopy(text) {{
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  var ok = false;
  try {{ ok = document.execCommand('copy') }} catch (e) {{ ok = false }}
  document.body.removeChild(ta);
  return ok;
}}
function tcCopy(text) {{
  if (!text) return false;
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).catch(function () {{ tcFallbackCopy(text) }});
    return true;
  }}
  return tcFallbackCopy(text);
}}
document.addEventListener('click', function (ev) {{
  var btn = ev.target.closest('button.cp');
  if (!btn) return;
  var text = '';
  if (btn.hasAttribute('data-copy-value')) {{
    text = btn.getAttribute('data-copy-value');
  }} else if (btn.hasAttribute('data-copy-target')) {{
    var span = btn.parentElement.querySelector('.v');
    text = span ? (span.innerText || span.textContent || '') : '';
  }} else if (btn.hasAttribute('data-copy-table')) {{
    var tb = btn.closest('h3') ? btn.closest('h3').nextElementSibling : null;
    if (tb && tb.tagName === 'TABLE') {{
      var lines = [];
      tb.querySelectorAll('tr').forEach(function (tr) {{
        var cells = [];
        tr.querySelectorAll('th,td').forEach(function (c) {{
          if (c.classList.contains('cpc')) return;
          var sp = c.querySelector('.v');
          cells.push((sp ? (sp.innerText || sp.textContent) : (c.innerText || c.textContent) || '').trim());
        }});
        if (cells.length) lines.push(cells.join('\\t'));
      }});
      text = lines.join('\\n');
    }}
  }}
  var ok = tcCopy(text);
  var old = btn.textContent;
  btn.textContent = ok ? '已复制' : '请 Ctrl+C';
  tcFlash(btn);
  setTimeout(function () {{ btn.textContent = old }}, 900);
}});
</script>
</body>
</html>
"""

OUT.write_text(HTML, encoding="utf-8", newline="\n")
print(f"生成：{OUT}（{len(HTML)} 字符）")
print(f"章节数：{HTML.count('<h3>')}；表格数：{HTML.count('<table')}")
