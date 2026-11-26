"""ライン速報を読む(all-tools `tools/nippou/nippou/services/flash_report.py` が書くファイル)

all-tools(日報管理ツール)は、日報を保存するたびに、そのラインの今の直・今日の枚数を
`<ライン速報の置き場所>\\<ライン>.json`(UTF-8)に書きます(1ラインに1つ・上書き)。

    {"line": "L-1", "date": "2026-11-26", "date_label": "2026年11月26日", "shift": "2直",
     "shift_count": 120.0, "shifts": {"1直": 140.0, "2直": 120.0}, "day_total": 260.0,
     "target": 140.0, "diff": 120.0, "updated_at": "2026-11-26T16:05:12"}

数え方は all-tools の集計と同じ(集計から除く作業者・テストの直は入らない)。ここでは**読むだけ**で、
計算し直さない。書きかけ(`.tmp`)は読まない。壊れたファイルは理由を出して飛ばす。

【古い速報を今日の数と取り違えない】ファイルの日付が今日でなければ「今日の速報はまだ」として出す
(前の日の数を今日の数に見せない)。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

#: 書いてから何分たったら「しばらく更新がない」と出すか
QUIET_MINUTES = 90


def _num(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def read_one(path: Path, today: date, now: datetime) -> dict:
    out: dict = {"file": str(path), "line": path.stem, "error": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("中身が { } ではありません")
    except (OSError, ValueError) as exc:
        out["error"] = f"読めません: {exc}"
        return out
    shifts = data.get("shifts") if isinstance(data.get("shifts"), dict) else {}
    out.update({
        "line": str(data.get("line") or path.stem),
        "date": str(data.get("date") or ""),
        "date_label": str(data.get("date_label") or ""),
        "shift": str(data.get("shift") or ""),
        "shift_count": _num(data.get("shift_count")),
        "shifts": {str(k): _num(v) for k, v in shifts.items()},
        "day_total": _num(data.get("day_total")),
        "target": _num(data.get("target")),
        "diff": _num(data.get("diff")),
        "updated_at": str(data.get("updated_at") or ""),
    })
    try:
        out["is_today"] = date.fromisoformat(out["date"]) == today
    except ValueError:
        out["is_today"] = False
    try:
        age = (now - datetime.fromisoformat(out["updated_at"])).total_seconds() / 60
        out["minutes_ago"] = max(0, int(age))
        out["quiet"] = age > QUIET_MINUTES
    except ValueError:
        out["minutes_ago"] = None
        out["quiet"] = False
    return out


def read_all(folder: Optional[Path], *, today: Optional[date] = None, now: Optional[datetime] = None) -> dict:
    """置き場所の `*.json` を全部。**例外にしない**(届かなければ理由を返す)。"""
    now = now or datetime.now()
    today = today or now.date()
    if folder is None:
        return {"folder": "", "items": [], "error": "ライン速報の置き場所を決めていません(設定の参照設定)",
                "read_at": now.isoformat(timespec="seconds")}
    try:
        files = sorted(p for p in Path(folder).glob("*.json") if p.is_file())
    except OSError as exc:
        return {"folder": str(folder), "items": [], "error": f"ライン速報の置き場所に届きません: {exc}",
                "read_at": now.isoformat(timespec="seconds")}
    if not Path(folder).is_dir():
        return {"folder": str(folder), "items": [], "error": f"ライン速報の置き場所がありません: {folder}",
                "read_at": now.isoformat(timespec="seconds")}
    return {"folder": str(folder), "items": [read_one(p, today, now) for p in files], "error": "",
            "read_at": now.isoformat(timespec="seconds")}
