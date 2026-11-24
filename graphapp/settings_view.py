"""設定タブの中身を組み立てる所(画面は写すだけ。**判断はここ**)。

all-tools の `presenters/settings.py` / `_settings_parts.html` の考え方を移植:

* パスを決めるのは「参照設定」の面だけ。**読みに行く先 / 書き出す先**に分けて同じ形で並べる。
* 「設定した値」と「実際に見る道」を両方出す(相対で書いたときにどこを見ているか分かる)。
* 印の文言はサーバが決める(フォルダの欄は「このフォルダがあります / ありません」)。
* 欄ごとに保存する。保存は**送った欄だけ**を書く(送っていない欄は触らない)。
* 守る欄(読みに行く先を変える = 別のデータを読ませる)は管理者の鍵が要る。
  ログの出力パスは要らない ── 守る対象を増やすほど、現場はパスワードを紙に貼る。
"""
from __future__ import annotations

import os
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import agg_store, app_config, config, distribution, user_settings
from .logging_setup import note, redirect_logging, status as log_status


@dataclass(frozen=True)
class PathSpec:
    key: str
    label: str
    group: str
    note: str
    empty_text: str
    protected: bool = False
    is_file: bool = False


GROUP_READ = "読みに行く先"
GROUP_WRITE = "書き出す先"

SPECS: tuple[PathSpec, ...] = (
    PathSpec(config.KEY_AGG_ROOT, "集計データの大本", GROUP_READ,
             "日報管理ツールの「集計CSV・印刷用HTMLの出力パス」と同じフォルダを指します。"
             "決めるのは大本だけ ── <ライン>\\集計\\<yyyy.mm>\\<dd> はアプリがたどります。",
             "空なら この端末の日報管理ツールの既定の出力先(NippouTool\\work)", protected=True),
    PathSpec(config.KEY_AGG_ROOT2, "集計データの大本(2つ目)", GROUP_READ,
             "日報管理ツールで「集計CSVの出力パス(2つ目)」を使っているときだけ。"
             "1つ目に無い日だけ、ここから拾います。",
             "空なら見ない", protected=True),
    PathSpec(config.KEY_ACCESS_DIR, "共有の日報データの置き場所", GROUP_READ,
             "読み取り専用で読みます(書き込み・テーブルの変更はしません)。",
             "空なら使わない", protected=True),
    PathSpec(config.KEY_ACCESS_DB_FILE, "共有の日報データのファイル名", GROUP_READ,
             "ふつうは決めなくて構いません。",
             config.DEFAULT_ACCESS_DB_FILE, protected=True, is_file=True),
    PathSpec(config.KEY_LOG_DIR, "ログの出力パス", GROUP_WRITE,
             "この下の all_lines_graph\\ に端末ごとのファイルで書きます。"
             "共有のフォルダにすると、どの端末のエラーも1か所で見られます。",
             "空なら この端末の中(%LOCALAPPDATA%\\AllLinesGraph\\logs)"),
    PathSpec(config.KEY_EXPORT_DIR, "CSV・画像の書き出し先", GROUP_WRITE,
             "ダッシュボードの「CSVに出す」「画像で保存」はここの下の <yyyy.mm> フォルダへ書きます"
             "(ブラウザのダウンロードは使いません)。",
             "空なら この端末の中(%LOCALAPPDATA%\\AllLinesGraph\\work)"),
)
SPEC_BY_KEY = {s.key: s for s in SPECS}
PROTECTED = frozenset(s.key for s in SPECS if s.protected)


@dataclass
class PathView:
    key: str
    label: str
    group: str
    note: str
    empty_text: str
    protected: bool
    is_file: bool
    value: str = ""
    resolved: str = ""
    is_default: bool = False
    from_dist: bool = False
    is_relative: bool = False
    off: bool = False
    exists: bool = False
    found_text: str = ""
    missing_text: str = ""
    error: str = ""
    checked_at: str = ""
    extra: dict = field(default_factory=dict)


def _exists(path: Optional[Path]) -> tuple[bool, str]:
    if path is None:
        return False, ""
    try:
        return path.exists(), ""
    except OSError as exc:
        return False, str(exc)


def _view(spec: PathSpec, current: dict[str, Any], came: dict[str, Any]) -> PathView:
    raw = current.get(spec.key)
    value = raw.strip() if isinstance(raw, str) else ""
    view = PathView(**{k: getattr(spec, k) for k in
                       ("key", "label", "group", "note", "empty_text", "protected", "is_file")},
                    value=value, checked_at=datetime.now().strftime("%H:%M:%S"))
    view.is_default = not value
    view.from_dist = bool(value) and came.get(spec.key) == raw
    view.is_relative = config.is_relative_setting(value)
    s = config.SETTINGS
    target: Optional[Path]
    if spec.key == config.KEY_AGG_ROOT:
        target = s.agg_root
    elif spec.key == config.KEY_AGG_ROOT2:
        target = s.agg_root_2
    elif spec.key == config.KEY_ACCESS_DIR:
        target = s.access_dir
    elif spec.key == config.KEY_ACCESS_DB_FILE:
        target = s.access_db_path
    elif spec.key == config.KEY_EXPORT_DIR:
        target = s.export_dir
    else:
        target = s.log_dir
    if target is None:
        view.off = True
        view.resolved = "(使っていません)"
        if spec.key == config.KEY_ACCESS_DB_FILE:
            view.resolved = f"(置き場所が空なので使っていません){s.access_db_filename}"
        return view
    view.resolved = str(target)
    view.exists, view.error = _exists(target)
    if spec.is_file:
        view.found_text, view.missing_text = "このファイルがあります", "このファイルがありません"
    else:
        view.found_text, view.missing_text = "このフォルダがあります", "このフォルダがありません"
    if spec.key in (config.KEY_LOG_DIR, config.KEY_EXPORT_DIR) and not view.exists:
        view.missing_text = "このフォルダがありません(初めて書くときに作ります)"
    if spec.key in (config.KEY_AGG_ROOT, config.KEY_AGG_ROOT2) and view.exists:
        scan = agg_store.scan_root(target)
        view.extra = {"scan": scan.to_dict(), "example": agg_store.example_path(
            target if scan.level == "大本" else target.parent if scan.level == "ライン" else target.parent.parent,
            scan.lines[0]["line"] if scan.lines else "<ライン>")}
        if scan.error:
            view.found_text = "フォルダはありますが、集計データが見つかりません"
    return view


