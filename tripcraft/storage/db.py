"""SQLite 存储层 —— 线程 / 资产 / 答题 / 订单 / 会话 / 画像。

不引入重框架，用标准库 sqlite3。服务层只通过本模块读写。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "tripcraft.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, username TEXT UNIQUE, display_name TEXT DEFAULT '',
  password_hash TEXT DEFAULT '', password_salt TEXT DEFAULT '', kind TEXT DEFAULT 'real',
  company TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', bio TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT, last_login_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, expires_at TEXT,
  revoked_at TEXT DEFAULT '', last_seen_at TEXT DEFAULT '', ua TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS profile_baseline (
  user_id TEXT, dimension TEXT, value REAL DEFAULT 0, source TEXT DEFAULT '', created_at TEXT,
  PRIMARY KEY (user_id, dimension));
CREATE TABLE IF NOT EXISTS profile_snapshot (
  snapshot_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
  created_at TEXT NOT NULL, radar_json TEXT NOT NULL, report_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_profile_snapshot_user_time
  ON profile_snapshot(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS quiz_question (
  question_id TEXT PRIMARY KEY, user_id TEXT, skill_point_id TEXT,
  payload TEXT, answer TEXT DEFAULT '', reference TEXT DEFAULT '',
  created_at TEXT, answered_at TEXT DEFAULT '', correct INTEGER DEFAULT -1);
CREATE TABLE IF NOT EXISTS profile (
  user_id TEXT PRIMARY KEY, level TEXT DEFAULT 'L1',
  deals INTEGER DEFAULT 0, lost INTEGER DEFAULT 0, complaints INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS ability (
  user_id TEXT, skill_point_id TEXT, teach REAL DEFAULT 0, real_v REAL DEFAULT 0, updated_at TEXT,
  PRIMARY KEY (user_id, skill_point_id));
CREATE TABLE IF NOT EXISTS thread (
  thread_id TEXT PRIMARY KEY, user_id TEXT, skill_point_id TEXT, created_at TEXT, last_active_at TEXT);
CREATE TABLE IF NOT EXISTS thread_message (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, role TEXT, content TEXT, evidence TEXT, created_at TEXT,
  kind TEXT DEFAULT 'text', payload TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS asset (
  asset_id TEXT PRIMARY KEY, user_id TEXT, thread_id TEXT, skill_point_id TEXT,
  type TEXT, title TEXT, content TEXT, evidence TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS quiz_attempt (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, skill_point_id TEXT, question_id TEXT,
  question TEXT, answer TEXT, correct INTEGER, score REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS memory (
  memory_id TEXT PRIMARY KEY, user_id TEXT, type TEXT, content TEXT,
  importance REAL DEFAULT 0.6, source_thread TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS biz_order (
  order_id TEXT PRIMARY KEY, user_id TEXT, customer TEXT, destination TEXT,
  status TEXT, stage_index INTEGER DEFAULT 0, payload TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS im_session (
  session_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, kind TEXT, members TEXT, created_at TEXT,
  order_id TEXT DEFAULT '', code TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS contact (
  contact_id TEXT PRIMARY KEY, order_id TEXT, user_id TEXT, name TEXT, kind TEXT,
  phone TEXT DEFAULT '', source TEXT DEFAULT '', note TEXT DEFAULT '',
  added_at TEXT DEFAULT '', session_id TEXT DEFAULT '', remark TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS supplier_quote (
  order_id TEXT, kind TEXT, payload TEXT, updated_at TEXT,
  PRIMARY KEY (order_id, kind));
CREATE TABLE IF NOT EXISTS im_message (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, sender TEXT, role TEXT, content TEXT,
  created_at TEXT, kind TEXT DEFAULT 'text', payload TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS order_contact (
  contact_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, kind TEXT, at TEXT,
  status TEXT, has_record INTEGER DEFAULT 0, detail TEXT);
CREATE TABLE IF NOT EXISTS notice (
  notice_id TEXT PRIMARY KEY, user_id TEXT, group_key TEXT, title TEXT, body TEXT,
  at TEXT, starred INTEGER DEFAULT 0, order_id TEXT);
CREATE TABLE IF NOT EXISTS finance_entry (
  entry_id TEXT PRIMARY KEY, order_id TEXT, code TEXT, label TEXT, category TEXT,
  amount REAL DEFAULT 0, bearer TEXT DEFAULT '\u5f85\u5b9a', ours REAL DEFAULT 0,
  supplier_kind TEXT DEFAULT '', source TEXT DEFAULT '', ref TEXT DEFAULT '',
  note TEXT DEFAULT '', status TEXT DEFAULT '\u5f85\u5904\u7406', at TEXT);
CREATE TABLE IF NOT EXISTS doc_template (
  template_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, kind TEXT DEFAULT 'plan',
  sections TEXT DEFAULT '[]', updated_at TEXT);
CREATE TABLE IF NOT EXISTS plan_version (
  plan_id TEXT PRIMARY KEY, order_id TEXT, user_id TEXT, version INTEGER DEFAULT 1,
  title TEXT DEFAULT '', days TEXT DEFAULT '', quote TEXT DEFAULT '', note TEXT DEFAULT '',
  status TEXT DEFAULT '草稿', channels TEXT DEFAULT '', created_at TEXT, sent_at TEXT,
  read_at TEXT, read_due_at TEXT, feedback TEXT DEFAULT '', confirm_at TEXT,
  values_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS order_settlement (
  order_id TEXT PRIMARY KEY, revenue REAL DEFAULT 0, cost REAL DEFAULT 0,
  loss REAL DEFAULT 0, profit REAL DEFAULT 0, margin REAL DEFAULT 0,
  grade TEXT DEFAULT '', detail TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS supplier_state (
  user_id TEXT, kind TEXT, order_id TEXT DEFAULT '', payload TEXT, updated_at TEXT,
  PRIMARY KEY (user_id, kind, order_id));
CREATE TABLE IF NOT EXISTS order_evidence (
  evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, kind TEXT, step TEXT,
  ref TEXT, text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS order_score (
  order_id TEXT, skill_point_id TEXT, score REAL, level TEXT,
  hit_negative INTEGER DEFAULT 0, evidence TEXT, comment TEXT, source TEXT, created_at TEXT,
  confidence REAL DEFAULT 0, status TEXT DEFAULT '\u5df2\u5165\u5e93', review_reason TEXT DEFAULT '',
  PRIMARY KEY (order_id, skill_point_id));
CREATE TABLE IF NOT EXISTS call_session (
  session_id TEXT PRIMARY KEY, order_id TEXT, user_id TEXT, customer TEXT,
  destination TEXT, mode TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS call_line (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, who TEXT, text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS order_target (
  order_id TEXT, skill_point_id TEXT, checkpoint TEXT, step TEXT,
  trigger_state TEXT DEFAULT 'pending', covered INTEGER DEFAULT 0,
  reason TEXT DEFAULT '', updated_at TEXT,
  PRIMARY KEY (order_id, skill_point_id));
CREATE TABLE IF NOT EXISTS director_event (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, type TEXT, payload TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS deliverable_doc (
  order_id TEXT, deliverable_id TEXT, version INTEGER DEFAULT 1,
  values_json TEXT, rendered TEXT, audience TEXT, guard_json TEXT,
  file_ids TEXT, at TEXT, PRIMARY KEY (order_id, deliverable_id));
CREATE TABLE IF NOT EXISTS deliverable_draft (
  order_id TEXT NOT NULL, deliverable_id TEXT NOT NULL, values_json TEXT NOT NULL,
  updated_at TEXT NOT NULL, validation_json TEXT DEFAULT '', PRIMARY KEY (order_id, deliverable_id));
CREATE TABLE IF NOT EXISTS deliverable_file (
  file_id TEXT PRIMARY KEY, order_id TEXT, deliverable_id TEXT,
  filename TEXT, mime TEXT, size INTEGER, data BLOB, at TEXT);
CREATE TABLE IF NOT EXISTS order_action (
  action_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, action TEXT,
  payload TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS calibration_run (
  run_id TEXT PRIMARY KEY, samples INTEGER, predictions INTEGER, agreement REAL,
  evidence_accuracy REAL, stability REAL, threshold_conf REAL, threshold_delta REAL,
  passed INTEGER, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS incident (
  incident_id TEXT PRIMARY KEY, order_id TEXT, code TEXT, step TEXT, title TEXT,
  channel TEXT, session_id TEXT, speaker TEXT, body TEXT, skill_points TEXT,
  rule TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS order_customer (
  order_id TEXT PRIMARY KEY, card_json TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customer_fact_event (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, fact_key TEXT NOT NULL,
  value TEXT, state TEXT, kind TEXT NOT NULL, expected TEXT, source_channel TEXT, source_ref TEXT, at TEXT,
  UNIQUE(order_id, fact_key, kind, source_channel, source_ref, value));
CREATE INDEX IF NOT EXISTS idx_customer_fact_order ON customer_fact_event(order_id, event_id);
CREATE TABLE IF NOT EXISTS customer_feedback_turn (
  turn_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, channel TEXT, session_id TEXT,
  speaker TEXT, text TEXT, source_ref TEXT UNIQUE, at TEXT);
CREATE TABLE IF NOT EXISTS source_snapshot (
  snapshot_id TEXT PRIMARY KEY, url TEXT NOT NULL, canonical_url TEXT DEFAULT '',
  host TEXT NOT NULL, title TEXT DEFAULT '', content TEXT NOT NULL, content_hash TEXT NOT NULL,
  content_type TEXT DEFAULT '', raw_size INTEGER DEFAULT 0, created_by TEXT DEFAULT '',
  fetched_at TEXT NOT NULL, fetch_method TEXT DEFAULT 'server_http',
  status TEXT DEFAULT 'verified');
CREATE INDEX IF NOT EXISTS idx_source_snapshot_host_time
  ON source_snapshot(host, fetched_at DESC);
CREATE VIEW IF NOT EXISTS conversation_turn AS
  SELECT s.order_id, s.mode AS channel, s.session_id,
         CASE WHEN l.who='agent' THEN 'customer' ELSE 'consultant' END AS speaker,
         l.text, 'call:' || printf('%020d', l.msg_id) AS source_ref, replace(l.created_at, ' ', 'T') AS at
    FROM call_line l JOIN call_session s ON s.session_id=l.session_id
  UNION ALL
  SELECT s.order_id, 'im', s.session_id,
         CASE WHEN m.role='me' THEN 'consultant' ELSE 'customer' END,
         m.content, 'im:' || printf('%020d', m.msg_id), replace(m.created_at, ' ', 'T')
    FROM im_message m JOIN im_session s ON s.session_id=m.session_id
    WHERE s.kind='客户' AND m.kind='text' AND m.role IN ('me','other')
  UNION ALL
  SELECT order_id, channel, session_id, speaker, text, source_ref, replace(at, ' ', 'T')
    FROM customer_feedback_turn;
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        # 允许用 TRIPCRAFT_DB 指定库文件：测试用临时库，不碰演示库
        self.path = str(path or os.environ.get("TRIPCRAFT_DB") or DEFAULT_DB)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._migrate_ability_sources()
        self._migrate_supplier_state()
        self._conn.commit()
        # 旧订单只保留既有明确值；不把缺失信息补成未经客户说过的事实。
        for row in self._all("SELECT * FROM biz_order"):
            self.ensure_customer_card(row["order_id"], row=row, fill_hidden=False)

    # 轻量迁移：老库缺列时补齐（不引入迁移框架）
    _MIGRATIONS: dict[str, dict[str, str]] = {
        "deliverable_draft": {"validation_json": "TEXT DEFAULT ''"},
        "ability": {
            "teach_source": "TEXT DEFAULT ''", "real_source": "TEXT DEFAULT ''",
            "teach_updated_at": "TEXT DEFAULT ''", "real_updated_at": "TEXT DEFAULT ''",
        },
        "im_session": {"order_id": "TEXT DEFAULT ''", "code": "TEXT DEFAULT ''"},
        "im_message": {"kind": "TEXT DEFAULT 'text'", "payload": "TEXT DEFAULT ''"},
        # 教学线程：题目卡与判分结果要跟着聊天记录一起存（kind=quiz / quiz_result）
        "thread_message": {"kind": "TEXT DEFAULT 'text'", "payload": "TEXT DEFAULT ''"},
        "contact": {"remark": "TEXT DEFAULT ''", "session_id": "TEXT DEFAULT ''"},
        "order_score": {
            "confidence": "REAL DEFAULT 0",
            "status": "TEXT DEFAULT '\u5df2\u5165\u5e93'",
            "review_reason": "TEXT DEFAULT ''",
        },
    }

    def _migrate(self) -> None:
        for table, cols in self._MIGRATIONS.items():
            have = {r["name"] for r in self._all(f"PRAGMA table_info({table})")}
            if not have:
                continue
            for name, ddl in cols.items():
                if name not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _migrate_supplier_state(self) -> None:
        """supplier_state 升级为「全局默认 + 按订单覆盖」：主键要加 order_id，只能重建表。"""
        have = {r["name"] for r in self._all("PRAGMA table_info(supplier_state)")}
        if not have or "order_id" in have:
            return
        with self._lock:
            self._conn.execute("ALTER TABLE supplier_state RENAME TO supplier_state_legacy")
            self._conn.execute(
                "CREATE TABLE supplier_state ("
                "user_id TEXT, kind TEXT, order_id TEXT DEFAULT '', payload TEXT, updated_at TEXT, "
                "PRIMARY KEY (user_id, kind, order_id))")
            self._conn.execute(
                "INSERT INTO supplier_state(user_id, kind, order_id, payload, updated_at) "
                "SELECT user_id, kind, '', payload, updated_at FROM supplier_state_legacy")
            self._conn.execute("DROP TABLE supplier_state_legacy")
            self._conn.commit()

    def _migrate_ability_sources(self) -> None:
        """旧能力值按已有证据标注来源；初始测评不会被标成学习训练。"""
        self._conn.execute("""UPDATE ability SET teach_source='learning',
            teach_updated_at=COALESCE((SELECT MAX(q.created_at) FROM quiz_attempt q
                WHERE q.user_id=ability.user_id AND q.skill_point_id=ability.skill_point_id), updated_at)
            WHERE teach_source='' AND EXISTS (SELECT 1 FROM quiz_attempt q
                WHERE q.user_id=ability.user_id AND q.skill_point_id=ability.skill_point_id)""")
        self._conn.execute("""UPDATE ability SET teach_source='initial', teach_updated_at=updated_at
            WHERE teach_source='' AND EXISTS (SELECT 1 FROM profile_baseline b
                WHERE b.user_id=ability.user_id AND b.dimension=substr(ability.skill_point_id,1,2))""")
        self._conn.execute("""UPDATE ability SET real_source='practice', real_updated_at=updated_at
            WHERE real_source='' AND real_v>0""")

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    def close(self) -> None:
        self._conn.close()

    # 画像
    def ensure_profile(self, user_id: str) -> dict:
        self._exec("INSERT OR IGNORE INTO profile(user_id, updated_at) VALUES(?,?)", (user_id, now()))
        return self._one("SELECT * FROM profile WHERE user_id=?", (user_id,))  # type: ignore

    def get_profile(self, user_id: str) -> dict | None:
        return self._one("SELECT * FROM profile WHERE user_id=?", (user_id,))

    def set_ability(self, user_id: str, sp: str, teach: float | None = None,
                    real_v: float | None = None, *, source: str = "") -> None:
        self.ensure_profile(user_id)
        row = self._one("SELECT * FROM ability WHERE user_id=? AND skill_point_id=?", (user_id, sp))
        t = row["teach"] if (row and teach is None) else (teach if teach is not None else 0)
        r = row["real_v"] if (row and real_v is None) else (real_v if real_v is not None else 0)
        ts = now()
        teach_source = (source or "learning") if teach is not None else (row or {}).get("teach_source", "")
        real_source = (source or "practice") if real_v is not None else (row or {}).get("real_source", "")
        teach_at = ts if teach is not None else (row or {}).get("teach_updated_at", "")
        real_at = ts if real_v is not None else (row or {}).get("real_updated_at", "")
        if row:
            self._exec("UPDATE ability SET teach=?, real_v=?, updated_at=?, teach_source=?, real_source=?, "
                       "teach_updated_at=?, real_updated_at=? WHERE user_id=? AND skill_point_id=?",
                       (t, r, ts, teach_source, real_source, teach_at, real_at, user_id, sp))
        else:
            self._exec("INSERT INTO ability(user_id, skill_point_id, teach, real_v, updated_at, "
                       "teach_source, real_source, teach_updated_at, real_updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (user_id, sp, t, r, ts, teach_source, real_source, teach_at, real_at))

    def abilities(self, user_id: str) -> dict[str, dict]:
        return {r["skill_point_id"]: r for r in self._all("SELECT * FROM ability WHERE user_id=?", (user_id,))}

    def has_profile_data(self, user_id: str) -> bool:
        """是否已有能力或训练记录；初始测评是否完成由 has_initial_assessment 单独判断。

        有非零掌握度 / 做过题 / 有实战评分，任一条成立即视为已建档。
        做题和实战记录不代表做过初始测评。
        """
        row = self._one("SELECT COUNT(*) AS n FROM ability WHERE user_id=? AND (teach > 0 OR real_v > 0)",
                        (user_id,))
        if row and int(row["n"] or 0) > 0:
            return True
        row = self._one("SELECT COUNT(*) AS n FROM quiz_attempt WHERE user_id=?", (user_id,))
        if row and int(row["n"] or 0) > 0:
            return True
        row = self._one("""SELECT COUNT(*) AS n FROM order_score os
            JOIN biz_order o ON o.order_id = os.order_id WHERE o.user_id=?""", (user_id,))
        return bool(row and int(row["n"] or 0) > 0)

    def has_initial_assessment(self, user_id: str) -> bool:
        """初始测评以持久化基线或初始报告为准，不被做题、实战评分挡住。"""
        if self._one("SELECT 1 FROM profile_baseline WHERE user_id=? LIMIT 1", (user_id,)):
            return True
        # 兼容只有初始报告、尚未写基线表的旧账号；动态刷新报告不算初始测评。
        for row in self._all("SELECT source_thread, content FROM memory "
                             "WHERE user_id=? AND type='profile_report'", (user_id,)):
            if row.get("source_thread") == "profile:assessment":
                return True
            try:
                report = json.loads(row.get("content") or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(report, dict) and report.get("kind") == "initial":
                return True
        return False

    # ---------------- 身份与会话（owner: identity 域） ----------------
    # users/sessions 是认证的唯一持久层：只存口令的加盐哈希与 token 的 sha256 摘要。
    # 其他域只允许读 user_by_id / user_by_name，写操作一律走 identity 的 AuthService。

    def create_user(self, user_id: str, username: str, password_hash: str, password_salt: str,
                    display_name: str = "", kind: str = "real") -> dict:
        ts = now()
        self._exec("INSERT INTO users(user_id, username, display_name, password_hash, password_salt,"
                   " kind, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (user_id, username, display_name or username, password_hash, password_salt, kind, ts, ts))
        return self.user_by_id(user_id) or {}  # type: ignore[return-value]

    def user_by_id(self, user_id: str) -> dict | None:
        return self._one("SELECT * FROM users WHERE user_id=?", (user_id,))

    def user_by_name(self, username: str) -> dict | None:
        return self._one("SELECT * FROM users WHERE username=?", (username,))

    def set_user_password(self, user_id: str, password_hash: str, password_salt: str) -> None:
        self._exec("UPDATE users SET password_hash=?, password_salt=?, updated_at=? WHERE user_id=?",
                   (password_hash, password_salt, now(), user_id))

    def update_user_profile(self, user_id: str, fields: dict) -> dict | None:
        """只允许改公开个人资料字段；口令列永远不经此入口。"""
        allowed = ("display_name", "company", "phone", "email", "bio")
        sets: list[str] = []
        args: list = []
        for key in allowed:
            if key in fields and fields[key] is not None:
                sets.append(f"{key}=?")
                args.append(str(fields[key]))
        if sets:
            sets.append("updated_at=?")
            args.append(now())
            args.append(user_id)
            self._exec(f"UPDATE users SET {', '.join(sets)} WHERE user_id=?", tuple(args))
        return self.user_by_id(user_id)

    def touch_login(self, user_id: str) -> None:
        ts = now()
        self._exec("UPDATE users SET last_login_at=?, updated_at=? WHERE user_id=?",
                   (ts, ts, user_id))

    def create_session(self, token_hash: str, user_id: str, expires_at: str, ua: str = "") -> None:
        ts = now()
        self._exec("INSERT OR REPLACE INTO sessions(token_hash, user_id, created_at, expires_at,"
                   " revoked_at, last_seen_at, ua) VALUES(?,?,?,?,?,?,?)",
                   (token_hash, user_id, ts, expires_at, "", ts, ua))

    def session_by_hash(self, token_hash: str) -> dict | None:
        return self._one("SELECT * FROM sessions WHERE token_hash=?", (token_hash,))

    def touch_session(self, token_hash: str) -> None:
        self._exec("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now(), token_hash))

    def revoke_session(self, token_hash: str) -> None:
        self._exec("UPDATE sessions SET revoked_at=? WHERE token_hash=?", (now(), token_hash))

    def purge_expired_sessions(self, before: str = "") -> int:
        """清理已过期或已登出的会话，返回删除行数。"""
        cur = self._exec("DELETE FROM sessions WHERE expires_at < ? OR revoked_at != ''",
                         (before or now(),))
        return int(cur.rowcount or 0)

    # 画像初始基线（R12）：初始测评的快照，唯一不被后续评分覆盖的口径来源。
    def save_baseline(self, user_id: str, dimension: str, value: float,
                      source: str = "intake") -> None:
        self._exec("INSERT OR REPLACE INTO profile_baseline(user_id, dimension, value, source, created_at)"
                   " VALUES(?,?,?,?,?)", (user_id, dimension, float(value), source, now()))

    def baseline(self, user_id: str) -> dict[str, dict]:
        return {r["dimension"]: r for r in
                self._all("SELECT * FROM profile_baseline WHERE user_id=?", (user_id,))}

    def initial_profile_report(self, user_id: str) -> dict:
        """兼容尚无快照表的旧初始报告，只取本人实际保存的初始测评。"""
        rows = self._all("SELECT content, created_at FROM memory WHERE user_id=? "
                         "AND type='profile_report' ORDER BY created_at, rowid", (user_id,))
        for row in rows:
            try:
                report = json.loads(row.get("content") or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(report, dict) and report.get("kind") == "initial":
                report["created_at"] = report.get("created_at") or row.get("created_at") or ""
                return report
        return {}

    def save_profile_snapshot(self, user_id: str, kind: str, radar: dict, report: dict) -> dict:
        """报告与雷达历史原子保存；历史 JSON 不随后续能力变动而重算。"""
        snapshot_id = "ps_" + uuid.uuid4().hex
        ts = now()
        meta = {"id": snapshot_id, "kind": kind, "at": ts}
        radar = {**radar, "snapshot_id": snapshot_id, "at": ts}
        report = {**report, "created_at": ts}
        radar_json = json.dumps(radar, ensure_ascii=False)
        report_json = json.dumps(report, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO profile_snapshot "
                               "(snapshot_id,user_id,kind,created_at,radar_json,report_json) VALUES(?,?,?,?,?,?)",
                               (snapshot_id, user_id, kind, ts, radar_json, report_json))
            self._conn.execute("INSERT INTO memory "
                               "(memory_id,user_id,type,content,importance,source_thread,created_at) VALUES(?,?,?,?,?,?,?)",
                               ("mem_" + uuid.uuid4().hex, user_id, "profile_report", report_json,
                                0.8 if kind == "initial" else 0.7,
                                "profile:assessment" if kind == "initial" else "profile:refresh", ts))
        return {"snapshot": meta, "radar": radar, "report": report}

    def profile_snapshots(self, user_id: str) -> list[dict]:
        return self._all("SELECT snapshot_id AS id, kind, created_at AS at FROM profile_snapshot "
                         "WHERE user_id=? ORDER BY created_at DESC, rowid DESC", (user_id,))

    def profile_snapshot(self, user_id: str, snapshot_id: str) -> dict | None:
        row = self._one("SELECT snapshot_id AS id, kind, created_at AS at, radar_json, report_json "
                        "FROM profile_snapshot WHERE user_id=? AND snapshot_id=?", (user_id, snapshot_id))
        if not row:
            return None
        return {"id": row["id"], "kind": row["kind"], "at": row["at"],
                "radar": json.loads(row["radar_json"]), "report": json.loads(row["report_json"])}

    # ---------------- 题目与答案只存服务端（P0：判分不得信客户端） ----------------
    # `pick_question` 出题后把**完整题卡（含答案/参考/讲解）**按 question_id 落这张表，
    # 下发给前端的题卡一律经过剥离；`submit_answer` 只按 question_id 取回服务端题库再判分，
    # 客户端传来的 stem/answer/reference/explain 不参与判分。

    def save_quiz_question(self, question_id: str, user_id: str, sp: str, payload: dict,
                           answer: str = "", reference: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO quiz_question(question_id, user_id, skill_point_id,"
                   " payload, answer, reference, created_at, answered_at, correct)"
                   " VALUES(?,?,?,?,?,?,?,'',-1)",
                   (question_id, user_id, sp, json.dumps(payload, ensure_ascii=False),
                    str(answer or ""), str(reference or ""), now()))

    def quiz_question(self, question_id: str) -> dict | None:
        """按 question_id 精确取回服务端题目存档（含 user/sp 归属，用于越权判定）。"""
        return self._one("SELECT * FROM quiz_question WHERE question_id=?", (question_id,))

    def mark_quiz_answered(self, question_id: str, correct: bool) -> None:
        self._exec("UPDATE quiz_question SET answered_at=?, correct=? WHERE question_id=?",
                   (now(), 1 if correct else 0, question_id))

    def claim_quiz_question(self, question_id: str) -> bool:
        """**原子**地把题目标记为已作答，返回 True 表示本次抢占成功（之前未作答过）。

        用单条带 WHERE 条件的 UPDATE 做并发闸门：同一 question_id 被重复/并发提交时只有一次能抢占成功，
        其余一律拒绝，因此不会重复判分、重复加分。抢占失败时不得再写 attempts / ability / memory。
        """
        cur = self._exec(
            "UPDATE quiz_question SET answered_at=? "
            "WHERE question_id=? AND (answered_at IS NULL OR answered_at='')",
            (now(), question_id))
        return bool(cur.rowcount)

    def release_quiz_claim(self, question_id: str) -> None:
        """判分过程异常时回滚抢占，避免题目被卡成「已作答但没判分」。"""
        self._exec("UPDATE quiz_question SET answered_at='' WHERE question_id=? AND correct=-1",
                   (question_id,))

    def latest_memory(self, user_id: str, type_: str) -> dict | None:
        return self._one("""SELECT * FROM memory WHERE user_id=? AND type=?
            ORDER BY created_at DESC, rowid DESC LIMIT 1""", (user_id, type_))

    # 线程
    def get_or_create_thread(self, user_id: str, sp: str) -> dict:
        """按 **用户 + 技能点** 取/建唯一线程。

        线程 ID 必须带 user_id。历史实现用的是 `thread:<技能点ID>`（**全局一条**），
        导致所有账号共用同一线程：新注册账号在 /learn/thread/C6.1 能看到别人的旧对话与已答题记录
        （已发生的跨账号串数据缺陷）。本方法同时是线程历史、题卡、个性化资产的唯一入口，
        因此改这一处即可让三者的读写都按用户隔离。

        旧格式 `thread:<技能点ID>` 的行**保留不动**（不删除、不改归属）：
        其中的历史消息无法按用户归属，把它归属给任何账号都是错误归属；
        因此它不再作为读写目标，新账号一律得到属于自己的空线程。
        """
        tid = f"thread:{user_id}:{sp}"
        self._exec("INSERT OR IGNORE INTO thread(thread_id, user_id, skill_point_id, created_at, last_active_at) VALUES(?,?,?,?,?)",
                   (tid, user_id, sp, now(), now()))
        return self._one("SELECT * FROM thread WHERE thread_id=?", (tid,))  # type: ignore

    def touch_thread(self, tid: str) -> None:
        self._exec("UPDATE thread SET last_active_at=? WHERE thread_id=?", (now(), tid))

    def add_message(self, tid: str, role: str, content: str, evidence: list | None = None,
                    kind: str = "text", payload: str = "") -> int:
        """kind/payload 用来存结构化消息（教学线程里的题目卡与判分结果）。"""
        cur = self._exec(
            "INSERT INTO thread_message(thread_id, role, content, evidence, created_at, kind, payload) "
            "VALUES(?,?,?,?,?,?,?)",
            (tid, role, content, json.dumps(evidence or [], ensure_ascii=False), now(), kind, payload or ""))
        return int(cur.lastrowid)

    def messages(self, tid: str, limit: int = 60) -> list[dict]:
        rows = self._all("SELECT * FROM thread_message WHERE thread_id=? ORDER BY msg_id DESC LIMIT ?", (tid, limit))
        return list(reversed(rows))

    # 资产
    def add_asset(self, asset_id: str, user_id: str, tid: str, sp: str, type_: str,
                  title: str, content: str, evidence: list | None = None) -> None:
        self._exec("INSERT OR REPLACE INTO asset(asset_id, user_id, thread_id, skill_point_id, type, title, content, evidence, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (asset_id, user_id, tid, sp, type_, title, content, json.dumps(evidence or [], ensure_ascii=False), now()))

    def assets(self, user_id: str, sp: str | None = None) -> list[dict]:
        if sp:
            return self._all("SELECT * FROM asset WHERE user_id=? AND skill_point_id=? ORDER BY created_at DESC", (user_id, sp))
        return self._all("SELECT * FROM asset WHERE user_id=? ORDER BY created_at DESC", (user_id,))

    def asset(self, asset_id: str) -> dict | None:
        return self._one("SELECT * FROM asset WHERE asset_id=?", (asset_id,))

    # 答题
    def add_attempt(self, user_id: str, sp: str, qid: str, question: dict, answer: str, correct: bool, score: float) -> int:
        cur = self._exec("INSERT INTO quiz_attempt(user_id, skill_point_id, question_id, question, answer, correct, score, created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (user_id, sp, qid, json.dumps(question, ensure_ascii=False), answer, 1 if correct else 0, score, now()))
        return int(cur.lastrowid)

    def attempts(self, user_id: str, sp: str) -> list[dict]:
        return self._all("SELECT * FROM quiz_attempt WHERE user_id=? AND skill_point_id=? ORDER BY attempt_id", (user_id, sp))

    def all_attempts(self, user_id: str) -> list[dict]:
        return self._all("SELECT * FROM quiz_attempt WHERE user_id=? ORDER BY created_at", (user_id,))

    def order_scores_all(self, user_id: str) -> list[dict]:
        return self._all("""SELECT os.* FROM order_score os JOIN biz_order o ON o.order_id=os.order_id
            WHERE o.user_id=? ORDER BY os.created_at""", (user_id,))

    # 记忆
    def add_memory(self, user_id: str, type_: str, content: str, source_thread: str = "", importance: float = 0.6) -> None:
        self._exec("INSERT INTO memory(memory_id, user_id, type, content, importance, source_thread, created_at) VALUES(?,?,?,?,?,?,?)",
                   (f"mem_{int(datetime.now().timestamp()*1000)}", user_id, type_, content, importance, source_thread, now()))

    def memories(self, user_id: str, limit: int = 20) -> list[dict]:
        return self._all("SELECT * FROM memory WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))

    # 订单
    def upsert_order(self, order_id: str, user_id: str, customer: str, destination: str,
                     status: str, stage_index: int, payload: dict | None = None) -> None:
        old = self._one("SELECT * FROM biz_order WHERE order_id=?", (order_id,))
        try:
            old_payload = json.loads((old or {}).get("payload") or "{}")
        except (TypeError, ValueError):
            old_payload = {}
        if not isinstance(old_payload, dict):
            old_payload = {}
        new_payload = payload or {}

        # order_customer 是订单身份的事实快照，不是状态缓存。只更新阶段/状态时保留它；
        # 一旦客户、目的地或身份字段被改写，旧卡必须失效，否则跨场景复用固定订单号时
        # 会把上一位客人的年龄、性格、隐藏诉求带到新订单里。
        identity_changed = bool(old) and (
            (old.get("user_id") or "") != user_id
            or (old.get("customer") or "") != customer
            or (old.get("destination") or "") != destination
            or any(
                key in new_payload and new_payload.get(key) != old_payload.get(key)
                for key in ("source_market", "language", "age", "gender", "documents")
            )
        )
        if identity_changed:
            self._exec("DELETE FROM order_customer WHERE order_id=?", (order_id,))

        self._exec("INSERT OR REPLACE INTO biz_order(order_id, user_id, customer, destination, status, stage_index, payload, created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (order_id, user_id, customer, destination, status, stage_index, json.dumps(new_payload, ensure_ascii=False), now()))
        self.ensure_customer_card(order_id, fill_hidden=bool(new_payload.get("generated")))

    def orders(self, user_id: str | None = None) -> list[dict]:
        if user_id:
            rows = self._all("SELECT * FROM biz_order WHERE user_id=? ORDER BY created_at DESC", (user_id,))
        else:
            rows = self._all("SELECT * FROM biz_order ORDER BY created_at DESC")
        cards = {r["order_id"]: json.loads(r["card_json"]) for r in self._all("SELECT order_id,card_json FROM order_customer")}
        for row in rows:
            row["_customer_card"] = cards.get(row["order_id"])
        return rows

    def order(self, order_id: str) -> dict | None:
        row = self._one("SELECT * FROM biz_order WHERE order_id=?", (order_id,))
        if row:
            row["_customer_card"] = self.ensure_customer_card(order_id, row=row)
        return row

    def ensure_customer_card(self, order_id: str, *, row: dict | None = None,
                             fill_hidden: bool | None = None) -> dict:
        from ..services.customer_card import build_card, load_payload
        saved = self._one("SELECT card_json FROM order_customer WHERE order_id=?", (order_id,))
        if saved:
            return json.loads(saved["card_json"])
        row = row or self._one("SELECT * FROM biz_order WHERE order_id=?", (order_id,))
        if not row:
            raise ValueError(f"未找到订单: {order_id}")
        if fill_hidden is None:
            fill_hidden = bool(load_payload(row).get("generated"))
        card = build_card(row, fill_hidden=fill_hidden)
        self._exec("INSERT OR IGNORE INTO order_customer(order_id,card_json,version,updated_at) VALUES(?,?,?,?)",
                   (order_id, json.dumps(card, ensure_ascii=False), card["version"], now()))
        for issue in card.get("issues", []):
            self.record_customer_conflict(order_id, issue, "migration", "initial-card")
        return json.loads(self._one("SELECT card_json FROM order_customer WHERE order_id=?", (order_id,))["card_json"])

    def observe_customer_facts(self, order_id: str, observations: dict, channel: str, source_ref: str,
                               *, confirmed: bool = False) -> dict:
        from ..services.customer_card import reconcile
        self.ensure_customer_card(order_id)
        with self._lock:
            row = self._conn.execute("SELECT card_json FROM order_customer WHERE order_id=?", (order_id,)).fetchone()
            card, events = reconcile(json.loads(row["card_json"]), observations, confirmed=confirmed)
            if channel == "template_import":
                for event in events:
                    if event["kind"] == "confirmed":
                        event["kind"] = "simulated"
                        card["fields"][event["fact_key"]]["origin"] = "template_simulation"
            try:
                for event in events:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO customer_fact_event(order_id,fact_key,value,state,kind,expected,source_channel,source_ref,at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (order_id, event["fact_key"], event["value"], event["state"], event["kind"],
                         event.get("expected", ""), channel, source_ref, now()))
                self._conn.execute("UPDATE order_customer SET card_json=?,version=?,updated_at=? WHERE order_id=?",
                                   (json.dumps(card, ensure_ascii=False), card["version"], now(), order_id))
                if any(event["kind"] in ("released", "confirmed", "simulated") for event in events):
                    legacy = self._conn.execute("SELECT payload FROM biz_order WHERE order_id=?", (order_id,)).fetchone()
                    payload = json.loads(legacy["payload"] or "{}")
                    for event in events:
                        if event["kind"] in ("released", "confirmed", "simulated") and not payload.get(event["fact_key"]):
                            payload[event["fact_key"]] = event["value"]
                    self._conn.execute("UPDATE biz_order SET payload=? WHERE order_id=?",
                                       (json.dumps(payload, ensure_ascii=False), order_id))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return card

    def customer_fact_events(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM customer_fact_event WHERE order_id=? ORDER BY event_id", (order_id,))

    def complete_template_identity(self, order_id: str, identity: dict) -> dict:
        """只补齐缺失的客户身份/目的地，订单展示和角色共用同一份模拟补充。"""
        self.ensure_customer_card(order_id)
        unknown = {"", "待定", "未定", "未确定", "未知", "未明确", "待推荐", "未选择", "未提供"}
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM order_customer WHERE order_id=?", (order_id,)).fetchone()
            card = json.loads(row["card_json"])
            order = dict(self._conn.execute("SELECT * FROM biz_order WHERE order_id=?", (order_id,)).fetchone())
            payload = json.loads(order.get("payload") or "{}")
            changed = False
            for key in ("customer", "destination", "source_market", "language", "age", "gender"):
                value = str(identity.get(key) or "").strip()
                if str(card["identity"].get(key) or "").strip() in unknown and value:
                    card["identity"][key] = value
                    changed = True
                # 旧卡里已有稳定默认身份时同步到订单，表头、公开资料和通话保持同源。
                if key not in ("customer", "destination") and str(payload.get(key) or "").strip() in unknown:
                    payload[key] = card["identity"].get(key) or value
                    changed = True
            if changed:
                card["version"] += 1
                self._conn.execute("UPDATE order_customer SET card_json=?,version=?,updated_at=? WHERE order_id=?",
                                   (json.dumps(card, ensure_ascii=False), card["version"], now(), order_id))
                self._conn.execute("UPDATE biz_order SET customer=?,destination=?,payload=? WHERE order_id=?",
                                   (card["identity"]["customer"], card["identity"]["destination"],
                                    json.dumps(payload, ensure_ascii=False), order_id))
        return card

    def record_customer_conflict(self, order_id: str, issue: dict, channel: str, source_ref: str) -> None:
        self._exec("INSERT OR IGNORE INTO customer_fact_event(order_id,fact_key,value,state,kind,expected,source_channel,source_ref,at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (order_id, issue.get("key", "reply"), str(issue.get("value") or issue.get("reason") or ""),
                    issue.get("reason", ""), "conflict", str(issue.get("expected") or ""), channel, source_ref, now()))

    def conversation_turns(self, order_id: str, limit: int = 10, exclude_session: str = "") -> list[dict]:
        return list(reversed(self._all(
            "SELECT * FROM conversation_turn WHERE order_id=? AND (?='' OR session_id<>?) ORDER BY at DESC, source_ref DESC LIMIT ?",
            (order_id, exclude_session, exclude_session, max(1, min(limit, 100))))))

    def recent_im_cards(self, order_id: str, limit: int = 5) -> list[dict]:
        """客户在 IM 里收到的交付物卡片（按时间正序），供客户 Agent 读取正文摘要。"""
        rows = self._all(
            "SELECT m.msg_id, m.sender, m.content, m.payload, m.created_at "
            "FROM im_message m JOIN im_session s ON s.session_id=m.session_id "
            "WHERE s.order_id=? AND s.kind='客户' AND m.kind='card' "
            "ORDER BY m.msg_id DESC LIMIT ?",
            (order_id, max(1, min(limit, 20))))
        return list(reversed(rows))

    def add_customer_turn(self, order_id: str, channel: str, speaker: str, text: str, source_ref: str) -> None:
        self._exec("INSERT OR IGNORE INTO customer_feedback_turn(order_id,channel,session_id,speaker,text,source_ref,at) VALUES(?,?,?,?,?,?,?)",
                   (order_id, channel, "", speaker, text, source_ref, now()))

    def set_stage(self, order_id: str, stage_index: int) -> None:
        self._exec("UPDATE biz_order SET stage_index=? WHERE order_id=?", (stage_index, order_id))

    # IM
    def upsert_session(self, session_id: str, user_id: str, name: str, kind: str, members: list,
                       order_id: str = "", code: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO im_session(session_id, user_id, name, kind, members,"
                   " created_at, order_id, code) VALUES(?,?,?,?,?,?,?,?)",
                   (session_id, user_id, name, kind, json.dumps(members, ensure_ascii=False),
                    now(), order_id, code))

    def sessions(self, user_id: str, order_id: str | None = None) -> list[dict]:
        if order_id is not None:
            return self._all("SELECT * FROM im_session WHERE user_id=? AND order_id=? ORDER BY code",
                             (user_id, order_id))
        return self._all("SELECT * FROM im_session WHERE user_id=? ORDER BY created_at", (user_id,))

    def session(self, session_id: str) -> dict | None:
        return self._one("SELECT * FROM im_session WHERE session_id=?", (session_id,))

    # 资源方事实数据（硬编码基准 + 情景约束推导，落库保证前后一致）

    def save_quote(self, order_id: str, kind: str, payload: dict) -> None:
        self._exec("INSERT OR REPLACE INTO supplier_quote(order_id, kind, payload, updated_at)"
                   " VALUES(?,?,?,?)",
                   (order_id, kind, json.dumps(payload, ensure_ascii=False), now()))

    def quote(self, order_id: str, kind: str) -> dict | None:
        row = self._one("SELECT * FROM supplier_quote WHERE order_id=? AND kind=?", (order_id, kind))
        if not row:
            return None
        try:
            return json.loads(row["payload"] or "{}")
        except Exception:
            return None

    def quotations(self, order_id: str) -> dict[str, dict]:
        out = {}
        for r in self._all("SELECT * FROM supplier_quote WHERE order_id=?", (order_id,)):
            try:
                out[r["kind"]] = json.loads(r["payload"] or "{}")
            except Exception:
                pass
        return out

    def add_im_message(self, session_id: str, sender: str, role: str, content: str,
                       kind: str = "text", payload: dict | None = None) -> int:
        """写一条消息并返回 msg_id（证据链用 `im:session:msg_id` 引用）。"""
        cur = self._exec("INSERT INTO im_message(session_id, sender, role, content, created_at, kind, payload)"
                         " VALUES(?,?,?,?,?,?,?)",
                         (session_id, sender, role, content, now(), kind,
                          json.dumps(payload or {}, ensure_ascii=False)))
        return int(cur.lastrowid)

    def im_messages(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM im_message WHERE session_id=? ORDER BY msg_id", (session_id,))

    def rename_session(self, session_id: str, name: str) -> None:
        self._exec("UPDATE im_session SET name=? WHERE session_id=?", (name, session_id))

    def set_session_members(self, session_id: str, members: list) -> None:
        self._exec("UPDATE im_session SET members=? WHERE session_id=?",
                   (json.dumps(members, ensure_ascii=False), session_id))

    # 文档模板（学员自己写的小节标题，存下来下次直接用）

    def save_doc_template(self, template_id: str, user_id: str, name: str, sections: list,
                          kind: str = "plan") -> None:
        self._exec("INSERT OR REPLACE INTO doc_template(template_id, user_id, name, kind,"
                   " sections, updated_at) VALUES(?,?,?,?,?,?)",
                   (template_id, user_id, name, kind,
                    json.dumps(sections, ensure_ascii=False), now()))

    def doc_templates(self, user_id: str, kind: str = "plan") -> list[dict]:
        return self._all("SELECT * FROM doc_template WHERE user_id=? AND kind=? ORDER BY updated_at DESC",
                         (user_id, kind))

    def doc_template(self, template_id: str) -> dict | None:
        return self._one("SELECT * FROM doc_template WHERE template_id=?", (template_id,))

    # 方案版本（创建方案 → 发送方案 → 客户已读）

    def save_plan(self, plan_id: str, order_id: str, user_id: str, version: int, title: str,
                  days: list, quote: list, note: str = "", status: str = "草稿",
                  channels: list | None = None, created_at: str = "", sent_at: str = "",
                  read_at: str = "", read_due_at: str = "", feedback: str = "",
                  confirm_at: str = "", values: dict | None = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO plan_version(plan_id, order_id, user_id, version, title, days,"
            " quote, note, status, channels, created_at, sent_at, read_at, read_due_at, feedback,"
            " confirm_at, values_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, order_id, user_id, version, title,
             json.dumps(days or [], ensure_ascii=False), json.dumps(quote or [], ensure_ascii=False),
             note, status, json.dumps(channels or [], ensure_ascii=False), created_at, sent_at,
             read_at, read_due_at, feedback, confirm_at,
             json.dumps(values or {}, ensure_ascii=False)))

    def plan(self, plan_id: str) -> dict | None:
        return self._one("SELECT * FROM plan_version WHERE plan_id=?", (plan_id,))

    def plans(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM plan_version WHERE order_id=? ORDER BY version", (order_id,))

    def update_plan(self, plan_id: str, **kv) -> None:
        cols = ", ".join(f"{k}=?" for k in kv)
        self._exec(f"UPDATE plan_version SET {cols} WHERE plan_id=?", (*kv.values(), plan_id))

    # 联系人簿（每单一套：客户 / 地接 / 酒店 / 车队 / 导游 / 司机；票务走平台不用加）

    def save_contact(self, contact_id: str, order_id: str, user_id: str, name: str, kind: str,
                     phone: str = "", source: str = "", note: str = "",
                     added_at: str = "", session_id: str = "", remark: str = "") -> None:
        row = self._one("SELECT * FROM contact WHERE contact_id=?", (contact_id,))
        if row and not remark:
            remark = row.get("remark") or ""
        self._exec("INSERT OR REPLACE INTO contact(contact_id, order_id, user_id, name, kind, phone,"
                   " source, note, added_at, session_id, remark) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (contact_id, order_id, user_id, name, kind, phone, source, note,
                    added_at, session_id, remark))

    def contacts_of(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM contact WHERE order_id=? ORDER BY kind, contact_id",
                         (order_id,))

    def contacts_for_user(self, user_id: str) -> list[dict]:
        """学员级通讯录：跨订单只有一份，谁加过就是加过。"""
        return self._all("SELECT * FROM contact WHERE user_id=? ORDER BY added_at, contact_id",
                         (user_id,))

    def update_contact(self, contact_id: str, **kv) -> None:
        if not kv:
            return
        cols = ", ".join(f"{k}=?" for k in kv)
        self._exec(f"UPDATE contact SET {cols} WHERE contact_id=?", (*kv.values(), contact_id))

    def contact(self, contact_id: str) -> dict | None:
        return self._one("SELECT * FROM contact WHERE contact_id=?", (contact_id,))

    # 订单联系记录

    def add_contact(self, order_id: str, kind: str, at: str, status: str,
                    has_record: bool = False, detail: str = "") -> None:
        self._exec("INSERT INTO order_contact(order_id, kind, at, status, has_record, detail) VALUES(?,?,?,?,?,?)",
                   (order_id, kind, at, status, 1 if has_record else 0, detail))

    def contacts(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_contact WHERE order_id=? ORDER BY contact_id", (order_id,))

    def has_contacts(self, order_id: str) -> bool:
        return bool(self._all("SELECT 1 FROM order_contact WHERE order_id=? LIMIT 1", (order_id,)))

    # 平台通知（消息中心）

    def upsert_notice(self, notice_id: str, user_id: str, group_key: str, title: str,
                      body: str, at: str, starred: bool = False, order_id: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO notice(notice_id, user_id, group_key, title, body, at, starred, order_id)"
                   " VALUES(?,?,?,?,?,?,?,?)",
                   (notice_id, user_id, group_key, title, body, at, 1 if starred else 0, order_id))

    def notices(self, user_id: str) -> list[dict]:
        return self._all("SELECT * FROM notice WHERE user_id=? ORDER BY at DESC", (user_id,))

    # 成本 / 损失 / 结算台账

    def add_finance_entry(self, entry_id: str, order_id: str, code: str, label: str,
                          category: str, amount: float, supplier_kind: str = "",
                          source: str = "", ref: str = "", note: str = "",
                          bearer: str = "待定", ours: float = 0,
                          status: str = "待处理") -> None:
        self._exec("INSERT OR REPLACE INTO finance_entry(entry_id, order_id, code, label, category,"
                   " amount, bearer, ours, supplier_kind, source, ref, note, status, at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (entry_id, order_id, code, label, category, float(amount or 0), bearer,
                    float(ours or 0), supplier_kind, source, ref, note, status, now()))

    def finance_entries(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM finance_entry WHERE order_id=? ORDER BY at, entry_id",
                         (order_id,))

    def finance_entry(self, entry_id: str) -> dict | None:
        return self._one("SELECT * FROM finance_entry WHERE entry_id=?", (entry_id,))

    def update_finance_entry(self, entry_id: str, **kv) -> None:
        if not kv:
            return
        cols = ", ".join(f"{k}=?" for k in kv)
        self._exec(f"UPDATE finance_entry SET {cols} WHERE entry_id=?",
                   tuple(kv.values()) + (entry_id,))

    def save_settlement(self, order_id: str, payload: dict) -> None:
        self._exec("INSERT OR REPLACE INTO order_settlement(order_id, revenue, cost, loss, profit,"
                   " margin, grade, detail, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (order_id, float(payload.get("revenue") or 0), float(payload.get("cost") or 0),
                    float(payload.get("loss") or 0), float(payload.get("profit") or 0),
                    float(payload.get("margin") or 0), payload.get("grade", ""),
                    json.dumps(payload.get("detail") or {}, ensure_ascii=False), now()))

    def settlement(self, order_id: str) -> dict | None:
        row = self._one("SELECT * FROM order_settlement WHERE order_id=?", (order_id,))
        if not row:
            return None
        try:
            row["detail"] = json.loads(row.get("detail") or "{}")
        except Exception:
            row["detail"] = {}
        return row

    # 资源方情景状态（导演控制）

    def set_supplier_state(self, user_id: str, kind: str, payload: dict,
                           order_id: str = "") -> None:
        """写情景约束。`order_id=""` 是导演的全局默认；传订单号则只覆盖这一单。"""
        self._exec("INSERT OR REPLACE INTO supplier_state(user_id, kind, order_id, payload, updated_at)"
                   " VALUES(?,?,?,?,?)",
                   (user_id, kind, order_id or "", json.dumps(payload, ensure_ascii=False), now()))

    def supplier_state_for(self, user_id: str, kind: str, order_id: str = "") -> dict:
        """取该单该资源方的有效约束：全局默认打底，订单级覆盖优先。"""
        out: dict = {}
        keys = ["", order_id] if order_id else [""]
        for oid in keys:
            row = self._one("SELECT payload FROM supplier_state WHERE user_id=? AND kind=? AND order_id=?",
                            (user_id, kind, oid))
            if row:
                try:
                    out.update(json.loads(row["payload"] or "{}"))
                except Exception:
                    pass
        return out

    # 实战证据

    def add_evidence(self, order_id: str, kind: str, step: str, ref: str, text: str) -> int:
        cur = self._exec("INSERT INTO order_evidence(order_id, kind, step, ref, text, created_at) VALUES(?,?,?,?,?,?)",
                         (order_id, kind, step, ref, text, now()))
        return int(cur.lastrowid)

    def evidence(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_evidence WHERE order_id=? ORDER BY evidence_id", (order_id,))

    def has_evidence(self, order_id: str, kind: str, ref: str) -> bool:
        return bool(self._all("SELECT 1 FROM order_evidence WHERE order_id=? AND kind=? AND ref=? LIMIT 1",
                              (order_id, kind, ref)))

    # 官方来源快照（证据闸门的服务端信任根）

    def save_source_snapshot(self, snapshot_id: str, url: str, canonical_url: str, host: str,
                             title: str, content: str, content_hash: str, content_type: str,
                             raw_size: int, created_by: str, fetched_at: str,
                             fetch_method: str = "server_http",
                             status: str = "verified") -> dict:
        self._exec(
            "INSERT OR REPLACE INTO source_snapshot(snapshot_id, url, canonical_url, host, title,"
            " content, content_hash, content_type, raw_size, created_by, fetched_at, fetch_method, status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (snapshot_id, url, canonical_url, host, title, content, content_hash,
             content_type, int(raw_size or 0), created_by, fetched_at, fetch_method, status))
        return self.source_snapshot(snapshot_id) or {}

    def source_snapshot(self, snapshot_id: str) -> dict | None:
        return self._one("SELECT * FROM source_snapshot WHERE snapshot_id=?", (snapshot_id,))

    def source_snapshots(self, host: str = "", limit: int = 20) -> list[dict]:
        if host:
            return self._all("SELECT * FROM source_snapshot WHERE host=?"
                             " ORDER BY fetched_at DESC LIMIT ?", (host, limit))
        return self._all("SELECT * FROM source_snapshot ORDER BY fetched_at DESC LIMIT ?", (limit,))

    def source_snapshot_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM source_snapshot")
        return int((row or {}).get("n") or 0)

    # 实战评分

    def upsert_order_score(self, order_id: str, sp: str, score: float, level: str,
                           hit_negative: bool, evidence: list, comment: str, source: str,
                           confidence: float = 0.0, status: str = "\u5df2\u5165\u5e93",
                           review_reason: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO order_score(order_id, skill_point_id, score, level, hit_negative,"
                   " evidence, comment, source, created_at, confidence, status, review_reason)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (order_id, sp, score, level, 1 if hit_negative else 0,
                    json.dumps(evidence, ensure_ascii=False), comment, source, now(),
                    float(confidence or 0), status, review_reason))

    def order_scores(self, order_id: str) -> dict[str, dict]:
        return {r["skill_point_id"]: r for r in self._all("SELECT * FROM order_score WHERE order_id=?", (order_id,))}

    def pending_reviews(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_score WHERE order_id=? AND status=? ORDER BY skill_point_id",
                         (order_id, "待复核"))

    def set_score_status(self, order_id: str, sp: str, status: str) -> None:
        self._exec("UPDATE order_score SET status=? WHERE order_id=? AND skill_point_id=?", (status, order_id, sp))

    # 考核目标 / 覆盖

    def upsert_target(self, order_id: str, sp: str, checkpoint: str, step: str,
                      trigger_state: str = "pending", covered: bool = False, reason: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO order_target(order_id, skill_point_id, checkpoint, step,"
                   " trigger_state, covered, reason, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (order_id, sp, checkpoint, step, trigger_state, 1 if covered else 0, reason, now()))

    def targets(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_target WHERE order_id=? ORDER BY skill_point_id", (order_id,))

    def target(self, order_id: str, sp: str) -> dict | None:
        return self._one("SELECT * FROM order_target WHERE order_id=? AND skill_point_id=?", (order_id, sp))

    # 导演总线

    def add_event(self, order_id: str, type_: str, payload: dict | None = None) -> int:
        cur = self._exec("INSERT INTO director_event(order_id, type, payload, at) VALUES(?,?,?,?)",
                         (order_id, type_, json.dumps(payload or {}, ensure_ascii=False), now()))
        return int(cur.lastrowid)

    def events(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM director_event WHERE order_id=? ORDER BY event_id", (order_id,))

    def add_incident(self, incident_id: str, order_id: str, code: str, step: str, title: str,
                     channel: str, session_id: str, speaker: str, body: str,
                     skill_points: list, rule: str) -> None:
        self._exec("INSERT OR REPLACE INTO incident(incident_id, order_id, code, step, title, channel,"
                   " session_id, speaker, body, skill_points, rule, at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (incident_id, order_id, code, step, title, channel, session_id, speaker, body,
                    json.dumps(skill_points, ensure_ascii=False), rule, now()))

    def incidents(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM incident WHERE order_id=? ORDER BY at", (order_id,))

    def has_incident(self, order_id: str, code: str) -> bool:
        return bool(self._all("SELECT 1 FROM incident WHERE order_id=? AND code=? LIMIT 1", (order_id, code)))

    # 交付物文档

    def save_deliverable(self, order_id: str, deliverable_id: str, values: dict, rendered: str,
                         audience: list, guard: dict, file_ids: list) -> int:
        row = self._one("SELECT version FROM deliverable_doc WHERE order_id=? AND deliverable_id=?",
                        (order_id, deliverable_id))
        version = int((row or {}).get("version") or 0) + 1
        self._exec("INSERT OR REPLACE INTO deliverable_doc(order_id, deliverable_id, version, values_json,"
                   " rendered, audience, guard_json, file_ids, at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (order_id, deliverable_id, version, json.dumps(values, ensure_ascii=False), rendered,
                    json.dumps(audience, ensure_ascii=False), json.dumps(guard, ensure_ascii=False),
                    json.dumps(file_ids, ensure_ascii=False), now()))
        return version

    def deliverable(self, order_id: str, deliverable_id: str) -> dict | None:
        return self._one("SELECT * FROM deliverable_doc WHERE order_id=? AND deliverable_id=?",
                         (order_id, deliverable_id))

    def deliverables(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM deliverable_doc WHERE order_id=? ORDER BY at", (order_id,))

    def completed_practice_at(self, user_id: str) -> str:
        """本人两份行后文件都已提交的最近完成时间，与平台阶段和覆盖率独立。"""
        from ..contracts.deliverables_spec import PRACTICE_FINAL_CODES, resolve
        required = [resolve(code).id for code in PRACTICE_FINAL_CODES]
        row = self._one("SELECT MAX(completed_at) AS at FROM ("
                        "SELECT d.order_id, MAX(d.at) AS completed_at FROM deliverable_doc d "
                        "JOIN biz_order o ON o.order_id=d.order_id WHERE o.user_id=? "
                        "AND d.deliverable_id IN (?,?) GROUP BY d.order_id "
                        "HAVING COUNT(DISTINCT d.deliverable_id)=?)",
                        (user_id, *required, len(required)))
        return str((row or {}).get("at") or "")

    def deliverable_draft(self, order_id: str, deliverable_id: str) -> dict | None:
        return self._one("SELECT * FROM deliverable_draft WHERE order_id=? AND deliverable_id=?",
                         (order_id, deliverable_id))

    def save_deliverable_drafts(self, order_id: str, drafts: dict[str, dict], validations: dict | None = None) -> list[str]:
        saved = []
        with self._lock, self._conn:
            for did, values in drafts.items():
                if self._conn.execute("SELECT 1 FROM deliverable_doc WHERE order_id=? AND deliverable_id=?",
                                      (order_id, did)).fetchone():
                    continue
                self._conn.execute("INSERT OR REPLACE INTO deliverable_draft "
                                   "(order_id,deliverable_id,values_json,updated_at,validation_json) VALUES(?,?,?,?,?)",
                                   (order_id, did, json.dumps(values, ensure_ascii=False), now(),
                                    json.dumps((validations or {}).get(did) or {}, ensure_ascii=False)))
                saved.append(did)
        return saved

    def save_file(self, file_id: str, order_id: str, deliverable_id: str, filename: str,
                  mime: str, size: int, data: bytes) -> None:
        self._exec("INSERT OR REPLACE INTO deliverable_file(file_id, order_id, deliverable_id, filename,"
                   " mime, size, data, at) VALUES(?,?,?,?,?,?,?,?)",
                   (file_id, order_id, deliverable_id, filename, mime, size, data, now()))

    def file(self, file_id: str) -> dict | None:
        return self._one("SELECT * FROM deliverable_file WHERE file_id=?", (file_id,))

    @staticmethod
    def file_meta(row: dict) -> dict:
        return {k: row[k] for k in ("file_id", "filename", "mime", "size", "deliverable_id") if k in row}

    # 学员动作账本（流程通关驱动）

    def add_action(self, order_id: str, action: str, payload: dict | None = None) -> None:
        self._exec("INSERT INTO order_action(order_id, action, payload, at) VALUES(?,?,?,?)",
                   (order_id, action, json.dumps(payload or {}, ensure_ascii=False), now()))

    def has_action(self, order_id: str, action: str) -> bool:
        return bool(self._all("SELECT 1 FROM order_action WHERE order_id=? AND action=? LIMIT 1",
                              (order_id, action)))

    def action_at(self, order_id: str, action: str) -> str | None:
        row = self._one("SELECT at FROM order_action WHERE order_id=? AND action=? ORDER BY action_id LIMIT 1",
                        (order_id, action))
        return row["at"] if row else None

    def actions(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_action WHERE order_id=? ORDER BY action_id", (order_id,))

    def action_keys(self, order_id: str) -> set[str]:
        return {r["action"] for r in self.actions(order_id)}

    # 校准基线

    def add_calibration_run(self, run_id: str, samples: int, predictions: int, agreement: float,
                            evidence_accuracy: float, stability: float, threshold_conf: float,
                            threshold_delta: float, passed: bool, detail: dict) -> None:
        self._exec("INSERT OR REPLACE INTO calibration_run(run_id, samples, predictions, agreement,"
                   " evidence_accuracy, stability, threshold_conf, threshold_delta, passed, detail, created_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, samples, predictions, agreement, evidence_accuracy, stability,
                    threshold_conf, threshold_delta, 1 if passed else 0,
                    json.dumps(detail, ensure_ascii=False), now()))

    def latest_calibration(self) -> dict | None:
        return self._one("SELECT * FROM calibration_run ORDER BY created_at DESC, run_id DESC LIMIT 1")

    def calibration_runs(self, limit: int = 10) -> list[dict]:
        return self._all("SELECT * FROM calibration_run ORDER BY created_at DESC LIMIT ?", (limit,))

    def incidents_by_session(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM incident WHERE session_id=?", (session_id,))

    # 通话持久化

    def save_call_session(self, session_id: str, order_id: str, user_id: str, customer: str,
                          destination: str, mode: str = "text") -> None:
        self._exec("INSERT OR REPLACE INTO call_session(session_id, order_id, user_id, customer, destination, mode, created_at)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (session_id, order_id, user_id, customer, destination, mode, now()))

    def add_call_line(self, session_id: str, who: str, text: str) -> None:
        self._exec("INSERT INTO call_line(session_id, who, text, created_at) VALUES(?,?,?,?)",
                   (session_id, who, text, now()))

    def call_lines(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM call_line WHERE session_id=? ORDER BY msg_id", (session_id,))

    def call_sessions_for_order(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM call_session WHERE order_id=? ORDER BY created_at", (order_id,))

    def supplier_states(self, user_id: str, order_id: str = "") -> dict[str, dict]:
        """默认返回全局默认档（导演台用）；传订单号则返回该单的有效值。"""
        out: dict[str, dict] = {}
        for r in self._all("SELECT * FROM supplier_state WHERE user_id=?", (user_id,)):
            if order_id:
                out[r["kind"]] = self.supplier_state_for(user_id, r["kind"], order_id)
                continue
            if r.get("order_id"):
                continue
            try:
                out[r["kind"]] = json.loads(r["payload"] or "{}")
            except Exception:
                out[r["kind"]] = {}
        return out

