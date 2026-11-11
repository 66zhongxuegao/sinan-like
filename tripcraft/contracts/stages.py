"""六阶段共享契约（Lead 冻结 v1）。

用户确认的实战一级阶段是 6 个，底层考核状态仍是 13 个内部步骤（S0–S12）。
本模块是**唯一**的阶段口径来源：前端导航、首页任务路径、订单详情、文档提交、
验收脚本都必须从这里取，不得各自写死编号（旧 StepBar.vue 直接平铺 S0–S12 即为反例）。

契约（v1）：
- `STAGES`           六阶段定义，顺序固定
- `stage_of_step(s)` 内部步骤 → 阶段 id
- `steps_of_stage()` 阶段 id → 内部步骤 id 列表
- `deliverable_stage(code)` 交付物 code → 阶段 id
- `as_payload()`     给前端的 JSON（不含任何隐藏评分信息）
- `INTERNAL_STEP_ORDER`  全量 13 步顺序（保留底层考核状态，只对用户收敛）

映射决策（行前2 的「客户反馈」= 方案发送/已读；行前3 的「反馈迭代」= S7，两者区分开）：
  行前1 ← S0 初始化/交底、S1 抢单、S2 首呼、S3 需求确认
  行前2 ← S4 询价与资源取舍、S5 逐日行程
  行前3 ← S6 报价与利润、S7 反馈迭代、S8 成交与合同
  行前4 ← S9 资源锁定与行前准备
  行中   ← S10 执行与突发处理
  行后   ← S11 结算回访、S12 评分与能力更新

变更本契约必须升版并通知全部 owner（journey / conversation / scenario / identity）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tripcraft.contracts.enums import STEP_NAMES, StepId


@dataclass(frozen=True)
class Substep:
    """阶段内小步骤：用户能看懂的一步，不暴露内部编号。"""

    id: str
    name: str
    hint: str = ""
    step: str = ""          # 对应内部步骤（S0–S12），可为空
    deliverable: str = ""   # 与交付物 code 绑定时可填，例如 requirement_sheet


@dataclass(frozen=True)
class Stage:
    id: str
    name: str
    short: str
    order: int
    steps: tuple[str, ...]
    deliverables: tuple[str, ...]
    focus: str
    substeps: tuple[Substep, ...] = field(default_factory=tuple)

    @property
    def primary_deliverable(self) -> str:
        return self.deliverables[0] if self.deliverables else ""

    def as_payload(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "short": self.short,
            "order": self.order,
            "steps": list(self.steps),
            "deliverables": list(self.deliverables),
            "focus": self.focus,
            "primary_deliverable": self.primary_deliverable,
            "substeps": [
                {"id": s.id, "name": s.name, "hint": s.hint,
                 "step": s.step, "deliverable": s.deliverable}
                for s in self.substeps
            ],
        }


STAGES: tuple[Stage, ...] = (
    Stage(
        id="pre1_requirement",
        name="行前 1 · 需求确认单",
        short="需求确认",
        order=1,
        steps=("S0", "S1", "S2", "S3"),
        deliverables=("requirement_sheet",),
        focus="客户沟通是重点：接单后尽快首呼，把模糊需求问清并复述确认。",
        substeps=(
            Substep("pre1.brief", "接单与规则交底", "看清这一单的客源、语言与时限", step="S0"),
            Substep("pre1.grab", "接单", "在派单时限内接单", step="S1"),
            Substep("pre1.call", "首次电话", "自我介绍、确认通话方便、逐项澄清、复述确认", step="S2"),
            Substep("pre1.clarify", "需求澄清", "把需求结构化：人数、日期、偏好、禁忌、预算", step="S3"),
            Substep("pre1.confirm", "客户确认", "提交《需求确认单》并取得客户确认",
                     step="S3", deliverable="requirement_sheet"),
        ),
    ),
    Stage(
        id="pre2_plan",
        name="行前 2 · 行程方案",
        short="行程方案",
        order=2,
        steps=("S4", "S5"),
        deliverables=("resource_quote", "itinerary"),
        focus="先资源后行程：询价结果与取舍理由要能对上客户需求。",
        substeps=(
            Substep("pre2.quote", "资源询价", "向地接/酒店/车队询价并留证",
                     step="S4", deliverable="resource_quote"),
            Substep("pre2.tradeoff", "资源取舍", "在价格、档期、可服务性之间做取舍并说明理由", step="S4"),
            Substep("pre2.day", "逐日行程", "逐日写清交通、住宿、活动与用餐", step="S5"),
            Substep("pre2.feedback", "客户反馈", "发送方案给客户，收集已读与反馈", step="S5"),
            Substep("pre2.submit", "提交《行程方案》", "按格式要求校验后提交",
                     step="S5", deliverable="itinerary"),
        ),
    ),
    Stage(
        id="pre3_quote",
        name="行前 3 · 报价与成交确认",
        short="报价成交",
        order=3,
        steps=("S6", "S7", "S8"),
        deliverables=("quotation", "contract"),
        focus="报价要能算清利润，成交要有合同与必要子项作证据。",
        substeps=(
            Substep("pre3.price", "分项报价", "分项列价并测算利润",
                     step="S6", deliverable="quotation"),
            Substep("pre3.margin", "利润测算", "成本、毛利、可能损失一目了然", step="S6"),
            Substep("pre3.iterate", "反馈迭代", "按客户反馈改价改方案并留版本", step="S7"),
            Substep("pre3.deal", "成交确认", "客户确认成交", step="S8"),
            Substep("pre3.contract", "合同与必要子项", "合同、保险等必要子项齐全",
                     step="S8", deliverable="contract"),
        ),
    ),
    Stage(
        id="pre4_notice",
        name="行前 4 · 出团通知书",
        short="出团通知",
        order=4,
        steps=("S9",),
        deliverables=("departure_notice",),
        focus="资源锁定 + 行前准备 + 正式通知，三件事都留证。",
        substeps=(
            Substep("pre4.lock", "资源锁定", "把地接、酒店、车队的确认锁定下来", step="S9"),
            Substep("pre4.prepare", "行前准备", "证件、保险、联系人、应急信息齐备", step="S9"),
            Substep("pre4.notice", "正式通知", "向客户与资源方发出《出团通知书》",
                     step="S9", deliverable="departure_notice"),
        ),
    ),
    Stage(
        id="on_trip",
        name="行中服务",
        short="行中服务",
        order=5,
        steps=("S10",),
        deliverables=(),
        focus="执行、突发处理、沟通与证据：每一步都要能回放。",
        substeps=(
            Substep("on.execute", "执行", "按方案推进并记录关键节点", step="S10"),
            Substep("on.incident", "突发处理", "出现事件时先止损、再沟通、留证据", step="S10"),
            Substep("on.comm", "沟通与证据", "与客户/资源方的沟通沉淀为证据", step="S10"),
        ),
    ),
    Stage(
        id="post_trip",
        name="行后复盘",
        short="行后复盘",
        order=6,
        steps=("S11", "S12"),
        deliverables=("settlement", "review"),
        focus="结算回访 → 评分 → 能力更新，闭环回到画像。",
        substeps=(
            Substep("post.settle", "结算回访", "成本损失结清、客户回访",
                     step="S11", deliverable="settlement"),
            Substep("post.score", "评分", "按订单事实评分", step="S12"),
            Substep("post.review", "复盘与能力更新", "复盘并写回能力画像",
                     step="S12", deliverable="review"),
        ),
    ),
)

STAGE_ORDER: tuple[str, ...] = tuple(s.id for s in STAGES)
STAGES_BY_ID: dict[str, Stage] = {s.id: s for s in STAGES}

_BY_STEP: dict[str, str] = {st: s.id for s in STAGES for st in s.steps}
_BY_DELIVERABLE: dict[str, str] = {d: s.id for s in STAGES for d in s.deliverables}

INTERNAL_STEP_ORDER: tuple[str, ...] = tuple(s.value for s in StepId)


def stage_of_step(step: str) -> str:
    """内部步骤 → 阶段 id；未知步骤返回空串（调用方自行兜底）。"""
    return _BY_STEP.get(step, "")


def steps_of_stage(stage_id: str) -> tuple[str, ...]:
    st = STAGES_BY_ID.get(stage_id)
    return st.steps if st else ()


def deliverable_stage(code: str) -> str:
    """交付物 code → 阶段 id（四份文档据此后移到对应阶段，R01）。"""
    return _BY_DELIVERABLE.get(code, "")


def stage_of_deliverable(code: str) -> Stage | None:
    sid = _BY_DELIVERABLE.get(code, "")
    return STAGES_BY_ID.get(sid) if sid else None


def step_label(step: str) -> str:
    """内部步骤的中文名（仅用于内部/复盘展示，不作为主导航）。"""
    try:
        return STEP_NAMES[StepId(step)]
    except (ValueError, KeyError):
        return step


def as_payload() -> dict:
    """前端契约：六阶段 + 子步骤 + 内部步骤名（不含评分答案与隐藏字段）。"""
    return {
        "version": 1,
        "stages": [s.as_payload() for s in STAGES],
        "step_names": {s.value: STEP_NAMES[s] for s in StepId},
        "stage_of_step": dict(_BY_STEP),
        "stage_of_deliverable": dict(_BY_DELIVERABLE),
    }
