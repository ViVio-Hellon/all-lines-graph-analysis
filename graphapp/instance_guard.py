"""ブラウザ版とデスクトップ版を同時に動かさない(どちらを後から開いても止まる)。

**Rust 側(`src-tauri/src/instance.rs`)と同じ名前・同じ手順**で錠を扱う。
食い違うと止め損ねるので、名前は試験で突き合わせている(`tests/test_desktop.py`)。
作りは all-tools の `instance.rs` / 点検表と同じ。

【錠は OS の名前付きの錠にする(ファイルにしない)】
ラインPCの Python は Microsoft Store 版のことがあり、`%LOCALAPPDATA%` に書いたファイルは
Python 専用の場所へ振り替えられ、exe からは見えない。名前付きミューテックスは振り替えられない。
Windows 以外(開発機・試験)では、一時フォルダのファイルの錠(flock)で同じことをする。

    1. 自分の種類の目印を作る(browser / desktop)
    2. 本体の錠を作る
       ├─ 作れた                       → 起動してよい(終わるまで握る)
       └─ すでにあった
          ├─ 相手の目印がある         → 相手の版が動いている。止まる
          └─ 無い                     → 同じ版が動いている(前に出して止まる)
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import app_config

BROWSER = "browser"
DESKTOP = "desktop"

ERROR_ALREADY_EXISTS = 183


def base_name(app_id: str = app_config.APP_ID) -> str:
    """錠の名前の頭(Rust の `instance::base_name` と同じ規則)。"""
    app_id = app_id.strip() or "all-lines-graph-analysis"
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in app_id)


@dataclass(frozen=True)
class Names:
    instance: str
    desktop: str
    browser: str


def names(app_id: str = app_config.APP_ID) -> Names:
    base = base_name(app_id)
    return Names(instance=f"{base}.instance", desktop=f"{base}.desktop", browser=f"{base}.browser")


# ----------------------------------------------------------------------
# 錠そのもの(Windows: 名前付きミューテックス / ほか: 一時フォルダのファイルの錠)
# ----------------------------------------------------------------------
class _Lock:
    def __init__(self, handle) -> None:
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
        else:
            try:
                self.handle.close()
            except OSError:
                pass
        self.handle = None


def lock_dir() -> Path:
    """Windows 以外の錠の置き場所(Rust の `std::env::temp_dir()` と同じ所)。"""
    override = os.environ.get("ALG_LOCK_DIR", "").strip()
    return Path(override) if override else Path(tempfile.gettempdir())


def _create(name: str) -> tuple[Optional[_Lock], bool]:
    """(錠, すでにあったか)。すでにあったときは錠を返さない。"""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        handle = k32.CreateMutexW(None, False, f"Local\\{name}")
        existed = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        if not handle:
            return None, True
        if existed:
            k32.CloseHandle(handle)
            return None, True
        return _Lock(handle), False
    import fcntl
    path = lock_dir() / f"{name}.lock"
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None, True
    return _Lock(handle), False


def _exists(name: str) -> bool:
    """その錠を誰かが握っているか(握らずに確かめる)。"""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = wintypes.HANDLE
        k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        handle = k32.OpenMutexW(0x00100000, False, f"Local\\{name}")   # SYNCHRONIZE
        if handle:
            k32.CloseHandle(handle)
            return True
        return False
    lock, existed = _create(name)
    if lock is not None:
        lock.release()
    return existed


# ----------------------------------------------------------------------
# 手順
# ----------------------------------------------------------------------
@dataclass
class Guard:
    ok: bool
    other: str = ""            # 動いていた相手(browser / desktop)
    message: str = ""
    _locks: tuple = ()

    def release(self) -> None:
        for lock in self._locks:
            lock.release()
        self._locks = ()


def acquire(kind: str, app_id: str = app_config.APP_ID) -> Guard:
    """起動してよいか。よければ錠を握ったまま返す(終わるまで `release` しない)。"""
    n = names(app_id)
    mine, other = (n.browser, n.desktop) if kind == BROWSER else (n.desktop, n.browser)
    marker, _ = _create(mine)
    instance, existed = _create(n.instance)
    if not existed and instance is not None:
        return Guard(True, _locks=tuple(l for l in (instance, marker) if l is not None))
    if marker is not None:
        marker.release()
    if _exists(other):
        who = DESKTOP if kind == BROWSER else BROWSER
        text = ("デスクトップ版(全ライン グラフ分析.exe)が動いています。そちらの窓を使ってください。"
                if who == DESKTOP else
                "ブラウザ版(Start.vbs / start.bat)が動いています。ブラウザ版を終えてから開いてください。")
        return Guard(False, other=who, message=text)
    return Guard(False, other=kind, message="すでに起動しています。")


def show_message(text: str) -> None:
    """コンソールの無い起動(pythonw)でも読めるように、Windows では窓で出す。"""
    print(text, file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, app_config.DISPLAY_NAME, 0x40)
        except Exception:  # 窓が出せなくても止まるだけ
            pass
