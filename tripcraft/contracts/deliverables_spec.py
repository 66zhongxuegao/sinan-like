"""交付物契约 —— 每一步「交什么、什么格式、发给谁、怎么校验」（PRD 第 8 / 10 章）。

一个交付物 = 结构化字段 + 渲染器 + 发送对象 + 适用校验。
学员填**结构化表单**而不是自由文本，系统渲染成正式文档；渲染结果同时是两个 Agent 的输入：
  - 客户 Agent：读渲染文档给反馈（`audience` 含「客户」时）
  - 评分 Agent：渲染文档写进 `order_evidence`，作为该步骤的评分素材
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# 发送对象
CUSTOMER = "客户"
PLATFORM = "平台"
SUPPLIER = "地接社"
INTERNAL = "内部"

# 两份行后文件均成功提交即完成一次训练；提交先后顺序不限制。
PRACTICE_FINAL_CODES = ("settlement", "review")


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    width: str = ""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str = "text"           # text | textarea | number | date | select | rows | file
    required: bool = False
    placeholder: str = ""
    help: str = ""
    unit: str = ""
    options: tuple[str, ...] = ()
    columns: tuple[Column, ...] = ()   # type == rows
    # 内部字段：只进内部渲染（拦截网 / 评分 / 财务 / 台账），**绝不进客户输出**
    # （客户输出 = 预览、PDF、客户聊天卡片、客户 Agent 反馈上下文）
    internal: bool = False

    @property
    def is_rows(self) -> bool:
        return self.type == "rows"


@dataclass(frozen=True)
class DeliverableSpec:
    id: str                      # 中文名（展示与证据用）
    code: str                    # ASCII 标识（URL / 代码用）
    step: str                    # 13 步落点，决定考哪些技能点
    audience: tuple[str, ...]    # 发给谁
    title: str
    purpose: str
    fields: tuple[Field, ...]
    filename: str
    surface: str = "document"     # 工作台归类：platform 平台提交 / document 发给对方 / ledger 内部台账
    checks: tuple[str, ...] = ()  # 适用的拦截网类型
    extra_sections: tuple[tuple[str, str], ...] = ()   # 渲染时的附加说明区块
    auto_actions: tuple[str, ...] = ()   # 提交后无条件登记的门槛动作
    # 条件动作：(action, 字段 key, 期望值)——字段等于期望值时才登记
    conditional_actions: tuple[tuple[str, str, str], ...] = ()


def _f(key, label, type="text", required=False, placeholder="", help="", unit="", options=(),
       columns=(), internal=False):
    return Field(key, label, type, required, placeholder, help, unit, tuple(options),
                 tuple(columns), internal)


# ---------------------------------------------------------------- 逐日行程列（C3.1 六要素）

DAY_COLUMNS = (
    Column("day", "天次"), Column("time", "时间"), Column("transport", "交通+耗时"),
    Column("spot", "景点"), Column("meal", "餐食"), Column("hotel", "住宿"), Column("guide", "导游"),
)
QUOTE_COLUMNS = (Column("name", "项目"), Column("desc", "说明"), Column("qty", "数量"),
                 Column("price", "单价"), Column("amount", "金额"))
COMPARE_COLUMNS = (Column("supplier", "资源方"), Column("price", "报价"), Column("included", "含项"),
                   Column("cancel", "取消政策"), Column("reputation", "口碑"))
SETTLE_COLUMNS = (Column("item", "项目"), Column("supplier", "地接结算"), Column("ours", "我方报价"),
                  Column("diff", "差异"), Column("note", "说明"))


DELIVERABLES: tuple[DeliverableSpec, ...] = (
    DeliverableSpec(
        id="需求确认单", code="requirement_sheet", step="S3", audience=(CUSTOMER, PLATFORM),
        title="需求确认单", filename="需求确认单.md",
        purpose="把客户口语需求整理成四分类并让客户确认，作为后续方案与报价的依据",
        checks=("需求确认单",), auto_actions=("deliverable:需求确认单",),
        fields=(
            _f("guest", "客人称呼", required=True, placeholder="如 王女士"),
            _f("source", "客源地", placeholder="如 香港"),
            _f("people", "出行人数", required=True, placeholder="如 3 大 1 小"),
            _f("dates", "出行日期", required=True, placeholder="如 10 月 20 日–24 日，5 天"),
            _f("route", "目的地与城市", placeholder="如 昆明 / 大理 / 丽江"),
            _f("must", "必须满足", "textarea", required=True, placeholder="日期、人数、预算上限、住宿标准…"),
            _f("want", "希望满足", "textarea", placeholder="节奏、偏好景点、餐食…"),
            _f("alternative", "可替代", "textarea", placeholder="酒店可降档、用车可换…"),
            _f("refuse", "明确不要", "textarea", placeholder="不去的地方、不接受的方式…"),
            _f("budget", "预算范围", "textarea", required=True, placeholder="人均还是总价？区间？含不含大交通？"),
            _f("docs", "证件与入境", placeholder="回乡证 / 台胞证 / 护照+签证…"),
            _f("taboo", "饮食与宗教禁忌", placeholder="如 清真、忌猪肉与酒"),
            _f("decision", "决策人", placeholder="由谁拍板"),
            _f("note", "其他备注", "textarea"),
        ),
        extra_sections=(("确认方式", "请客户逐项确认；有异议的条目在上方对应项里标注。"),),
    ),
    DeliverableSpec(
        id="资源询价记录", code="resource_quote", step="S4", audience=(INTERNAL,),
        title="资源询价记录", filename="资源询价记录.md",
        purpose="记录向资源方确认到的可用性、价格与时限，并做比价",
        fields=(
            _f("supplier", "资源方", required=True, placeholder="如 XX地接 / XX酒店"),
            _f("kind", "资源类型", "select", required=True,
               options=("酒店", "用车", "门票", "导游", "票务", "组合")),
            _f("quote", "报价明细", "textarea", required=True, placeholder="房型/车型/票价 + 单价 + 单位"),
            _f("availability", "可用性与档期", required=True, placeholder="有 / 紧张 / 无"),
            _f("included", "含项与不含项", "textarea", placeholder="含司机油费？含早？含税？"),
            _f("deadline", "回复时限", placeholder="如 今天 18 点前确认"),
            _f("compare", "比价（≥2 家）", "rows", columns=COMPARE_COLUMNS,
               help="至少两家，比较价格 / 含项 / 取消政策 / 口碑"),
            _f("backup", "备选方案与触发条件", "textarea", placeholder="主选 A；若 X 发生则换 B，价差 Y"),
            _f("note", "备注", "textarea"),
        ),
    ),
    DeliverableSpec(
        id="行程方案", code="itinerary", step="S5", audience=(CUSTOMER, PLATFORM),
        title="行程方案", filename="行程方案.md",
        purpose="逐日六要素齐全、时间可衔接的行程；不确定资源要有备选与触发条件",
        checks=("行程方案",), auto_actions=("deliverable:行程方案",),
        fields=(
            _f("title", "方案标题", required=True, placeholder="如 香港客人 云南 5 日定制行程"),
            _f("dates", "出发 / 返程", required=True, placeholder="10 月 20 日 – 10 月 24 日"),
            _f("people", "出行人数", required=True, placeholder="3 大 1 小"),
            _f("days", "逐日行程", "rows", required=True, columns=DAY_COLUMNS,
               help="每天写全六要素：时间 / 交通+耗时 / 景点 / 餐食 / 住宿 / 导游"),
            _f("vehicle", "交通与用车", "textarea", placeholder="车型、座位、是否含司机与油费"),
            _f("hotel", "住宿安排", "textarea", placeholder="酒店名称、星标、位置、含早、确认状态"),
            _f("tickets", "门票与预约", "textarea", placeholder="景点门票、是否需实名预约"),
            _f("insurance", "保险与合规", "textarea", placeholder="保险类型、保额、是否已投保；景区预约与实名要求"),
            _f("entry", "入境与证件提醒", "textarea", placeholder="回乡证 / 台胞证 / 签证免签、证件有效期"),
            _f("backup", "备选方案", "textarea", placeholder="主选 A（已确认）；若 X 发生则换 B（已确认，价差 Y）"),
            _f("note", "备注", "textarea"),
        ),
    ),
    DeliverableSpec(
        id="分项报价", code="quotation", step="S6", audience=(CUSTOMER, PLATFORM),
        title="分项报价单", filename="分项报价.md",
        purpose="分项列清、算术自洽、含保险、留出涨价空间；资源未确认前只给待确认价",
        checks=("分项报价",), auto_actions=("deliverable:分项报价", "guard_pass:分项报价"),
        fields=(
            _f("people", "出行人数", required=True, placeholder="如 3 大 1 小"),
            _f("dates", "出行日期", required=True, placeholder="如 10 月 20 日–24 日，5 天"),
            _f("items", "分项明细", "rows", required=True, columns=QUOTE_COLUMNS,
               help="一行一项：项目 / 说明 / 数量 / 单价 / 金额"),
            _f("total", "合计金额", "number", required=True, unit="元"),
            _f("per_person", "人均", "number", unit="元"),
            _f("cost", "成本（内部）", "number", unit="元", internal=True,
               help="地接/资源采购成本，用于算毛利；只进内部核算，不会出现在客户看到的文档里"),
            _f("insurance", "保险项", required=True, placeholder="如 旅游意外险 30 万，60 元/人"),
            _f("pending", "待确认项与锁定时限", "textarea", placeholder="酒店与用车待确认，资源方 2 小时内回复后锁定"),
            _f("fx", "汇率与支付（入境单）", "textarea", placeholder="汇率与锁价时间、支付方式、手续费承担、发票/收据"),
            _f("note", "说明", "textarea"),
            _f("internal_note", "内部核算说明（不发给客户）", "textarea", internal=True,
               help="成本、毛利、返点等只给自己看的数字写这里；它只进内部档案，不会出现在客户输出（预览 / PDF / 客户卡片）里"),
        ),
    ),
    DeliverableSpec(
        id="合同与保险", code="contract", step="S8", audience=(PLATFORM, CUSTOMER),
        title="合同与保险", filename="合同与保险.md",
        purpose="合同签署、保险购买、定金到账三项齐全且凭证可查、顺序合规",
        checks=("合同与保险",), auto_actions=("deliverable:合同与保险", "contract_signed", "insurance_bought"),
        conditional_actions=(("customer_signed_contract", "customer_signed", "已签署"),
                             ("deposit_paid", "deposit_state", "已到账")),
        fields=(
            _f("contract_no", "合同编号", required=True, placeholder="如 HT-20261008-17"),
            _f("sign_date", "签署日期", "date", required=True),
            _f("sign_way", "签署方式", "select", options=("线上电子签", "线下纸质", "门店面签")),
            _f("policy_no", "保单号", required=True, placeholder="如 PL-88213456"),
            _f("insurer", "承保公司", placeholder="如 XX 保险"),
            _f("insure_date", "投保日期", "date", required=True),
            _f("coverage", "保额", placeholder="如 意外 30 万 / 医疗 5 万"),
            _f("deposit", "定金金额", "number", unit="元"),
            _f("deposit_at", "到账时间", placeholder="2026-10-08 11:02"),
            _f("customer_signed", "客户签署状态", "select", required=True, options=("已签署", "待签署")),
            _f("deposit_state", "定金状态", "select", required=True, options=("已到账", "未到账")),
            _f("pay_way", "付款方式", "select", options=("对公转账", "线上支付", "信用卡", "其他")),
            _f("order_note", "配合项说明", "textarea", placeholder="是否已按顺序：先合同 → 再保险 → 后付款"),
        ),
    ),
    DeliverableSpec(
        id="出团通知书", code="departure_notice", step="S9", audience=(CUSTOMER, SUPPLIER),
        title="出团通知书", filename="出团通知书.md",
        purpose="行前 1–2 天送达，含集合、联系人、每日要点、证件与禁忌提醒，并取得确认",
        auto_actions=("deliverable:出团通知书", "resources_locked", "pre_trip_notice"),
        fields=(
            _f("gather", "集合时间与地点", required=True, placeholder="10 月 20 日 09:00，昆明长水机场 T1"),
            _f("guide", "导游 / 司机与电话", required=True, placeholder="导游 小周 138**** / 司机 赵师傅 139****"),
            _f("contact", "紧急联络人", placeholder="定制师 小李 137****（24 小时）"),
            _f("daily", "每日要点", "textarea", placeholder="每天集合时间、行程重点、注意事项"),
            _f("docs", "证件与随身物品", "textarea", placeholder="证件、充电、雨具、常用药"),
            _f("taboo", "饮食与禁忌提醒", "textarea", placeholder="已按清真/无猪肉无酒安排，餐厅名单见附件"),
            _f("weather", "天气与穿着", "textarea", placeholder="昆明 15–24℃，早晚温差大"),
            _f("confirm", "确认方式", "textarea", placeholder="已发微信群，请回复「收到」"),
        ),
    ),
    DeliverableSpec(
        id="地接结算核对单", code="settlement", step="S11", audience=(INTERNAL,),
        title="地接结算核对单", filename="地接结算核对单.md",
        purpose="拿地接结算单与自己的报价逐项核对，记录差异原因与处理决定",
        checks=(), auto_actions=("deliverable:地接结算核对单", "settlement_verified"),
        fields=(
            _f("settle_no", "结算单号", required=True, placeholder="如 JS-20261024-03"),
            _f("items", "逐项核对", "rows", required=True, columns=SETTLE_COLUMNS,
               help="项目 / 地接结算 / 我方报价 / 差异 / 说明"),
            _f("total_settle", "地接结算合计", "number", unit="元"),
            _f("total_ours", "我方报价合计", "number", unit="元"),
            _f("diff", "合计差异", "number", unit="元"),
            _f("actual_cost", "实际成本", "number", unit="元", internal=True),
            _f("actual_margin", "实际毛利", "number", unit="元", internal=True),
            _f("reason", "差异原因", "textarea", placeholder="哪几项对不上、为什么"),
            _f("decision", "处理决定", "textarea", placeholder="据实结算 / 要求核减 / 走申诉"),
        ),
    ),
    DeliverableSpec(
        id="回访与复盘记录", code="review", step="S12", audience=(INTERNAL,),
        title="回访与复盘记录", filename="回访与复盘记录.md",
        purpose="回访客户、记录投诉与补救、核算实际利润，并写清本单复盘",
        auto_actions=("deliverable:回访与复盘记录", "review_done"),
        conditional_actions=(("balance_paid", "balance_state", "已结清"),),
        fields=(
            _f("time", "回访时间与方式", required=True, placeholder="2026-10-26 电话 15 分钟"),
            _f("satisfaction", "满意度", "select", required=True,
               options=("非常满意", "满意", "一般", "不满意")),
            _f("quote", "客户原话", "textarea", placeholder="客户最能说明问题的一句原话"),
            _f("issue", "问题与投诉", "textarea"),
            _f("remedy", "补救措施", "textarea"),
            _f("balance_state", "尾款状态", "select", required=True, options=("已结清", "未结清")),
            _f("profit", "实际利润", "number", unit="元", internal=True),
            _f("good", "做得好的", "textarea"),
            _f("improve", "待改进的", "textarea", required=True),
            _f("next", "下一步动作", "textarea", placeholder="针对性补练哪个技能点"),
        ),
    ),
)

# ---------------------------------------------------------------- 交付物归类与自由编辑

# 真实场景里这三类产出走的地方完全不同：
#   platform —— 平台里的固定表单（合同号、保单号、录单信息），系统要什么填什么；
#   document —— 要发给客户/地接的文档（方案、报价、出团通知），既要结构清楚，也要能自己写；
#   ledger   —— 只有自己看的内部台账（询价比价、结算核对、回访复盘）。
SURFACE = {
    "需求确认单": "document",
    "资源询价记录": "ledger",
    "行程方案": "document",
    "分项报价": "document",
    "合同与保险": "platform",
    "出团通知书": "document",
    "地接结算核对单": "ledger",
    "回访与复盘记录": "ledger",
}

# 每一步都留一段自由正文：补充说明、注意事项、想强调的事，学员自己写。
# 固定字段保证平台与评分能核对，自由正文保证表达不被模板阉割。
FREEFORM = _f("freeform", "补充说明（发给对方）", "textarea",
              help="这一段会随文档发给对方（客户 / 地接）：写注意事项、提醒、给对方的信息；"
                   "成本、毛利这类只给自己看的内容请写到「内部核算说明」那一栏")

DELIVERABLES = tuple(
    replace(d, surface=SURFACE.get(d.id, "document"), fields=d.fields + (FREEFORM,))
    for d in DELIVERABLES)

BY_ID: dict[str, DeliverableSpec] = {d.id: d for d in DELIVERABLES}
BY_CODE: dict[str, DeliverableSpec] = {d.code: d for d in DELIVERABLES}


def resolve(key: str) -> DeliverableSpec | None:
    """中文名或 ASCII code 都能定位交付物。"""
    return BY_ID.get(key) or BY_CODE.get(key)


def specs_for_step(step: str) -> tuple[DeliverableSpec, ...]:
    return tuple(d for d in DELIVERABLES if d.step == step)


# ---------------------------------------------------------------- 渲染

def _rows_to_table(columns: tuple[Column, ...], rows: list[dict]) -> str:
    head = "| " + " | ".join(c.label for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for r in rows or []:
        cells = [str((r or {}).get(c.key, "") or "").replace("|", "／").replace("\n", " ") for c in columns]
        if not any(cells):
            continue
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep] + body)


# 客户可见文案里不得出现的内部口径（出现即从客户输出中剔除，并记入 withheld 供学员知情）
CUSTOMER_LEAK_TERMS: tuple[str, ...] = (
    "成本", "毛利", "利润率", "毛利率", "采购价", "进货价", "底价", "返点", "净赚", "加价率",
)


def _customer_safe_text(text: str) -> tuple[str, list[str]]:
    """逐行剔除含内部口径的句子：客户输出只保留可以给客户看的内容。

    返回 (保留的文本, 被剔除的词)。整段都被剔除时返回空串——文档里不留任何「已隐藏」痕迹，
    学员的知情通过接口的 `customer_withheld` 与工作台提示完成。
    """
    kept: list[str] = []
    dropped: list[str] = []
    for line in str(text or "").splitlines():
        hit = [t for t in CUSTOMER_LEAK_TERMS if t in line]
        if hit:
            dropped.extend(hit)
            continue
        kept.append(line)
    return "\n".join(kept).strip(), sorted(set(dropped))


def is_customer_facing(spec: DeliverableSpec) -> bool:
    """这份交付物会不会真的发给客户。

    只有 `audience` 含「客户」的文档才做客户化（脱敏）处理；
    内部/地接专用文档（资源询价、地接结算核对单、回访与复盘记录）保留自身核算内容。
    """
    return CUSTOMER in spec.audience


def render(spec: DeliverableSpec, values: dict[str, Any], context: dict[str, Any] | None = None,
           audience: str = "internal") -> str:
    """把结构化字段渲染成正式文档（Markdown）。

    `audience="internal"`（默认）＝内部档案：含内部字段（成本等）与核算汇总，
    用于拦截网算术校验、评分证据、财务与台账；
    `audience="customer"`＝**客户输出**：不含任何 internal 字段、不含核算汇总，
    且客户可见正文里出现内部口径（成本/毛利…）的句子会被剔除。
    客户输出去向：工作台预览、PDF 导出、客户聊天卡片、客户 Agent 反馈上下文。
    """
    ctx = context or {}
    customer_view = audience == "customer"
    out: list[str] = [f"# {spec.title}", ""]
    meta = [f"**订单** {ctx.get('order_id', '—')}", f"**客户** {ctx.get('customer', '—')}",
            f"**客源地** {ctx.get('source_market', '—')}", f"**目的地** {ctx.get('destination', '—')}",
            f"**发送对象** {'、'.join(spec.audience)}"]
    out += ["　".join(meta), "", f"> {spec.purpose}", ""]

    for f in spec.fields:
        if customer_view and f.internal:
            continue                      # 内部字段（成本 / 内部核算说明）不进客户输出
        val = values.get(f.key)
        heading = f"## {f.label}"
        if f.is_rows:
            rows = val if isinstance(val, list) else []
            if customer_view:
                rows = [{k: (v if not isinstance(v, str) else _customer_safe_text(v)[0])
                         for k, v in (r or {}).items()} for r in rows]
                rows = [r for r in rows if any(str(v or "").strip() for v in r.values())]
            if not rows and (val if isinstance(val, list) else []):
                continue                  # 整表内容都被剔除：客户版不保留空壳小节
            out.append(heading)
            out.append(_rows_to_table(f.columns, rows) if rows else "（未填写）")
        elif isinstance(val, list):
            out.append(heading)
            out.append("、".join(str(v) for v in val) or "（未填写）")
        else:
            empty = val in (None, "")
            text = "（未填写）" if empty else str(val).strip()
            if customer_view and not empty:
                safe, _dropped = _customer_safe_text(text)
                if not safe:
                    continue              # 整段都被剔除：客户版连小节标题都不留
                text = safe
            out.append(heading)
            out.append(f"{text}{f.unit if text != '（未填写）' else ''}")
        out.append("")

    for head, body in spec.extra_sections:
        if customer_view:
            body = _customer_safe_text(body)[0]
            if not body:
                continue
        out += [f"## {head}", body, ""]

    # 分项报价的「可核对汇总行」是内部核算（含成本），只进内部渲染；
    # 双层拦截网的算术校验读的是内部渲染，客户版本不需要它。
    if spec.id == "分项报价" and not customer_view:
        out += _quote_summary(values)

    # 页脚面向学员：不再暴露内部文件名（旧版会写「需求确认单.md」这类实现细节，R05/文案审查）
    out += ["---", "（本文件由 TripCraft · 司南礼客 交付物工作台生成，可在工作台下载 PDF 留存）"]
    return "\n".join(out)


def render_for_customer(spec: DeliverableSpec, values: dict[str, Any],
                        context: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """客户输出的渲染结果 + 被剔除的内部口径词（供工作台提示学员）。

    withheld 只统计**客户可见字段**里出现过的内部口径词（内部字段本身不算，
    否则任何报价单都会因为存在「成本」字段而误报）。
    """
    text = render(spec, values, context, audience="customer")
    seen: list[str] = []
    for f in spec.fields:
        if f.internal:
            continue
        raw = values.get(f.key)
        chunks: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    chunks.extend(str(v) for v in item.values())
                else:
                    chunks.append(str(item))
        elif raw not in (None, ""):
            chunks.append(str(raw))
        blob = "\n".join(chunks)
        seen.extend(t for t in CUSTOMER_LEAK_TERMS if t in blob)
    return text, sorted(set(seen))


def _quote_summary(values: dict[str, Any]) -> list[str]:
    lines = ["## 分项汇总（供核对）"]
    total = 0.0
    items = values.get("items") or []
    for it in items:
        amount = it.get("amount")
        if amount in (None, ""):
            try:
                amount = float(it.get("qty") or 0) * float(it.get("price") or 0)
            except (TypeError, ValueError):
                amount = 0
        try:
            total += float(amount or 0)
        except (TypeError, ValueError):
            pass
        if it.get("name"):
            lines.append(f"{it['name']} {amount if amount not in (None, '') else 0} 元")
    declared = values.get("total")
    if declared not in (None, ""):
        lines.append(f"合计 {declared} 元")
    elif items:
        lines.append(f"合计 {round(total)} 元")
    if values.get("cost") not in (None, ""):
        lines.append(f"成本 {values['cost']} 元")
    lines.append("")
    return lines
