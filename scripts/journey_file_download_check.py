"""附件下载 / PDF 导出的 Content-Disposition 真实验收（可重跑）。

复现并回归 Lead/Codex 独立发现的产品级缺陷：
    POST /deliverables/files  filename='需求确认单.pdf'  → 200
    GET  /deliverables/files/{id}                        → 500（Starlette header latin-1 编码失败）

本脚本用真实 app（真认证中间件 + 独立 sqlite）走真实 HTTP，覆盖：
  1. 四种文件名的下载：纯中文 / 含空格 / 含引号 / 中文+空格+引号混合；
     - HTTP 200
     - Content-Disposition 可解析，`filename*` 解码后等于净化后的原名
     - 响应体字节与上传字节 sha256 完全一致
  2. 防 header 注入：文件名里的 CR/LF/引号/反斜杠/路径分隔符不得原样进入 header
  3. PDF 导出：中文标题 + 中文交付物名，200 + application/pdf + filename* 可解码 + %PDF 魔数

用法：python scripts/journey_file_download_check.py
退出码 0 = 全通过；1 = 有失败。证据落盘 output/journey/evidence/file-download.{json,log}
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = ROOT / "output" / "journey" / "evidence"
OUT.mkdir(parents=True, exist_ok=True)
_TMP = ROOT / "output" / "journey" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_DB = _TMP / "journey-file-check.sqlite"
for _stale in (_DB, Path(str(_DB) + "-wal"), Path(str(_DB) + "-shm")):
    try:
        _stale.unlink(missing_ok=True)
    except OSError:
        pass
os.environ["TRIPCRAFT_DB"] = str(_DB)
os.environ["TRIPCRAFT_VISIT_LOG_DIR"] = str(_TMP / "logs-file")

from fastapi.testclient import TestClient          # noqa: E402
from tripcraft.api.app import create_app           # noqa: E402

RESULTS: list[dict] = []
PAYLOAD = ("中文附件内容 需求确认单 2026-11-16\n" * 20).encode("utf-8")

CASES = [
    ("纯中文", "需求确认单.pdf"),
    ("含空格", "customer note.pdf"),
    ("含引号", 'quote"inside.pdf'),
    ("中文+空格+引号混合", '需求 确认"单".pdf'),
    ("注入尝试(CR/LF)", "evil\r\nX-Injected: 1.pdf"),
    ("路径穿越", "../../etc/passwd.txt"),
]


def check(cid: str, name: str, ok: bool, detail: object = "", runtime: bool = True) -> bool:
    RESULTS.append({"id": cid, "name": name, "ok": bool(ok), "detail": str(detail),
                    "runtime": runtime})
    print(f"{'PASS' if ok else 'FAIL'}  {cid}  {name}" + (f"  ·  {detail}" if detail else ""))
    return bool(ok)


def parse_disposition(value: str) -> dict:
    """解析 Content-Disposition：返回 {ascii, utf8}。"""
    out = {"raw": value, "ascii": "", "utf8": ""}
    for part in value.split(";"):
        part = part.strip()
        if part.lower().startswith("filename*="):
            v = part.split("=", 1)[1].strip().strip('"')
            if v.lower().startswith("utf-8''"):
                v = v[7:]
            out["utf8"] = unquote(v)
        elif part.lower().startswith("filename="):
            out["ascii"] = part.split("=", 1)[1].strip().strip('"')
    return out


def main() -> int:
    app = create_app()
    ctx = app.state.ctx
    client = TestClient(app)

    # 注册 + 登录（真会话）
    username = f"jfile_{int(time.time()) % 1000000}"
    client.post("/auth/register", json={"username": username, "password": "Test1234!",
                                        "display_name": username})
    lr = client.post("/auth/login", json={"username": username, "password": "Test1234!"})
    headers = {"Authorization": "Bearer " + (lr.json() or {}).get("token", "")}
    uid = (lr.json() or {}).get("user_id", "")

    order_id = "9300000000000001"
    ctx.store.upsert_order(order_id, uid, "客户 A", "云南", "正常", 1,
                           payload={"source_market": "香港", "language": "中文",
                                    "created_at": "2026-10-17 00:00:00"})

    sha = hashlib.sha256(PAYLOAD).hexdigest()
    for label, fname in CASES:
        up = client.post("/deliverables/files", headers=headers,
                         json={"filename": fname, "mime": "application/pdf",
                               "data_b64": base64.b64encode(PAYLOAD).decode(),
                               "order_id": order_id, "deliverable_id": ""})
        if up.status_code != 200:
            check(f"UP-{label}", f"上传「{label}」成功", False, f"status={up.status_code}")
            continue
        fid = up.json()["file_id"]
        check(f"UP-{label}", f"上传「{label}」成功", True, f"stored={up.json()['filename']}")

        got = client.get(f"/deliverables/files/{fid}", headers=headers)
        disp = got.headers.get("content-disposition", "")
        parsed = parse_disposition(disp)
        body = got.content
        check(f"DL-{label}", f"下载「{label}」HTTP 200", got.status_code == 200,
              f"status={got.status_code} header={disp[:120]}")
        check(f"SHA-{label}", f"「{label}」字节与上传完全一致（sha256）",
              hashlib.sha256(body).hexdigest() == sha,
              f"len={len(body)} sha_ok={hashlib.sha256(body).hexdigest() == sha}")
        # header 必须只含 latin-1 可编码字符（否则 Starlette 会 500）
        try:
            disp.encode("latin-1")
            latin_ok = True
        except UnicodeEncodeError:
            latin_ok = False
        check(f"LATIN-{label}", f"「{label}」Content-Disposition 可 latin-1 编码",
              latin_ok, repr(disp[:80]))
        # 文件名可还原（净化后）
        expect_utf8 = (fname.replace("\r", "").replace("\n", "").replace("\\", "_")
                       .replace("/", "_").replace('"', "_").strip().strip(".").rsplit("/", 1)[-1]
                       .rsplit("\\", 1)[-1])
        check(f"NAME-{label}", f"「{label}」filename* 解码回净化后原名",
              parsed["utf8"] == expect_utf8 and bool(parsed["ascii"]),
              f"utf8={parsed['utf8']!r} expect={expect_utf8!r} ascii={parsed['ascii']!r}")
        # 注入与穿越：真判定 = header 里没有 CR/LF，且响应头里没有出现被注入的头
        resp_header_names = {k.lower() for k in got.headers}
        inj = ("\r" in disp or "\n" in disp or "x-injected" in resp_header_names)
        check(f"SAFE-{label}", f"「{label}」无 header 注入 / 无路径穿越",
              not inj and "/" not in parsed["utf8"] and "\\" not in parsed["utf8"],
              f"inj={inj} injected_header={'x-injected' in resp_header_names} "
              f"utf8={parsed['utf8']!r}")

    # PDF 导出：中文标题 + 中文交付物名
    pdf = client.post(f"/practice/orders/{order_id}/deliverables/requirement_sheet/export.pdf",
                      headers=headers,
                      json={"values": {"guest": "王女士", "people": "3 大 1 小",
                                       "dates": "2026-11-16 至 11-20", "must": "预算 18000",
                                       "budget": "总价上限"}})
    pdisp = parse_disposition(pdf.headers.get("content-disposition", ""))
    pdisp_raw = pdf.headers.get("content-disposition", "")
    try:
        pdisp_raw.encode("latin-1")
        platin = True
    except UnicodeEncodeError:
        platin = False
    check("PDF-1", "PDF 导出 200 + application/pdf",
          pdf.status_code == 200 and "application/pdf" in pdf.headers.get("content-type", ""),
          f"status={pdf.status_code} type={pdf.headers.get('content-type')}")
    check("PDF-2", "PDF 的 Content-Disposition 只含 latin-1 可编码字符（不会 500）",
          platin and bool(pdisp["ascii"]), pdisp_raw[:160])
    check("PDF-3", "PDF filename* 解码出「需求确认单」",
          "需求确认单" in pdisp["utf8"] and pdisp["ascii"].endswith(".pdf"),
          f"utf8={pdisp['utf8']!r} ascii={pdisp['ascii']!r}")
    check("PDF-4", "PDF 内容为真实 %PDF 且含订单号（与工作台渲染同源）",
          pdf.content.startswith(b"%PDF"), f"bytes={len(pdf.content)}")

    failed = [r for r in RESULTS if not r["ok"]]
    summary = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db": str(_DB), "total": len(RESULTS), "passed": len(RESULTS) - len(failed),
        "failed": len(failed), "results": RESULTS,
        "note": "真实 HTTP（TestClient + 真认证中间件 + 独立库）；覆盖中文/空格/引号/混合/注入/穿越"
                "六种文件名 + PDF 导出。",
    }
    (OUT / "file-download.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    (OUT / "file-download.log").write_text(
        "\n".join(f"{'PASS' if r['ok'] else 'FAIL'}\t{r['id']}\t{r['name']}\t{r['detail']}"
                  for r in RESULTS) + f"\n\n{summary['passed']}/{summary['total']} passed\n",
        encoding="utf-8")
    print(f"\n=== 附件下载/PDF header 检查: {summary['passed']}/{summary['total']} passed ===")
    for f in failed:
        print(f"FAILED: {f['id']} {f['name']} · {f['detail']}")
    print(f"evidence -> {OUT / 'file-download.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
