"""ログ出力(all-tools の `logging_setup.py` / `services/event_log.py` の必要部分を移植)。

* **書き先は設定の「ログの出力パス」**(`config.KEY_LOG_DIR`)。決めていなければ
  この端末の `%LOCALAPPDATA%\\AllLinesGraph\\logs`。
* 設定の先に**書けなければこの端末へ書く**(共有に届かない朝でも起動を止めない)。
  書けなかった理由は覚えておき、設定画面に出す。
* 設定画面でパスを変えたら `redirect_logging()` で書き先を移す(再起動しなくてよい)。
* 動いた記録(テキスト)のほかに、**WARNING 以上と操作**を「出来事」(JSON 1行ずつ・日ごと)
  にも残す。設定画面のログの面はこちらを読む(全部の端末ぶん)。
* 要件定義の「起動、DB接続、取得時間、対象期間・ライン、エラー」を残す口として
  `timed()` を置く(取得にかかった時間と条件を1行で)。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from . import app_config, log_names
from .config import SETTINGS

LOGGER_NAME = app_config.TOOL_ID
_FORMAT = "%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5
#: 出来事を残す日数(all-tools と同じ半年)
KEEP_DAYS = 180

_state: dict[str, object] = {"path": None, "dir": None, "problem": ""}
_lock = threading.RLock()


def get_logger(component: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if component is None else f"{LOGGER_NAME}.{component}")


def _usable(wanted: Path) -> Path:
    """書けるフォルダ。**書けなければこの端末の logs\\all_lines_graph**(理由を覚える)。"""
    try:
        wanted.mkdir(parents=True, exist_ok=True)
        probe = wanted / f".{app_config.TOOL_ID}_write_check"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        _state["problem"] = ""
        return wanted
    except OSError as exc:
        fallback = log_names.tool_dir(SETTINGS.default_log_dir)
        _state["problem"] = f"{wanted} に書けません({exc})"
        if fallback == wanted:
            raise
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class EventHandler(logging.Handler):
    """WARNING 以上(と `note()` で残す操作)を、日ごと・端末ごとの JSONL に書く。"""

    def __init__(self, folder: Path) -> None:
        super().__init__(level=logging.INFO)
        self.folder = folder
        self.terminal = app_config.terminal_name()

    def emit(self, record: logging.LogRecord) -> None:
        label = getattr(record, "event_label", "")
        if record.levelno < logging.WARNING and not label:
            return                                    # 普通の INFO は動いた記録だけ
        try:
            when = datetime.fromtimestamp(record.created)
            row = {
                "at": when.strftime("%Y-%m-%d %H:%M:%S"),
                "level": (record.levelname if record.levelno >= logging.WARNING else "操作"),
                "terminal": self.terminal,
                "where": record.name,
                "message": record.getMessage(),
            }
            if label:
                row["label"] = label
            if record.exc_info:
                row["detail"] = logging.Formatter().formatException(record.exc_info)
            path = self.folder / log_names.event_name(when.date(), self.terminal)
            with _lock, open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:  # ログが書けないことで本体を止めない
            self.handleError(record)


def init_logging(log_dir: Optional[Path] = None, level: int = logging.INFO) -> logging.Logger:
    """ログを組む。**何度呼んでもよい**(書き先が変わったときだけ付け替える)。"""
    with _lock:
        wanted = Path(log_dir) if log_dir is not None else SETTINGS.log_dir
        folder = _usable(log_names.tool_dir(wanted))
        log_path = folder / log_names.text_log_name(app_config.terminal_name())
        logger = get_logger()
        logger.setLevel(level)
        logger.propagate = False
        for handler in list(logger.handlers):
            if getattr(handler, "_alg_path", None) not in (None, log_path):
                logger.removeHandler(handler)
                handler.close()
        if not any(getattr(h, "_alg_path", None) == log_path for h in logger.handlers):
            text = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
            text.setFormatter(logging.Formatter(_FORMAT))
            text._alg_path = log_path  # type: ignore[attr-defined]
            events = EventHandler(folder)
            events._alg_path = log_path  # type: ignore[attr-defined]
            logger.addHandler(text)
            logger.addHandler(events)
        _state["path"] = log_path
        _state["dir"] = folder
    if _state["problem"]:
        logger.warning("ログの出力パスに書けないので、この端末へ書きます: %s", _state["problem"])
    return logger


def redirect_logging() -> dict:
    """設定の「ログの出力パス」へ書き先を移す。移した先と、移せなかった理由を返す。"""
    before = _state.get("path")
    init_logging()
    after = _state.get("path")
    if before != after:
        note(f"ログの書き先を移しました: {before} → {after}", label="ログの出力パスを変えた")
    return status()


def status() -> dict:
    return {"path": str(_state["path"] or ""), "dir": str(_state["dir"] or ""),
            "problem": str(_state["problem"] or ""),
            "configured": str(SETTINGS.log_dir), "fallback": str(SETTINGS.default_log_dir)}


def note(message: str, *, label: str = "") -> None:
    """**操作**を出来事にも残す(設定を変えた・配布設定を書き出した など)。

    出来事は WARNING 以上と、ここで印(`event_label`)を付けたものだけを拾う。
    テキストの動いた記録にも同じ1行が出る。
    """
    get_logger("操作").info(message, extra={"event_label": label or "操作"})


@contextmanager
def timed(what: str, *, lines: Optional[list[str]] = None, start: Optional[date] = None,
          end: Optional[date] = None) -> Iterator[dict]:
    """取得にかかった時間と条件を1行で残す(要件定義 8 のログ)。

        with timed("集計CSVを読む", lines=["L-1"], start=d1, end=d2) as info:
            info["rows"] = len(rows)
    """
    info: dict = {}
    began = time.perf_counter()
    try:
        yield info
    except Exception:
        get_logger("取得").exception("%s に失敗(ライン %s / 期間 %s〜%s)", what,
                                    ",".join(lines or []) or "-", start or "-", end or "-")
        raise
    seconds = time.perf_counter() - began
    extra = " ".join(f"{k}={v}" for k, v in info.items())
    get_logger("取得").info("%s %.3f秒 ライン=%s 期間=%s〜%s %s", what, seconds,
                           ",".join(lines or []) or "-", start or "-", end or "-", extra)


# ----------------------------------------------------------------------
# 読む(設定画面のログの面)
# ----------------------------------------------------------------------
def _event_files(folder: Path, first: date, last: date) -> list[Path]:
    try:
        names = sorted(folder.iterdir())
    except OSError:
        return []
    out = []
    for path in names:
        parts = log_names.event_parts(path.name)
        if parts and first <= parts[0] <= last:
            out.append(path)
    return out


def _read_folders() -> list[Path]:
    """読むフォルダ(設定の先と、書けなかったときの逃げ先)。"""
    folders = [log_names.tool_dir(SETTINGS.log_dir),
               log_names.tool_dir(SETTINGS.default_log_dir)]
    out: list[Path] = []
    for folder in folders:
        if folder not in out:
            out.append(folder)
    return out


def events(start: date, end: date, *, terminal: str = "", query: str = "",
           level: str = "", limit: int = 500) -> dict:
    """期間の出来事(新しい順)。全端末ぶん。**壊れた行は飛ばす。**"""
    rows: list[dict] = []
    terminals: set[str] = set()
    for folder in _read_folders():
        for path in _event_files(folder, start, end):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                terminals.add(str(row.get("terminal", "")))
                if terminal and row.get("terminal") != terminal:
                    continue
                if level and row.get("level") != level:
                    continue
                if query and query not in json.dumps(row, ensure_ascii=False):
                    continue
                rows.append(row)
    rows.sort(key=lambda r: str(r.get("at", "")), reverse=True)
    return {"rows": rows[:limit], "total": len(rows), "truncated": len(rows) > limit,
            "terminals": sorted(t for t in terminals if t)}


def tail(lines: int = 200) -> dict:
    """この端末の動いた記録の終わりのほう。"""
    path = _state.get("path")
    if not path:
        return {"path": "", "lines": []}
    try:
        with open(str(path), encoding="utf-8", errors="replace") as handle:
            content = handle.readlines()[-max(1, min(lines, 2000)):]
    except OSError as exc:
        return {"path": str(path), "lines": [], "error": str(exc)}
    return {"path": str(path), "lines": [c.rstrip("\n") for c in content]}


def prune_events(today: Optional[date] = None) -> int:
    """半年より古い出来事を消す(**この端末が書いたものだけ**。ほかの端末のは触らない)。"""
    today = today or date.today()
    mine = log_names.safe(app_config.terminal_name())
    limit = today - timedelta(days=KEEP_DAYS)
    removed = 0
    for folder in _read_folders():
        for path in _event_files(folder, date(1900, 1, 1), limit - timedelta(days=1)):
            parts = log_names.event_parts(path.name)
            if parts and parts[1] == mine:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


# ----------------------------------------------------------------------
# 起動の記録(業務ログとは別のファイル。組み上がる前に失敗した理由を残す)
# ----------------------------------------------------------------------
def get_launch_logger() -> logging.Logger:
    logger = logging.getLogger(f"{LOGGER_NAME}.launch")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    name = log_names.launch_log_name(app_config.terminal_name())
    for base in (SETTINGS.log_dir, SETTINGS.default_log_dir):
        try:
            folder = log_names.tool_dir(base)
            folder.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                folder / name, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
        except OSError:
            continue
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        break
    return logger
