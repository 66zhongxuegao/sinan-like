"""流程通关驱动 —— 平台 8 态的门槛定义（PRD 第 3 / 6 章）。

原来的门槛是「文案 + 伪随机勾选」，学员做完了也不会推进。现在每一道门槛都绑定
**一个可验证的学员动作**；本阶段门槛全部达成，订单才推进到下一个平台状态。

设计口径：
- 动作要么由接口自动登记（抢单、首呼、交付物通过拦截网），要么由学员显式确认
  （客户已确认、合同已签、保险已买、定金到账…）——后者在真实平台里也是点按钮确认的。
- 时限用「接单时间 → 动作时间」的差值考核；超时留痕，补做后允许推进。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 动作

ACTION_LABELS: dict[str, str] = {
    "grab": "抢单",
    "first_call": "首呼",
    # 交付物投递动作：必须与 contracts/deliverables_spec.py 的 auto_actions 逐一对应。
    # 缺一个 label 的后果不是「少一行日志」——deliverable_service 只登记 is_known_action() 为真的动作，
    # 漏登记会让该阶段的门槛证据链断掉（标准案例走到出团通知/结算/复盘时表现为 blocked_by_contract）。
    "deliverable:需求确认单": "投递需求确认单",
    "deliverable:资源询价记录": "投递资源询价记录",
    "deliverable:行程方案": "投递行程方案",
    "deliverable:分项报价": "投递分项报价",
    "deliverable:合同与保险": "投递合同与保险",
    "deliverable:出团通知书": "投递出团通知书",
    "deliverable:地接结算核对单": "投递地接结算核对单",
    "deliverable:回访与复盘记录": "投递回访与复盘记录",
    "guard_pass:分项报价": "报价通过双层拦截网",
    "customer_confirmed_plan": "客户确认方案",
    "contract_signed": "合同已生成",
    "insurance_bought": "保险已购买",
    "customer_signed_contract": "客户已签署合同",
    "deposit_paid": "定金/首款已到账",
    "resources_locked": "资源已锁定",
    "pre_trip_notice": "出团通知书已送达",
    "depart": "客户出团",
    "settlement_verified": "账目核对一致",
    "balance_paid": "尾款已结清",
    "review_done": "客户回访与复盘完成",
}

# 学员可以在界面上直接确认的动作（其余由接口自动登记）
MANUAL_ACTIONS: tuple[str, ...] = (
    "customer_confirmed_plan", "contract_signed", "insurance_bought",
    "customer_signed_contract", "deposit_paid", "resources_locked",
    "pre_trip_notice", "settlement_verified", "balance_paid", "review_done",
)


@dataclass(frozen=True)
class Gate:
    action: str
    label: str
    hint: str
    within_min: int = 0      # >0 时，距 grabbed_at 的分钟上限
    where: str = ""          # 这件事在哪个界面的哪里做（学员看得到，评分也知道去哪找）


from ..contracts.steps import STEP_EVIDENCE   # 13 步产出位置（提示 + 评分说明）



# ---------------------------------------------------------------- 门槛

# key = 当前平台状态序号；门槛全部达成才能离开该状态
GATES: dict[int, tuple[Gate, ...]] = {
    0: (
        Gate("grab", "抢单成功", "在消息中心点「抢单」接手本单", where="消息中心 › 待接单"),
        Gate("first_call", "首呼已完成", "在派单时限内拨打客户电话；超时补做后可继续，时效单独考核", within_min=60,
             where="订单管理 › 打开该单 › 拨打电话"),
        Gate("deliverable:需求确认单", "需求确认单已产出", "填写需求确认单并投递",
             where="产出与投递 › 需求确认单（发客户群）"),
    ),
    1: (
        Gate("deliverable:行程方案", "行程方案已产出", "填写逐日行程并投递",
             where="产出与投递 › 行程方案（标题与逐日六要素自己写）"),
        Gate("deliverable:分项报价", "分项报价已产出", "填写分项报价并投递",
             where="产出与投递 › 分项报价单"),
        Gate("guard_pass:分项报价", "报价通过双层拦截网", "保证分项求和与总价一致、含保险项",
             where="提交分项报价单时自动校验"),
        Gate("customer_confirmed_plan", "客户确认最终方案", "确认客户已认可当前版本",
             where="聊天界面 › 客户服务群（拿到客户明确回复后再标记）"),
    ),
    2: (
        Gate("contract_signed", "合同已生成", "生成并发送合同",
             where="产出与投递 › 合同与保险"),
        Gate("insurance_bought", "保险已购买", "为客人投保（定制游必须买）",
             where="产出与投递 › 合同与保险（保单号必填）"),
    ),
    3: (
        Gate("customer_signed_contract", "客户已签署合同", "确认客户回签",
             where="产出与投递 › 合同与保险（签署状态 = 已签署）"),
        Gate("deposit_paid", "定金/首款已到账", "确认收款",
             where="产出与投递 › 合同与保险（定金状态 = 已到账）"),
    ),
    4: (
        Gate("resources_locked", "资源已锁定", "订房、订车、订票、订导游并预留",
             where="聊天界面 › 地接 / 酒店 / 车队 / 票务群（谈好并锁定）"),
        Gate("pre_trip_notice", "出团通知书已送达", "行前 1–2 天发出团通知并确认收到",
             where="产出与投递 › 出团通知书 → 发客户群 + 地接 / 司导群"),
    ),
    5: (
        Gate("settlement_verified", "账目核对一致", "拿地接结算单与报价单逐项核对",
             where="产出与投递 › 地接结算核对单；成本与结算页可先看实际账"),
    ),
    6: (
        Gate("balance_paid", "尾款已结清", "确认尾款支付完成",
             where="聊天界面 › 地接群（结算沟通）；成本与结算页"),
        Gate("review_done", "客户回访与复盘完成", "完成回访并记录实际利润",
             where="产出与投递 › 回访与复盘记录"),
    ),
    7: (),   # 订单完成，无后续门槛
}

MAX_STAGE = 7


def gates_for(stage: int) -> tuple[Gate, ...]:
    return GATES.get(min(max(stage, 0), MAX_STAGE), ())


def is_known_action(action: str) -> bool:
    return action in ACTION_LABELS


def stage_hint(stage: int) -> str:
    """当前阶段一句话目标（给学员看，不暴露内部步骤口径）。"""
    return {
        0: "抢单后 1 小时内联系客户，并把需求确认单整理出来",
        1: "把行程方案与分项报价做出来，报价先过校验，再请客户确认",
        2: "生成合同并为客人投保",
        3: "跟进客户签署合同并收取定金",
        4: "锁定房间/车辆/票务/导游，发出团通知书",
        5: "行程结束后拿地接结算单与自己的报价逐项核对",
        6: "结清尾款，完成客户回访与复盘",
        7: "本单已完成",
    }.get(min(max(stage, 0), MAX_STAGE), "")
