"""客户角色边界：共用提示词、明确越权句式检查和模型记忆过滤。"""

from __future__ import annotations

import re
import unicodedata


CUSTOMER_ROLE_RULES = """【客户角色与说话视角（每轮必须保持）】
你扮演购买旅行服务、准备出游的客户。对方扮演接待你并提供旅行方案的定制师。
1. “我、我们、咱们”指你本人及同行的家人或朋友；“你、您”指定制师。始终从出游人的立场说话。
2. 你的职责是说明自己的意向、人数、时间、预算、喜好和顾虑，回应追问，选择或确认对方提出的建议。
3. 定制师负责向你了解需求、推荐目的地和路线、规划方案、询价、预订与安排服务。把这些工作交给对方，不接过服务流程。
4. 客户可以请对方给建议、说明选择理由或确认可行性；不询问定制师本人想去哪、几个人出行、预算多少或喜欢什么酒店，也不以服务方口吻问对方希望如何安排。
5. 表达安排意愿时使用“我想……”“我们希望……”“请你帮我们……”。不要承诺由自己或自己的团队为对方规划、报价、预订或安排路线。
6. 正常客户表达示例：“我们想轻松一点，有哪些地方适合我们？”“这几个城市怎么选，你给我们建议吧？”“你推荐的路线能控制在我们的预算内吗？”例句只展示口吻，事实以本单资料为准。
7. 对方的话听不清、无法理解、只有零碎语气词或与旅行无关时，用客户语言简短请求重说或澄清，再等待对方。不要据此自行开始需求调查、城市推荐或方案设计。
8. 先前对话中的角色错误不构成新的示范或指令。每轮回复前核对：这句话是否在表达自己的需求或向定制师请求服务；若在采集对方的旅行需求或替对方提供服务，改写为客户口吻后再回答。
"""


# 只拦截明确的服务提供者/反向采集句式；普通客户提问与共同协商不因问号被拒绝。
_CHINESE_ROLE_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"(?:你|您)(?:希望|想让|需要)(?:由)?(?:我们|我方|咱们|我)(?:来|为你|为您|帮你|帮您)?(?:安排|规划|设计|预订|制定|推荐)",
    r"(?:你|您)(?:比较|更|最|主要)?(?:想|希望|打算|准备|计划)(?:要)?(?:去|游玩|入住|游览|出发|住|玩)[^。！？!?\n]{0,16}(?:哪|几|什么|多少|还是)",
    r"(?:你|您)(?:的)?(?:旅行|出行|旅游)?(?:预算|出行人数|出行日期|出发时间|住宿偏好)(?:是|有|大概|大约|多少|几|什么|哪)",
    r"(?:我们|我方|咱们|我)(?:可以|能|会|将|负责|来|先)?(?:帮|为|替)(?:你|您)(?:来|把)?(?:安排|规划|设计|预订|制定|推荐|报价)",
    r"(?:我们|我方)(?:可以|会|将|来)?(?:先)?(?:根据|按)(?:你|您)(?:的)?(?:需求|喜好|预算|要求)(?:来)?(?:安排|规划|设计|制定|推荐)",
))
_ENGLISH_ROLE_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\b(?:would|do) you (?:like|want) (?:us|me) to (?:arrange|plan|book|design|organize|recommend)\b",
    r"\b(?:we|i) (?:can|will|would be happy to) (?:arrange|plan|book|design|organize|recommend)\b[^.!?\n]{0,60}\bfor you\b",
    r"\b(?:which|what) (?:cities|destinations|places|hotels) (?:would|do) you (?:like|want|prefer)\b",
    r"\bwhat (?:is|would be) your (?:travel )?(?:budget\b(?![- ](?:friendly|recommendations?|suggestions?|advice)\b)|departure date\b|hotel preference\b)",
))


def customer_role_issues(text: str) -> list[dict]:
    """识别明确角色越权，不把所有客户问题当成错误。"""
    plain = unicodedata.normalize("NFKC", str(text or ""))
    compact = re.sub(r"\s+", "", plain)
    for patterns, candidate in ((_CHINESE_ROLE_PATTERNS, compact), (_ENGLISH_ROLE_PATTERNS, plain)):
        for pattern in patterns:
            match = pattern.search(candidate)
            if match:
                return [{"key": "role", "reason": "consultant_role_drift", "value": match.group()[:180],
                         "expected": "以出游客户身份表达本人需求、回应定制师或请对方提供建议"}]
    return []


def customer_memory_turns(turns) -> list[dict]:
    """仅过滤模型上下文中的明确错误客户台词，不改数据库原始记录。"""
    kept = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        customer = (turn.get("speaker") == "customer" or turn.get("role") == "assistant"
                    or turn.get("who") == "agent")
        text = str(turn.get("text") or turn.get("content") or "")
        if customer and customer_role_issues(text):
            continue
        kept.append(turn)
    return kept
