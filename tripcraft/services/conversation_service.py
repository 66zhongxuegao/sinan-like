"""Conversation domain: resolve a room, an order and a speaking role before any reply.

This module is intentionally deterministic. A message never asks an LLM "who should
answer"; the route is derived from an existing conversation, its participants and
an optional explicit target role. The order is the only cross-channel anchor:

    conversation -> order -> target role -> agent plan

The service does not write messages. The API/service layer persists the message
after route validation so a failed/ambiguous route cannot create an orphan reply.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


class ConversationError(RuntimeError):
    """A route error with an HTTP-friendly status."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Participant:
    name: str
    kind: str
    agent_id: str = ""
    contact_id: str = ""
    order_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "contact_id": self.contact_id,
            "order_id": self.order_id,
        }


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    user_id: str
    name: str
    kind: str
    conversation_type: str
    code: str
    order_id: str
    participants: tuple[Participant, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "name": self.name,
            "kind": self.kind,
            "conversation_type": self.conversation_type,
            "code": self.code,
            "order_id": self.order_id,
            "participants": [p.as_dict() for p in self.participants],
        }


@dataclass(frozen=True)
class ConversationRoute:
    conversation: Conversation
    order_id: str
    target_role: str
    agent_id: str
    reason: str

    @property
    def conversation_type(self) -> str:
        return self.conversation.conversation_type

    @property
    def code(self) -> str:
        return self.conversation.code

    @property
    def participants(self):
        return self.conversation.participants

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation.conversation_id,
            "conversation_type": self.conversation.conversation_type,
            "order_id": self.order_id,
            "target_role": self.target_role,
            "agent_id": self.agent_id,
            "reason": self.reason,
            "participants": [p.as_dict() for p in self.conversation.participants],
        }


# Canonical roles are deliberately small. Display labels can be localized later;
# routing and persistence use these values.
ROLE_CUSTOMER = "customer"
ROLE_AGENCY = "agency"
ROLE_HOTEL = "hotel"
ROLE_VEHICLE = "vehicle"
ROLE_TICKET = "ticket"
ROLE_GUIDE = "guide"
ROLE_RESOURCE = "resource"

_ROLE_ALIASES: dict[str, str] = {
    "客户": ROLE_CUSTOMER, "customer": ROLE_CUSTOMER, "游客": ROLE_CUSTOMER,
    "地接社": ROLE_AGENCY, "地接": ROLE_AGENCY, "agency": ROLE_AGENCY,
    "资源方": ROLE_AGENCY, "supplier": ROLE_AGENCY, "资源": ROLE_AGENCY,
    "酒店": ROLE_HOTEL, "hotel": ROLE_HOTEL,
    "车队": ROLE_VEHICLE, "车辆": ROLE_VEHICLE, "vehicle": ROLE_VEHICLE, "car": ROLE_VEHICLE,
    "票务": ROLE_TICKET, "ticket": ROLE_TICKET,
    "导游": ROLE_GUIDE, "guide": ROLE_GUIDE, "司机": ROLE_GUIDE, "driver": ROLE_GUIDE,
    "司导": ROLE_GUIDE, "行中": ROLE_GUIDE,
}

_AGENT_BY_ROLE = {
    ROLE_CUSTOMER: "practice.customer",
    ROLE_AGENCY: "practice.supplier",
    ROLE_HOTEL: "practice.supplier",
    ROLE_VEHICLE: "practice.supplier",
    ROLE_TICKET: "practice.supplier",
    ROLE_GUIDE: "practice.guide",
}

_ROLE_MENTION = re.compile(
    "|".join(sorted((re.escape(x) for x in _ROLE_ALIASES), key=len, reverse=True)),
    re.IGNORECASE,
)


