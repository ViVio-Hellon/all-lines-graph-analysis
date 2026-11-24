"""書き出すファイル名に使えない字を除く(all-tools `file_names.py` と同じ)。"""
from __future__ import annotations

from typing import Optional

UNSAFE_CHARS = '\\/:*?"<>|'


def safe_name(text: Optional[str], default: str = "Unknown", limit: Optional[int] = None) -> str:
    cleaned = "".join(ch for ch in (text or "") if ch not in UNSAFE_CHARS and ch >= " ").strip()
    if limit is not None:
        cleaned = cleaned[:limit]
    return cleaned or default
