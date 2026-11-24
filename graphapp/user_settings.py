"""この端末の設定ファイル(`runtime\\user_config.json`)を読み書きする所。

all-tools の `user_settings` と同じ約束:

* **読めないのを「無い」と取り違えない。** 開けない・壊れているときは
  `SettingsUnreadable` を上げる(`load_checked`)。取り違えると、配布設定の
  読み込みがこの端末で決めた値を全部上書きしてしまう。
* **書くときは丸ごと作ってから入れ替える**(途中で落ちても半分の JSON を残さない)。
* 値に None / 空文字を渡すと、その鍵を消す(= 既定に戻す)。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from . import app_config

FILE_NAME = "user_config.json"

_lock = threading.RLock()
_problem: dict[str, str] = {"text": ""}


class SettingsUnreadable(Exception):
    """設定ファイルはあるのに読めない(ロック中・権限・壊れている)。"""


def path() -> Path:
    return app_config.local_dir("runtime") / FILE_NAME


def load_checked() -> dict[str, Any]:
    """中身。無ければ空。**読めなければ `SettingsUnreadable`。**"""
    target = path()
    with _lock:
        try:
            text = target.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise SettingsUnreadable(f"{target} を開けません: {exc}") from exc
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise SettingsUnreadable(f"{target} が壊れています: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsUnreadable(f"{target} の形が違います(中身が {{ }} ではありません)")
    return data


def load() -> dict[str, Any]:
    """中身。読めなければ空(画面を出すとき用。**判断には `load_checked` を使う**)。"""
    try:
        return load_checked()
    except SettingsUnreadable as exc:
        _problem["text"] = str(exc)
        return {}


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def text(key: str) -> str:
    """文字の設定。前後の空白と引用符を落とす。無ければ空。"""
    value = get(key)
    return value.strip().strip('"').strip() if isinstance(value, str) else ""


def save_many(values: dict[str, Any]) -> bool:
    """まとめて書く。**読めない設定ファイルには書かない**(他の値を消さない)。"""
    with _lock:
        try:
            current = load_checked()
        except SettingsUnreadable as exc:
            _problem["text"] = str(exc)
            return False
        for key, value in values.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                current.pop(key, None)
            else:
                current[key] = value
        target = path()
        temp = target.with_name(target.name + ".tmp")
        try:
            temp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            os.replace(temp, target)
        except OSError as exc:
            _problem["text"] = f"{target} に書けません: {exc}"
            try:
                temp.unlink()
            except OSError:
                pass
            return False
        _problem["text"] = ""
        return True


def save(key: str, value: Any) -> bool:
    return save_many({key: value})


def last_problem() -> str:
    return _problem["text"]


def is_set(value: Optional[Any]) -> bool:
    if value is None:
        return False
    return not (isinstance(value, str) and not value.strip())
