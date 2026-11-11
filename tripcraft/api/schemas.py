"""公开请求 DTO（由 api/app.py 的路由块机械拆分而来）。

对外契约：所有请求体模型集中在此；路由模块统一 `from tripcraft.api import schemas as S`。

v2（安全收紧，Lead 冻结）：
- 请求体里的 `user_id` **不是身份**，只是可选的「自报标识」。
  调用方必须用 `Depends(current_user)` 拿服务端会话身份；
  若需要校验自报值，用 `security.require_self(body.user_id, user)`。
- 因此所有 `user_id` 默认值统一改为 `""`（空 = 未自报）。
  旧默认值 `"u-demo"` / `"u1"` 会被 require_self 误判成「冒用他人」，也是硬编码用户的残留。
- 路由不得再以 `body.user_id` 作为查询/写入的身份来源。
"""

from __future__ import annotations

from pydantic import BaseModel

from tripcraft.contracts.deliverables import Deliverable  # noqa: F401  (类型引用)
from tripcraft.contracts.enums import DeliverableKind, StepId


# ---------------- 请求模型（必须定义在模块级，否则 FastAPI 无法解析） ----------------

class CreateRun(BaseModel):
    user_id: str = ""
    template_id: str = "tpl1"
    inbound: bool = True
    language: str = "中文"


class FlagBody(BaseModel):
    name: str
    value: bool = True


class DeliverableBody(BaseModel):
    kind: DeliverableKind
    step: StepId
    payload: dict = {}


class RollbackBody(BaseModel):
    to_step: StepId
    reason: str = ""


class TranslateBody(BaseModel):
    text: str
    target: str = "English"


class AbilityBody(BaseModel):
    skill_point_id: str
    value: float
    field: str = "teach"      # teach = 教学侧；real = 实战侧


class LearningRouteBody(BaseModel):
    demand: str = ""

class LearningRouteReviseBody(BaseModel):
    message: str

class AssessmentBody(BaseModel):
    user_id: str = ""
    answers: list[dict] = []
    language: str = "中文"


class CreateS2(BaseModel):
    user_id: str = ""
    inbound: bool = True
    language: str = "中文"


class SendMessage(BaseModel):
    text: str


class ThreadMsg(BaseModel):
    user_id: str = ""
    text: str


class ThreadAssetBody(BaseModel):
    user_id: str = ""
    kind: str


class ThreadQuizAnswer(BaseModel):
    user_id: str = ""
    question: dict = {}
    answer: str = ""


class SupplierBody(BaseModel):
    kind: str
    request: str
    order_id: str = ""          # 带上订单：口径与群里一致，并登记为询价证据


class DeliverableBody2(BaseModel):
    kind: str
    content: str
    customer: str = "客户"
    order_id: str = ""


class CallSay(BaseModel):
    text: str


class DeliverableSubmit(BaseModel):
    values: dict = {}
    file_ids: list[str] = []
    targets: list[str] = []      # 发在给谁：会话 ID 列表（客户群 / 地接群 / 司导群 / 单聊）
    submit_once: bool = False   # 文件夹工作台：已提交后不重复投递；方案版本入口保持原有语义。


class DeliverableTemplateImport(BaseModel):
    drafts: dict[str, dict] = {}  # 本页尚未提交的手工编辑，导入时保留。


class DeliverablePreview(BaseModel):
    values: dict = {}


class PlanBody(BaseModel):
    values: dict = {}
    note: str = ""


class PlanSendBody(BaseModel):
    targets: list[str] = []


class TemplateBody(BaseModel):
    user_id: str = ""
    name: str
    sections: list = []
    kind: str = "plan"


class FileUpload(BaseModel):
    filename: str
    mime: str = "application/octet-stream"
    data_b64: str
    order_id: str = ""
    deliverable_id: str = ""


class ActionBody(BaseModel):
    action: str


class DispatchGenerateBody(BaseModel):
    user_id: str = ""
    count: int = 1
    language: str = ""        # ""=随机各国；否则只生成说这种语言的客源


class CalibrationBody(BaseModel):
    repeats: int = 1
    limit: int = 0


class GuardBody(BaseModel):
    kind: str
    content: str
    order_id: str = ""
    geo: bool = False


class DirectorEventBody(BaseModel):
    type: str
    payload: dict = {}


class ReviewBody(BaseModel):
    decision: str = "accept"
    score: float | None = None


class SupplierStateBody(BaseModel):
    user_id: str = ""
    kind: str
    availability: str = ""
    price_factor: float = 0.0
    note: str = ""


class ItineraryBody(BaseModel):
    stops: list[str] = []


class FinanceDecideBody(BaseModel):
    bearer: str                 # 我方 | 资源方 | 客户
    note: str = ""


class ImMsg(BaseModel):
    sender: str
    role: str = "me"
    content: str
    kind: str = "text"            # text / file / card
    payload: dict = {}
    order_id: str = ""            # 资源大群/自建群里，明确这一句属于哪一单
    target_role: str = ""         # 资源大群/自建群需明确找谁：酒店/车队/地接社/票务/导游


class ContactBody(BaseModel):
    order_id: str
    kind: str


class RenameBody(BaseModel):
    name: str


class RemarkBody(BaseModel):
    remark: str = ""


class MembersBody(BaseModel):
    names: list[str] = []


class ImSessionBody(BaseModel):
    user_id: str = ""
    order_id: str = ""
    name: str
    kind: str = "客户"
    members: list[str] = []
