"""配布設定 ── 1台で決めた設定を、配った先の端末でそのまま使う
(all-tools `tools/nippou/nippou/distribution.py` の必要部分を移植)

【なぜ要るのか】
設定(集計データの大本・共有の日報データ・ログの出力パス・管理者パスワード)は
端末ごとの `%LOCALAPPDATA%\\AllLinesGraph\\runtime\\user_config.json` に入ります。
**アプリのフォルダをコピーしても付いて行きません。** 配った先で1台ずつ打ち直すと
打ち間違えた端末が別のフォルダを読みます。

【流れ】
    1. 1台で起動して参照設定を決め、設定の「配布設定」で書き出す
    2. **起動用の Start.vbs / start.bat と同じフォルダ**に `配布設定\\` ができる
    3. フォルダごと配る
    4. 配った先は起動したとき `配布設定\\` を見つけて読み込む

    配布設定\\
      設定.json        置き場所・出力先・管理者パスワード(撹拌した値)
      はじめに読む.txt  何が入っているか・配った先で何が起きるか

【読み込むときの決まり】**その端末で決めた値は上書きしない。** 無い項目だけ埋める
(空の値は「無い」と数える)。

【配り直したとき】配布設定から読み込んだ値は `distribution_values` に覚えておき、
端末の値がそのまま(= この端末で直していない)なら、新しい配布設定の値で置き換える。
揃えたいときは設定画面の「配布設定を読み込み直す」(管理者パスワード)で上書き。

【読めないとき】この端末の設定ファイルを読めないときは、書き出しも読み込みもしない
(「既定のまま」「この端末に無い」と取り違えると、全部を上書きしてしまう)。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import admin_password, app_config, config, user_settings
from .logging_setup import get_logger, note

log = get_logger("distribution")

DIR_NAME = "配布設定"
#: 保存したダッシュボード(名前と構成)。設定.json とは別のファイル
DASH_FILE = "ダッシュボード.json"
ITEM_DASHBOARDS = "dashboards"
#: 配布設定から取り込んだダッシュボードの指紋({名前: 指紋})。この端末で直したかを見分ける
KEY_DASH_FROM = "distribution_dashboards"
SETTINGS_NAME = "設定.json"
README_NAME = "はじめに読む.txt"
LAUNCHERS: tuple[str, ...] = ("Start.vbs", "start.bat")
FORMAT = 1
#: 何のアプリの配布設定か(all-tools の配布設定と取り違えない)
APP_KEY = "app"

KEY_APPLIED = "distribution_applied"
KEY_FROM_DIST = "distribution_values"
ENV_DIST_DIR = "ALG_DIST_DIR"

REFUSE_NEED_PASSWORD = "need_password"
REFUSE_BAD_INPUT = "bad_input"
REFUSE_FAILED = "failed"
REFUSE_NOTHING = "nothing"
REFUSE_UNREADABLE = "settings_unreadable"


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    default: bool = True


#: 入れられるもの。**並びは参照設定の面と同じ**(読みに行く先 → 書き出す先 → 鍵)
ITEMS: tuple[Item, ...] = (
    Item(config.KEY_AGG_ROOT, "集計データの大本"),
    Item(config.KEY_AGG_ROOT2, "集計データの大本(2つ目)"),
    Item(config.KEY_ACCESS_DIR, "共有の日報データの置き場所"),
    Item(config.KEY_ACCESS_DB_FILE, "共有の日報データのファイル名"),
    Item(config.KEY_LINE_TARGET_FILE, "ライン毎目標のCSV"),
    Item(config.KEY_FLASH_DIR, "ライン速報の置き場所"),
    # 共有のフォルダを配れば、どの端末のエラーも1か所で見られる
    Item(config.KEY_LOG_DIR, "ログの出力パス"),
    Item(config.KEY_EXPORT_DIR, "CSV・画像の書き出し先"),
    Item(config.KEY_ADMIN_PASSWORD, "管理者パスワード"),
    # 組んだダッシュボード(この端末に保存したもの全部)。配った先で同じ画面を使える
    Item(ITEM_DASHBOARDS, "ダッシュボード(この端末に保存したもの全部)"),
)
ITEM_BY_KEY = {item.key: item for item in ITEMS}
SETTING_KEYS = frozenset(k for k in ITEM_BY_KEY if k != ITEM_DASHBOARDS)


# ----------------------------------------------------------------------
# 置き場所
# ----------------------------------------------------------------------
def folder() -> Path:
    """`配布設定\\`。**起動用のファイルと同じ階層。** 検証用に ALG_DIST_DIR で差し替え。"""
    override = os.environ.get(ENV_DIST_DIR, "").strip()
    return Path(override) if override else app_config.APP_ROOT / DIR_NAME


def settings_path(base: Optional[Path] = None) -> Path:
    return (base or folder()) / SETTINGS_NAME


# ----------------------------------------------------------------------
# 読む
# ----------------------------------------------------------------------
@dataclass
class Bundle:
    settings: dict[str, Any]
    dashboards: list[dict] = field(default_factory=list)
    created_at: str = ""
    created_on: str = ""
    version: str = ""
    file: Optional[Path] = None


def _clean(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in SETTING_KEYS and user_settings.is_set(v)}


def _read() -> tuple[Optional[Bundle], str]:
    """(中身, 読めなかった理由)。無ければ (None, "")。例外にしない。"""
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, ""
    except (OSError, ValueError) as exc:
        return None, f"配布設定を読めません({path}): {exc}"
    if not isinstance(data, dict):
        return None, f"配布設定の形が違います({path})"
    if data.get("format") != FORMAT:
        return None, f"配布設定の版が違います({path}: format={data.get('format')})"
    if data.get(APP_KEY) not in (None, app_config.APP_ID):
        return None, (f"別のアプリの配布設定です({path}: {data.get(APP_KEY)})。"
                      f"{app_config.DISPLAY_NAME}の設定画面で書き出し直してください")
    dashboards: list[dict] = []
    try:
        raw = json.loads((path.parent / DASH_FILE).read_text(encoding="utf-8-sig"))
        dashboards = [d for d in (raw.get("dashboards") if isinstance(raw, dict) else []) or []
                      if isinstance(d, dict) and str(d.get("name") or "").strip() and isinstance(d.get("config"), dict)]
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        return None, f"配布設定のダッシュボードを読めません({path.parent / DASH_FILE}): {exc}"
    return Bundle(settings=_clean(data.get("settings")), dashboards=dashboards,
                  created_at=str(data.get("created_at", "")),
                  created_on=str(data.get("created_on", "")),
                  version=str(data.get("version", "")), file=path), ""


def _show(key: str, value: Any) -> str:
    if key == config.KEY_ADMIN_PASSWORD:
        return "(撹拌した値。伏せます)"
    return str(value)


def contents(bundle: Bundle) -> list[dict[str, str]]:
    rows = [{"key": item.key, "label": item.label, "value": _show(item.key, bundle.settings[item.key])}
            for item in ITEMS if item.key in bundle.settings]
    if bundle.dashboards:
        rows.append({"key": ITEM_DASHBOARDS, "label": "ダッシュボード",
                     "value": f"{len(bundle.dashboards)}件(" + "・".join(d["name"] for d in bundle.dashboards) + ")"})
    return rows


def _local_dashboards() -> list[dict]:
    from . import dash_store
    try:
        return dash_store.list_all()
    except Exception:  # 読めなくても配布設定の画面は出す
        return []


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def summary() -> dict[str, Any]:
    """設定画面に出す、いまの配布設定と、この端末での読み込みの様子。"""
    bundle, error = _read()
    current = user_settings.load()
    came = _from_distribution(current)
    applied = [item.label for item in ITEMS
               if item.key in came and current.get(item.key) == came[item.key]]
    kept = []
    if bundle:
        for item in ITEMS:
            if item.key in bundle.settings and item.key not in came:
                mine = current.get(item.key)
                if user_settings.is_set(mine) and mine != bundle.settings[item.key]:
                    kept.append(item.label)
    stamp = current.get(KEY_APPLIED)
    items = []
    for item in ITEMS:
        if item.key == ITEM_DASHBOARDS:
            local = _local_dashboards()
            items.append({"key": item.key, "label": item.label, "default": item.default,
                          "value": (f"{len(local)}件(" + "・".join(d["name"] for d in local) + ")") if local else ""})
            continue
        value = current.get(item.key)
        items.append({"key": item.key, "label": item.label, "default": item.default,
                      "value": _show(item.key, value) if user_settings.is_set(value) else ""})
    dash_came = current.get(KEY_DASH_FROM) if isinstance(current.get(KEY_DASH_FROM), dict) else {}
    if dash_came:
        applied.append(f"ダッシュボード{len(dash_came)}件(" + "・".join(dash_came) + ")")
    return {
        "path": str(folder()),
        "launchers": list(LAUNCHERS),
        "exists": bundle is not None,
        "error": error,
        "created_at": bundle.created_at if bundle else "",
        "created_on": bundle.created_on if bundle else "",
        "version": bundle.version if bundle else "",
        "contents": contents(bundle) if bundle else [],
        "applied_at": stamp.get("at", "") if isinstance(stamp, dict) else "",
        "reading": {"applied": applied, "kept": kept},
        "items": items,
        "warnings": _warnings(current),
    }


def _warnings(current: dict[str, Any]) -> list[dict[str, str]]:
    """このまま配ると困ること。**書き出す前に**読めるように。"""
    out: list[dict[str, str]] = []
    agg = current.get(config.KEY_AGG_ROOT)
    if not user_settings.is_set(agg):
        out.append({"level": "alert", "text": "集計データの大本が既定(この端末の日報管理ツールの出力先)のままです。"
                    "配った先の端末も自分の中を見ます ── 共有のフォルダを指してから書き出してください。"})
    elif config.is_relative_setting(str(agg)):
        out.append({"level": "warn", "text": "集計データの大本が相対の道です。配った先ではその端末のアプリのフォルダから"
                    "たどります(同じ場所に置かないと見えません)。"})
    for key, label in ((config.KEY_AGG_ROOT, "集計データの大本"), (config.KEY_LOG_DIR, "ログの出力パス"),
                       (config.KEY_ACCESS_DIR, "共有の日報データの置き場所")):
        text = current.get(key)
        if isinstance(text, str) and len(text) > 2 and text[1] == ":" and text[0].upper() == "C":
            out.append({"level": "warn", "text": f"{label}が C: ドライブ({text})です。配った先でも"
                        "その端末の C: を見ます(共有にはなりません)。"})
    if not user_settings.is_set(current.get(config.KEY_LOG_DIR)):
        out.append({"level": "info", "text": "ログの出力パスが既定(各端末の中)です。共有のフォルダにすると、"
                    "どの端末のエラーも1か所で見られます。"})
    return out


# ----------------------------------------------------------------------
# 書き出す・消す
# ----------------------------------------------------------------------
@dataclass
class Result:
    ok: bool = True
    message: str = ""
    reason: str = ""
    applied: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return vars(self)


def _refusal(password: str, admin: bool, what: str) -> Optional[Result]:
    if admin or admin_password.verify(password or ""):
        return None
    return Result(False, f"{what}には管理者パスワードが要ります(違っていたか、空でした)。",
                  REFUSE_NEED_PASSWORD)


def export(password: str, items: list[str], *, admin: bool = False) -> Result:
    """**この端末のいまの設定**を `配布設定\\` に書き出す(前の中身は置き換える)。

    この端末で一度も変えていない項目は入れない(配った先も同じ既定で動く)。
    """
    refused = _refusal(password, admin, "配布設定を書き出す")
    if refused is not None:
        return refused
    unknown = [k for k in items if k not in ITEM_BY_KEY]
    if unknown:
        return Result(False, "知らない項目です: " + ", ".join(unknown), REFUSE_BAD_INPUT)
    if not items:
        return Result(False, "入れる項目を1つ以上選んでください。", REFUSE_BAD_INPUT)
    try:
        current = user_settings.load_checked()
    except user_settings.SettingsUnreadable as exc:
        return Result(False, f"この端末の設定ファイルを読めないので、書き出しませんでした: {exc}",
                      REFUSE_UNREADABLE)
    settings: dict[str, Any] = {}
    defaults: list[str] = []
    for key in items:
        if key == ITEM_DASHBOARDS:
            continue
        value = current.get(key)
        if user_settings.is_set(value):
            settings[key] = value
        else:
            defaults.append(ITEM_BY_KEY[key].label)
    dashboards: list[dict] = []
    if ITEM_DASHBOARDS in items:
        from . import dash_store
        try:
            dashboards = dash_store.export_all()
        except Exception as exc:
            return Result(False, f"ダッシュボードを読めないので、書き出しませんでした: {exc}", REFUSE_FAILED)
        if not dashboards:
            defaults.append("ダッシュボード(保存したものがありません)")
    if not settings and not dashboards:
        return Result(False, "書き出せる設定がありません(" + "・".join(defaults)
                      + " はこの端末で変えていないため既定のままです)。", REFUSE_NOTHING)

    target = folder()
    staging = target.with_name(target.name + ".作成中")
    meta = {"format": FORMAT, APP_KEY: app_config.APP_ID, "created_at": _now(),
            "created_on": platform.node(), "version": app_config.VERSION,
            "labels": {k: ITEM_BY_KEY[k].label for k in settings}, "settings": settings}
    # **作ってから入れ替える。** 途中で失敗して半分だけ新しい配布設定を残さない
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        settings_path(staging).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
        if dashboards:
            (staging / DASH_FILE).write_text(json.dumps({"format": FORMAT, APP_KEY: app_config.APP_ID,
                                                         "dashboards": dashboards}, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        (staging / README_NAME).write_text(_readme(meta, dashboards), encoding="utf-8-sig")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return Result(False, f"{target} に書けませんでした: {exc}", REFUSE_FAILED)
    names = [ITEM_BY_KEY[k].label for k in settings]
    if dashboards:
        names.append(f"ダッシュボード{len(dashboards)}件")
    message = (f"配布設定を書き出しました({len(names)}項目)。起動用の Start.vbs と同じフォルダの"
               f"「{target.name}」に入っています({target})。フォルダごと配ってください。")
    if defaults:
        message += " 既定のままなので入れていないもの: " + "・".join(defaults) + "。"
    note("配布設定を書き出しました: " + "・".join(names), label="配布設定を書き出した")
    return Result(True, message, applied=names)


def _readme(meta: dict[str, Any], dashboards: Optional[list[dict]] = None) -> str:
    lines = [f"{app_config.DISPLAY_NAME} 配布設定", "",
             f"作成: {meta['created_at']}({meta['created_on']}) 版 {meta['version']}", "",
             "このフォルダに入っているもの"]
    for row in contents(Bundle(settings=meta["settings"], dashboards=dashboards or [])):
        lines.append(f"  {row['label']}: {row['value']}")
    lines += ["", "置き場所",
              "  起動用の Start.vbs / start.bat と同じフォルダに置いたままにしてください。", "",
              "配った先で起きること",
              "  起動したときにこのフォルダを読み込みます。",
              "  その端末で決めてある設定は読み込みません(上書きしない)。",
              "  揃えたいときは、設定の「配布設定」→「配布設定を読み込み直す」。", "",
              "集計データの大本について",
              "  決めるのは大本のフォルダだけです。<ライン>\\集計\\<yyyy.mm>\\<dd> はアプリがたどります。", ""]
    return "\n".join(lines)


def remove(password: str, *, admin: bool = False) -> Result:
    refused = _refusal(password, admin, "配布設定を消す")
    if refused is not None:
        return refused
    target = folder()
    try:
        if target.exists():
            shutil.rmtree(target)
    except OSError as exc:
        return Result(False, f"消せませんでした: {exc}", REFUSE_FAILED)
    note("配布設定を消しました", label="配布設定を消した")
    return Result(True, "配布設定を消しました。この端末の設定はそのままです。")


# ----------------------------------------------------------------------
# 読み込む(配られた側)
# ----------------------------------------------------------------------
def _from_distribution(current: dict[str, Any]) -> dict[str, Any]:
    found = current.get(KEY_FROM_DIST)
    return dict(found) if isinstance(found, dict) else {}


def _apply(bundle: Bundle, *, overwrite: bool) -> Result:
    result = Result()
    try:
        current = user_settings.load_checked()
    except user_settings.SettingsUnreadable as exc:
        log.warning("配布設定を読み込みませんでした(この端末の設定ファイルを読めない): %s", exc)
        result.ok = False
        result.error = (f"この端末の設定ファイルを読めなかったので、配布設定を読み込みませんでした"
                        f"(次の起動、または「配布設定を読み込み直す」でもう一度読みます): {exc}")
        return result
    came = _from_distribution(current)
    to_write: dict[str, Any] = {}
    for item in ITEMS:
        if item.key not in bundle.settings:
            continue
        new = bundle.settings[item.key]
        mine = current.get(item.key)
        decided_here = user_settings.is_set(mine) and not (item.key in came and came[item.key] == mine)
        if not overwrite and decided_here:
            if mine != new:
                result.kept.append(item.label)
            continue
        if mine == new:
            continue
        to_write[item.key] = new
        result.applied.append(item.label)
    _apply_dashboards(bundle, current, overwrite, result, to_write)
    final = {**current, **to_write}
    remembered = {k: v for k, v in came.items() if final.get(k) == v}
    remembered.update(to_write)
    if remembered != came:
        to_write[KEY_FROM_DIST] = remembered
    if result.applied:
        to_write[KEY_APPLIED] = {"at": _now(), "from": str(bundle.file or "")}
    if to_write and not user_settings.save_many(to_write):
        result.ok = False
        result.error = "配布設定を、この端末の設定ファイルに書けませんでした(" + user_settings.last_problem() + ")"
        result.applied = []
    return result


def _apply_dashboards(bundle: Bundle, current: dict[str, Any], overwrite: bool, result: Result,
                      to_write: dict[str, Any]) -> None:
    """配られたダッシュボードを取り込む。決まりは設定と同じ:

        この端末に同じ名前が無い                  → 取り込む
        ある・配布設定から取り込んだまま直していない → 配り直した中身に置き換える
        ある・この端末で作った/直した             → そのまま(読み込み直す ときだけ上書き)
    この端末にだけあるダッシュボードは消さない。
    """
    if not bundle.dashboards:
        return
    from . import dash_store

    came = current.get(KEY_DASH_FROM) if isinstance(current.get(KEY_DASH_FROM), dict) else {}
    remembered = dict(came)
    for d in bundle.dashboards:
        name = str(d["name"]).strip()
        new_fp = dash_store.fingerprint(d["config"])
        try:
            local = dash_store.find_by_name(name)
            if local is None:
                dash_store.create(name, d["config"])
                result.applied.append(f"ダッシュボード「{name}」")
            else:
                local_fp = dash_store.fingerprint(local["config"])
                if local_fp == new_fp:
                    pass                                   # もう同じ
                elif overwrite or came.get(name) == local_fp:
                    dash_store.save(local["id"], d["config"])
                    result.applied.append(f"ダッシュボード「{name}」")
                else:
                    result.kept.append(f"ダッシュボード「{name}」")
                    remembered.pop(name, None)
                    continue
            remembered[name] = new_fp
        except Exception as exc:                      # 1つ取り込めなくても、ほかは続ける
            log.warning("配布設定のダッシュボード「%s」を取り込めませんでした: %s", name, exc)
            result.kept.append(f"ダッシュボード「{name}」(取り込めませんでした: {exc})")
    if remembered != came:
        to_write[KEY_DASH_FROM] = remembered


def apply_on_start() -> Result:
    """起動時に呼ぶ。`配布設定\\` があれば、**この端末で決めていないものだけ**読む。"""
    bundle, error = _read()
    if error:
        log.warning(error)
        return Result(True, "", error=error)
    if bundle is None:
        return Result(True, "")
    result = _apply(bundle, overwrite=False)
    if result.applied:
        note("配布設定を読み込みました: " + "・".join(result.applied)
             + (f"(この端末で決めてあったので読まなかったもの: {'・'.join(result.kept)})" if result.kept else ""),
             label="配布設定を読み込んだ")
        result.message = "配布設定を読み込みました"
    return result


def reapply(password: str, *, admin: bool = False) -> Result:
    """設定画面から。**この端末で決めた値も上書きして**読み込み直す。"""
    refused = _refusal(password, admin, "配布設定を読み込み直す")
    if refused is not None:
        return refused
    bundle, error = _read()
    if error:
        return Result(False, error, REFUSE_BAD_INPUT)
    if bundle is None:
        return Result(False, "配布設定が置かれていません。", REFUSE_BAD_INPUT)
    result = _apply(bundle, overwrite=True)
    if result.error:
        return Result(False, result.error, REFUSE_FAILED)
    if result.applied:
        result.message = f"配布設定を読み込みました({len(result.applied)}項目: " + "・".join(result.applied) + ")"
        note(result.message, label="配布設定を読み込み直した")
    else:
        result.message = "この端末はもう配布設定のとおりです。"
    return result


def describe() -> str:
    """起動のたびにログへ残す1行。"""
    bundle, error = _read()
    if error:
        return error
    if bundle is None:
        return f"配布設定はありません({folder()})"
    return f"配布設定を読みます: {bundle.file}(設定 {len(bundle.settings)}件)"