def paths_state() -> dict[str, Any]:
    current = user_settings.load()
    came = distribution._from_distribution(current)
    rows = [asdict(_view(spec, current, came)) for spec in SPECS]
    groups = []
    for name in (GROUP_READ, GROUP_WRITE):
        groups.append({"label": name, "rows": [r for r in rows if r["group"] == name]})
    return {"groups": groups, "problem": user_settings.last_problem()}


@dataclass
class SaveResult:
    ok: bool
    message: str
    reason: str = ""
    saved: list[str] = field(default_factory=list)


def save_paths(values: dict[str, Any], *, admin: bool) -> SaveResult:
    """**送った欄だけ**保存する。守る欄は鍵が要る。空は「既定に戻す」。"""
    unknown = [k for k in values if k not in SPEC_BY_KEY]
    if unknown:
        return SaveResult(False, "知らない欄です: " + ", ".join(unknown), "bad_input")
    locked = [SPEC_BY_KEY[k].label for k in values if k in PROTECTED and not admin]
    if locked:
        return SaveResult(False, "「" + "・".join(locked) + "」を変えるには、面の上の鍵を開けてください"
                          "(管理者パスワード)。", "need_password")
    cleaned: dict[str, Any] = {}
    for key, raw in values.items():
        text = str(raw or "").strip().strip('"').strip()
        if text and SPEC_BY_KEY[key].is_file and any(ch in text for ch in "\\/"):
            return SaveResult(False, "ファイル名の欄には名前だけを書いてください(フォルダは置き場所の欄へ)。",
                              "bad_input")
        cleaned[key] = text or None
    try:
        before = user_settings.load_checked()
    except user_settings.SettingsUnreadable as exc:
        return SaveResult(False, f"この端末の設定ファイルを読めないので保存しませんでした: {exc}",
                          "settings_unreadable")
    if not user_settings.save_many(cleaned):
        return SaveResult(False, "保存できませんでした: " + user_settings.last_problem(), "failed")
    changed = [SPEC_BY_KEY[k].label for k, v in cleaned.items() if (before.get(k) or None) != v]
    if config.KEY_LOG_DIR in cleaned:
        redirect_logging()
    for key, value in cleaned.items():
        if (before.get(key) or None) != value:
            note(f"参照設定を変えました: {SPEC_BY_KEY[key].label} = {value or '(既定)'}",
                 label="参照設定を変えた")
    return SaveResult(True, "保存しました" if changed else "変わっていません(同じ値です)", saved=changed)


# ----------------------------------------------------------------------
# フォルダを選ぶ窓(all-tools `presenters/fs_browse.py`)
# ----------------------------------------------------------------------
MAX_ENTRIES = 300


def drives() -> list[dict]:
    if os.name != "nt":
        return [{"name": "/", "path": "/"}]
    out = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if Path(root).is_dir():
                out.append({"name": f"{letter}:", "path": root})
        except OSError:
            continue
    return out


def browse(text: str) -> dict[str, Any]:
    """フォルダの中(フォルダ名と、集計CSV・DBらしいファイル名だけ)。**中身は返さない。**"""
    raw = (text or "").strip().strip('"')
    target = Path(raw).expanduser() if raw else app_config.APP_ROOT
    parts = list(target.parts)
    crumbs = [{"name": parts[i].rstrip("\\/") or parts[i], "path": str(Path(*parts[:i + 1]))}
              for i in range(len(parts))]
    view: dict[str, Any] = {"path": str(target), "exists": False, "parent": "", "dirs": [],
                            "files": [], "truncated": False, "error": "",
                            "crumbs": crumbs, "drives": drives()}
    view["parent"] = str(target.parent) if target.parent != target else ""
    try:
        view["exists"] = target.is_dir()
    except OSError as exc:
        view["error"] = str(exc)
        return view
    if not view["exists"]:
        view["error"] = "フォルダがありません"
        return view
    try:
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        view["error"] = str(exc)
        return view
    for entry in entries:
        if len(view["dirs"]) + len(view["files"]) >= MAX_ENTRIES:
            view["truncated"] = True
            break
        try:
            if entry.is_dir():
                view["dirs"].append(entry.name)
            elif entry.suffix.lower() in (".csv", ".sqlite3", ".sqlite", ".db", ".accdb"):
                view["files"].append(entry.name)
        except OSError:
            continue
    # ここが大本・ライン・集計のどれに見えるか(選ぶときの手がかり)
    if view["exists"]:
        scan = agg_store.scan_root(target, with_latest=False)
        view["agg_level"] = scan.level
        view["agg_lines"] = [r["line"] for r in scan.lines]
    return view


def full_state(*, admin: bool) -> dict[str, Any]:
    return {
        "app": {"name": app_config.DISPLAY_NAME, "version": app_config.VERSION,
                "terminal": app_config.terminal_name(), "root": str(app_config.APP_ROOT),
                "local": str(app_config.local_root()),
                "settings_file": str(user_settings.path())},
        "admin": admin,
        "paths": paths_state(),
        "distribution": distribution.summary(),
        "log": log_status(),
    }
