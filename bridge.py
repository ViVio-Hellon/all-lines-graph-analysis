"""デスクトップ版(Tauri)からの入口 ── **ポートを使わない**

ブラウザ版(`start_app.py`)は 127.0.0.1 で待ち受けるが、デスクトップ版では外枠
(Rust/Tauri、`src-tauri/`)がこのプロセスを子として起動し、**標準入出力**で要求を渡す。
ソケットは1つも開かない。中の振り分けはブラウザ版と同じ `graphapp.server.Exchange`。

    外枠(Rust) ──標準入力──▶ bridge.py ──▶ Exchange(ブラウザ版と同じ振り分け)
               ◀──標準出力──

【やりとりの形】1件 = 見出し1行(JSON)+ 本文(見出しの `len` バイト)。python-web-tools と同じ。

    要求  {"id": 7, "method": "POST", "path": "/api/x?a=1", "headers": [[k, v], ...], "len": 12}\\n<本文>
    応答  {"id": 7, "status": 200, "headers": [[k, v], ...], "len": 345}\\n<本文>
    知らせ {"event": "started"} / {"event": "fatal", "message": ..., "log_dir": ...}

本文を JSON に埋めない(base64 にしない)のは、画像で保存の要求が数MBになるため。

【標準出力を守る】やりとりに使う標準出力へ誰かが1文字でも書くと、以降すべてずれる。
**最初に**本物の標準出力を取っておき、ファイル記述子 1 は標準エラーへ付け替える。

【終わり】外枠が終わると標準入力が閉じるので、ここも終わる(取り残さない)。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO, Optional

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

#: 同時に捌く要求の数(画面はグラフのカードの数だけ同時に取りに来る)
WORKERS = 8
#: 1件の本文の上限(外枠 `src-tauri/src/bridge.rs` の MAX_BODY と同じ)
MAX_BODY = 64 * 1024 * 1024


class FrameTooLarge(Exception):
    def __init__(self, head: dict, size: int) -> None:
        super().__init__(f"本文が大きすぎます: {size}")
        self.head, self.size = head, size


def read_frame(stream: BinaryIO) -> Optional[tuple[dict, bytes]]:
    """1件読む。相手が閉じたら None。上限を超えた本文は読み捨てて `FrameTooLarge`。"""
    line = stream.readline()
    if not line:
        return None
    head = json.loads(line.decode("utf-8"))
    size = int(head.get("len", 0) or 0)
    if size < 0:
        raise ValueError(f"本文の長さが不正です: {size}")
    if size > MAX_BODY:
        left = size
        while left > 0:
            chunk = stream.read(min(left, 1 << 20))
            if not chunk:
                raise EOFError("本文の途中で終わりました")
            left -= len(chunk)
        raise FrameTooLarge(head, size)
    body = b""
    while len(body) < size:
        chunk = stream.read(size - len(body))
        if not chunk:
            raise EOFError("本文の途中で終わりました")
        body += chunk
    return head, body


class FrameWriter:
    """応答と知らせを書く。**1件ずつ丸ごと**(複数のスレッドから来る)。"""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, head: dict, body: bytes = b"") -> None:
        head = dict(head)
        if "id" in head:
            head["len"] = len(body)
        data = json.dumps(head, ensure_ascii=False).encode("utf-8") + b"\n" + body
        with self._lock:
            self._stream.write(data)
            self._stream.flush()

    def event(self, name: str, **fields) -> None:
        self.write({"event": name, **fields})


def handle(head: dict, body: bytes) -> tuple[int, list, bytes]:
    from graphapp.server import Exchange

    headers = {str(k): str(v) for k, v in head.get("headers") or []}
    status, ctype, data = Exchange(str(head.get("method", "GET")), str(head.get("path", "/")),
                                   headers, body, transport="bridge").run()
    return status, [["Content-Type", ctype], ["Cache-Control", "no-store"]], data


def _protect_stdout() -> BinaryIO:
    """本物の標準出力を取っておき、fd 1 は標準エラーへ(print が混ざらないように)。"""
    real = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except OSError:
        pass
    sys.stdout = sys.stderr
    return real


def startup() -> None:
    """ブラウザ版の start_app と同じ準備(ログ・配布設定)。待ち受けはしない。"""
    from graphapp import app_config, config, distribution
    from graphapp.logging_setup import get_launch_logger, init_logging, prune_events, redirect_logging

    launch = get_launch_logger()
    launch.info("デスクトップ版の中身を起動します %s %s(Python %s)", app_config.DISPLAY_NAME,
                app_config.VERSION, sys.version.split()[0])
    logger = init_logging()
    applied = distribution.apply_on_start()
    launch.info(distribution.describe())
    if applied.error:
        launch.warning(applied.error)
    redirect_logging()
    prune_events()
    logger.info("デスクトップ版で起動しました(ポートなし・端末 %s)。集計データの大本: %s",
                app_config.terminal_name(), " / ".join(str(r) for r in config.SETTINGS.agg_roots()))


def serve(stdin: BinaryIO, writer: FrameWriter) -> None:
    pool = ThreadPoolExecutor(max_workers=WORKERS)

    def one(head: dict, body: bytes) -> None:
        try:
            status, headers, data = handle(head, body)
        except Exception as exc:  # 画面に理由を返す(ここで落ちると外枠が待ち続ける)
            status, headers = 500, [["Content-Type", "application/json; charset=utf-8"]]
            data = json.dumps({"ok": False, "message": f"内部エラー: {exc}"}, ensure_ascii=False).encode("utf-8")
        writer.write({"id": head.get("id"), "status": status, "headers": headers}, data)

    try:
        while True:
            try:
                frame = read_frame(stdin)
            except FrameTooLarge as exc:
                writer.write({"id": exc.head.get("id"), "status": 413,
                              "headers": [["Content-Type", "text/plain; charset=utf-8"]]},
                             "大きすぎます".encode("utf-8"))
                continue
            if frame is None:
                break                       # 外枠が終わった
            pool.submit(one, *frame)
    finally:
        pool.shutdown(wait=True)


def main() -> int:
    real_out = _protect_stdout()
    writer = FrameWriter(real_out)
    try:
        startup()
    except Exception as exc:
        log_dir = ""
        try:
            from graphapp.config import SETTINGS
            log_dir = str(SETTINGS.default_log_dir)
        except Exception:
            pass
        writer.event("fatal", message=f"起動できませんでした: {exc}", log_dir=log_dir)
        return 1
    writer.event("started")
    serve(sys.stdin.buffer, writer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
