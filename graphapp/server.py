"""画面の待ち受け(標準ライブラリの http.server だけ。Flask は使わない)。

各ラインPCの Python には追加ライブラリを入れられないため、`http.server` の
`ThreadingHTTPServer` で HTML/CSS/JS と JSON の API を出します。

【守り】127.0.0.1 だけで待ち受け、Host の検証と、書き込み系(POST)の
同一オリジン確認をします(all-tools と同じ考え方)。

【API】(設定タブ)
    GET  /api/settings/state            設定タブの中身ぜんぶ
    POST /api/settings/paths            {"values": {鍵: 値}} 送った欄だけ保存
    POST /api/settings/paths/recheck    いまの状態を読み直す
    GET  /api/fs/browse?path=...        フォルダを選ぶ窓
    POST /api/admin/unlock|lock|password
    POST /api/dist/export|reapply|remove
    GET  /api/log/events?start&end&terminal&level&q
    GET  /api/log/tail?lines=200
    GET  /api/agg/days?line&start&end   大本からたどった各日の集計CSV(確かめる用)
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from . import admin_password, agg_store, app_config, config, distribution, settings_view
from .logging_setup import events as log_events, get_logger, note, tail as log_tail

log = get_logger("server")
STATIC = Path(__file__).resolve().parent / "static"
#: 鍵を開けたままにする長さ(触らなければ閉じる)
ADMIN_IDLE_SECONDS = 30 * 60


class AdminLock:
    """管理者の鍵(この端末で動く1人用のアプリなので、サーバに1つ)。"""

    def __init__(self) -> None:
        self._until = 0.0
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            if time.monotonic() < self._until:
                self._until = time.monotonic() + ADMIN_IDLE_SECONDS
                return True
            return False

    def open(self) -> None:
        with self._lock:
            self._until = time.monotonic() + ADMIN_IDLE_SECONDS

    def close(self) -> None:
        with self._lock:
            self._until = 0.0


ADMIN = AdminLock()


def _date(text: Optional[str], default: date) -> date:
    try:
        return date.fromisoformat(text) if text else default
    except ValueError:
        return default


class Handler(BaseHTTPRequestHandler):
    server_version = "AllLinesGraph/" + app_config.VERSION

    # ---- 共通 -------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # 標準エラーへは出さない
        log.debug("%s %s", self.address_string(), fmt % args)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == self.server.server_port

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(min(length, 1_000_000)).decode("utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ---- GET --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/settings"):
                return self._static("settings.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path == "/api/settings/state":
                return self._json(settings_view.full_state(admin=ADMIN.is_open()))
            if url.path == "/api/fs/browse":
                return self._json(settings_view.browse(q.get("path", "")))
            if url.path == "/api/log/events":
                today = date.today()
                return self._json(log_events(_date(q.get("start"), today - timedelta(days=7)),
                                             _date(q.get("end"), today),
                                             terminal=q.get("terminal", ""), query=q.get("q", ""),
                                             level=q.get("level", "")))
            if url.path == "/api/log/tail":
                return self._json(log_tail(int(q.get("lines", "200") or 200)))
            if url.path == "/api/agg/days":
                return self._json(self._agg_days(q))
            return self._send(404, "見つかりません".encode("utf-8"), "text/plain; charset=utf-8")
        except Exception as exc:  # 画面には理由を返す。ログには詳しく
            log.exception("GET %s に失敗", url.path)
            return self._json({"ok": False, "message": f"内部エラー: {exc}"}, 500)

    def _static(self, name: str) -> None:
        target = (STATIC / name).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def _agg_days(self, q: dict) -> dict:
        roots = config.SETTINGS.agg_roots()
        line = q.get("line", "")
        today = date.today()
        end = _date(q.get("end"), today)
        start = _date(q.get("start"), end.replace(day=1))
        from .logging_setup import timed
        with timed("集計CSVをたどる", lines=[line], start=start, end=end) as info:
            days = agg_store.find_days(roots, line, start, end) if line else []
            info["days"] = len(days)
        return {"roots": [str(r) for r in roots], "lines": agg_store.lines(roots),
                "line": line, "start": start.isoformat(), "end": end.isoformat(),
                "days": [d.to_dict() for d in days]}

    # ---- POST -------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok() or not self._origin_ok():
            return self._send(403, b"forbidden", "text/plain")
        url = urlparse(self.path)
        body = self._body()
        try:
            return self._json(self._post(url.path, body))
        except Exception as exc:
            log.exception("POST %s に失敗", url.path)
            return self._json({"ok": False, "message": f"内部エラー: {exc}"}, 500)

    def _post(self, path: str, body: dict) -> dict:
        admin = ADMIN.is_open()
        pw = str(body.get("password") or "")
        if path == "/api/settings/paths":
            values = body.get("values") if isinstance(body.get("values"), dict) else {}
            result = settings_view.save_paths(values, admin=admin)
            return {**vars(result), "paths": settings_view.paths_state()}
        if path == "/api/settings/paths/recheck":
            return {"ok": True, "paths": settings_view.paths_state()}
        if path == "/api/admin/unlock":
            if admin_password.verify(pw):
                ADMIN.open()
                note("管理者の鍵を開けました", label="鍵を開けた")
                return {"ok": True, "message": "鍵を開けました(30分さわらなければ閉じます)。"}
            return {"ok": False, "message": "管理者パスワードが違います。", "reason": "wrong_password"}
        if path == "/api/admin/lock":
            ADMIN.close()
            return {"ok": True, "message": "鍵を閉じました。"}
        if path == "/api/admin/password":
            result = admin_password.change(str(body.get("current") or ""), str(body.get("new") or ""),
                                           str(body.get("confirm") or ""))
            if result.ok:
                note("管理者パスワードを変えました", label="パスワードを変えた")
            return vars(result)
        if path == "/api/dist/export":
            items = [str(k) for k in body.get("items") or []]
            return {**distribution.export(pw, items, admin=admin).to_dict(),
                    "distribution": distribution.summary()}
        if path == "/api/dist/reapply":
            result = distribution.reapply(pw, admin=admin)
            return {**result.to_dict(), "distribution": distribution.summary(),
                    "paths": settings_view.paths_state()}
        if path == "/api/dist/remove":
            return {**distribution.remove(pw, admin=admin).to_dict(),
                    "distribution": distribution.summary()}
        return {"ok": False, "message": f"知らない操作です: {path}"}


def make_server(port: Optional[int] = None) -> ThreadingHTTPServer:
    """待ち受けを作る。**使われていれば次の番号**(PORT_RETRY 回まで)。port=0 は空いている番号。"""
    if port is not None:
        return ThreadingHTTPServer((app_config.HOST, port), Handler)
    last: Optional[OSError] = None
    for offset in range(app_config.PORT_RETRY):
        try:
            return ThreadingHTTPServer((app_config.HOST, app_config.PORT + offset), Handler)
        except OSError as exc:
            last = exc
    raise OSError(f"待ち受けの番号が空いていません({app_config.PORT}〜): {last}")