def canonical_role(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _ROLE_ALIASES.get(text, _ROLE_ALIASES.get(text.lower(), text))


def role_from_session(sess: dict | None) -> str:
    if not sess:
        return ""
    kind = canonical_role(str(sess.get("kind") or ""))
    if kind in _AGENT_BY_ROLE:
        return kind
    members = _members(sess)
    if len(members) <= 2:
        for member in members:
            role = canonical_role(member)
            if role in _AGENT_BY_ROLE:
                return role
    return ""


def _members(sess: dict | None) -> list[str]:
    raw = (sess or {}).get("members") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    return [str(x) for x in (raw or []) if str(x).strip()]


def _conversation_type(sess: dict, members: list[str]) -> str:
    code = str(sess.get("code") or "")
    if code == "hub":
        return "hub"
    if code.startswith("dm-"):
        return "dm"
    if code in ("group", "custom"):
        return "group"
    return "group" if len(members) > 2 else "dm"


class ConversationService:
    """Resolve rooms and roles without asking a model to guess."""

    def __init__(self, store) -> None:
        self._store = store

    # ---------- read model ----------

    def get(self, session_id: str, user_id: str = "") -> Conversation:
        sess = self._store.session(session_id)
        if not sess:
            raise ConversationError("未找到会话", status=404)
        owner = str(sess.get("user_id") or "")
        if user_id and owner != user_id:
            raise ConversationError("无权访问该会话", status=403)
        members = _members(sess)
        contacts = {str(c.get("name") or ""): c for c in self._store.contacts_for_user(owner)}
        participants: list[Participant] = [Participant("我", "student", "student")]
        for name in members:
            if name == "我" or name in {p.name for p in participants}:
                continue
            contact = contacts.get(name)
            if not contact:
                # Remarks are display names, so try a display-name match too.
                contact = next((c for c in contacts.values()
                                if (c.get("remark") or c.get("name")) == name), None)
            role = canonical_role((contact or {}).get("kind") or "")
            if not role:
                role = role_from_session(sess) or ROLE_RESOURCE
            participants.append(Participant(
                name=name,
                kind=role,
                agent_id=_AGENT_BY_ROLE.get(role, "practice.supplier"),
                contact_id=str((contact or {}).get("contact_id") or ""),
                order_id=str((contact or {}).get("order_id") or ""),
            ))
        return Conversation(
            conversation_id=session_id,
            user_id=owner,
            name=str(sess.get("name") or "未命名会话"),
            kind=str(sess.get("kind") or ""),
            conversation_type=_conversation_type(sess, members),
            code=str(sess.get("code") or ""),
            order_id=str(sess.get("order_id") or ""),
            participants=tuple(participants),
        )

    def view(self, session_id: str, user_id: str = "") -> dict[str, Any]:
        return self.get(session_id, user_id).as_dict()

    # ---------- deterministic route ----------

    def resolve(self, session_id: str, user_id: str, *,
                order_id: str = "", text: str = "", target_role: str = "",
                allow_latest: bool = False) -> ConversationRoute:
        conv = self.get(session_id, user_id)
        resolved_order = self._resolve_order(conv, user_id, order_id, allow_latest=allow_latest)
        role, reason = self._resolve_role(conv, text, target_role)
        agent = "practice.hub" if conv.conversation_type == "hub" else _AGENT_BY_ROLE.get(role, "")
        if not agent:
            raise ConversationError("无法确定由哪个角色应答，请明确目标角色", status=409)
        return ConversationRoute(conv, resolved_order, role, agent, reason)

    def _resolve_order(self, conv: Conversation, user_id: str, requested: str,
                       *, allow_latest: bool) -> str:
        session_order = conv.order_id
        if session_order:
            self._assert_owner(user_id, session_order)
            if requested and requested != session_order:
                raise ConversationError("该会话属于别的订单，不能跨单发言", status=403)
            return session_order
        if requested:
            self._assert_owner(user_id, requested)
            return requested

        # A DM can carry a contact-level order even on an old database row.
        contact_orders = {p.order_id for p in conv.participants if p.order_id}
        if len(contact_orders) == 1:
            oid = next(iter(contact_orders))
            self._assert_owner(user_id, oid)
            return oid

        active = [o for o in self._store.orders(user_id)
                  if str(o.get("status") or "") != "禁用"]
        unfinished = [o for o in active if int(o.get("stage_index") or 0) < 7]
        candidates = unfinished or active
        if len(candidates) == 1:
            return str(candidates[0].get("order_id") or "")
        if len(candidates) > 1:
            if allow_latest:
                # Compatibility for service-level callers that predate the
                # explicit order selector. API calls must not use this path.
                return str(self._latest(user_id).get("order_id") or "")
            raise ConversationError(
                "这个会话绑定了多个在跟订单，请先明确选择订单再发言", status=409)
        return ""

    def _assert_owner(self, user_id: str, order_id: str) -> None:
        if not order_id:
            return
        row = self._store.order(order_id)
        if not row:
            raise ConversationError("未找到订单", status=404)
        owner = str(row.get("user_id") or "")
        if owner and owner != user_id:
            raise ConversationError("无权访问该订单", status=403)

    def _resolve_role(self, conv: Conversation, text: str, target_role: str) -> tuple[str, str]:
        explicit = canonical_role(target_role)
        if target_role.strip() and not explicit:
            raise ConversationError(f"未知目标角色: {target_role}", status=400)
        if explicit and explicit != "auto":
            if conv.conversation_type == "hub" and explicit == ROLE_CUSTOMER:
                raise ConversationError("客户不在资源对接群，请到客户群或客户单聊沟通", status=400)
            return explicit, "explicit"

        session_role = role_from_session(
            self._store.session(conv.conversation_id) or {})
        if conv.conversation_type == "dm" and session_role:
            return session_role, "session_kind"

        match = _ROLE_MENTION.search(text or "")
        if match:
            role = canonical_role(match.group(0))
            if not (conv.conversation_type == "hub" and role == ROLE_CUSTOMER):
                return role, "message_mention"

        # A resource hub is a dispatcher, not a free-form group. Its default
        # speaker is the agency that owns the package quote; other roles must be
        # named or selected explicitly.
        if conv.conversation_type == "hub":
            return ROLE_AGENCY, "hub_default_agency"

        kinds = [p.kind for p in conv.participants if p.kind in _AGENT_BY_ROLE]
        unique = list(dict.fromkeys(kinds))
        if len(unique) == 1:
            return unique[0], "single_participant"
        return ROLE_AGENCY, "group_default_agency"

    def _latest(self, user_id: str) -> dict:
        rows = [o for o in self._store.orders(user_id)
                if str(o.get("status") or "") != "禁用"]
        if not rows:
            return {}
        active = [o for o in rows if int(o.get("stage_index") or 0) < 7] or rows

        def touched(o: dict) -> str:
            acts = self._store.actions(o["order_id"]) if hasattr(self._store, "actions") else []
            last = max([a.get("at") or "" for a in acts], default="")
            ev = self._store.evidence(o["order_id"]) or []
            last_ev = max([e.get("created_at") or "" for e in ev], default="")
            return max(last, last_ev, o.get("created_at") or "")

        return sorted(active, key=touched, reverse=True)[0]
