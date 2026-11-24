"""管理者パスワード(all-tools の `admin_password.py` を移植)。

押し間違いを防ぐための関門です(本来の意味での権限管理ではない)。
平文では持たず PBKDF2 で撹拌して `user_config.json` に入れます。
変えていない端末は既定(all-tools と同じ合言葉)で通ります。
**設定ファイルを読めないときは通しません**(変えた端末が既定で通ってしまうため)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional

from . import user_settings
from .config import DEFAULT_ADMIN_PASSWORD, KEY_ADMIN_PASSWORD

SCHEME = "pbkdf2"
ITERATIONS = 200_000
SALT_BYTES = 16
MIN_LENGTH = 4

REFUSE_WRONG = "wrong_password"
REFUSE_TOO_SHORT = "too_short"
REFUSE_MISMATCH = "mismatch"
REFUSE_UNREADABLE = "settings_unreadable"
REFUSE_WRITE_FAILED = "write_failed"


@dataclass
class Result:
    ok: bool
    message: str = ""
    reason: str = ""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _encode(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{SCHEME}${iterations}${_b64(salt)}${_b64(digest)}"


def _matches(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, _ = stored.split("$")
        if scheme != SCHEME:
            return False
        expected = _encode(password, base64.b64decode(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected.encode("utf-8"), stored.encode("utf-8"))


def hashed(password: str) -> str:
    return _encode(password, os.urandom(SALT_BYTES))


def _stored() -> Optional[str]:
    """撹拌した値。変えていなければ None。読めなければ `SettingsUnreadable`。"""
    value = user_settings.load_checked().get(KEY_ADMIN_PASSWORD)
    return value if isinstance(value, str) and value.strip() else None


def is_custom() -> bool:
    try:
        return _stored() is not None
    except user_settings.SettingsUnreadable:
        return False


def verify(password: str) -> bool:
    try:
        stored = _stored()
    except user_settings.SettingsUnreadable:
        return False
    if stored is None:
        return hmac.compare_digest((password or "").encode("utf-8"), DEFAULT_ADMIN_PASSWORD.encode("utf-8"))
    return _matches(password or "", stored)


def change(current: str, new: str, confirm: str) -> Result:
    try:
        _stored()
    except user_settings.SettingsUnreadable as exc:
        return Result(False, f"この端末の設定ファイルを読めないので変えません: {exc}",
                      REFUSE_UNREADABLE)
    if not verify(current):
        return Result(False, "いまのパスワードが違います。", REFUSE_WRONG)
    if len(new or "") < MIN_LENGTH:
        return Result(False, f"新しいパスワードは{MIN_LENGTH}文字以上にしてください。",
                      REFUSE_TOO_SHORT)
    if new != confirm:
        return Result(False, "確認用と一致しません。", REFUSE_MISMATCH)
    if not user_settings.save(KEY_ADMIN_PASSWORD, hashed(new)):
        return Result(False, "設定ファイルに書けませんでした: " + user_settings.last_problem(),
                      REFUSE_WRITE_FAILED)
    return Result(True, "管理者パスワードを変えました。")
