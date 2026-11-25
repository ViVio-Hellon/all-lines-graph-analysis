"""ダッシュボード構成の保存(**アプリ専用の SQLite**。共有の日報データとは別のファイル)。

    %LOCALAPPDATA%\\AllLinesGraph\\data\\dashboards.sqlite3
      dashboards(id, name, config, created_at, updated_at, revision)

config は JSON の文字列で、共通条件・グラフの位置とサイズ・グラフごとの設定を
まるごと持ちます(`normalize` で形をそろえてから保存)。
**上書き保存は revision を見る** ── 別の窓で先に保存されていたら上書きせずに知らせる。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from . import app_config, metrics

FILE_NAME = "dashboards.sqlite3"
SCHEMA_VERSION = 1
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    config TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class DashError(Exception):
    def __init__(self, message: str, reason: str = "bad_input") -> None:
        super().__init__(message)
        self.reason = reason


def path() -> Path:
    return app_config.local_dir("data") / FILE_NAME


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    with _lock:
        con = sqlite3.connect(path(), timeout=10)
        try:
            con.row_factory = sqlite3.Row
            con.executescript(SCHEMA)
            con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema', ?)", (str(SCHEMA_VERSION),))
            yield con
            con.commit()
        finally:
            con.close()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------
# 形をそろえる
# ----------------------------------------------------------------------
GRID_COLUMNS = 12


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))


def _lines(value: Any) -> list[str]:
    return [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []


def _period(value: Any) -> dict:
    v = value if isinstance(value, dict) else {}
    preset = str(v.get("preset") or "this_month")
    return {"preset": preset, "start": str(v.get("start") or ""), "end": str(v.get("end") or "")}


def normalize(config: Any) -> dict:
    """保存する形(知らない鍵は捨てる・範囲の外は丸める)。"""
    c = config if isinstance(config, dict) else {}
    common = c.get("common") if isinstance(c.get("common"), dict) else {}
    out_common = {
        "all_lines": bool(common.get("all_lines", True)),
        "lines": _lines(common.get("lines")),
        "period": _period(common.get("period")),
        "grain": common.get("grain") if common.get("grain") in metrics.GRAINS else "day",
        "shift": str(common.get("shift") or ""),
        # 1ラインずつ切り替えて見る(ラインを指定したカードは切り替わらない)
        "switch": bool(common.get("switch", False)),
        "current": str(common.get("current") or ""),
        # 自動で読み直す(集計CSVが書き足されたら、開いたままのグラフにも出す)
        "auto_refresh": bool(common.get("auto_refresh", True)),
    }
    charts = []
    for raw in c.get("charts") or []:
        if not isinstance(raw, dict):
            continue
        metric = raw.get("metric") if raw.get("metric") in metrics.BY_KEY else "weight"
        chart = raw.get("chart") if raw.get("chart") in metrics.CHARTS else "bar"
        if metrics.BY_KEY[metric].charts().get(chart):
            chart = "bar"
        own = raw.get("own") if isinstance(raw.get("own"), dict) else {}
        charts.append({
            "id": str(raw.get("id") or f"g{len(charts) + 1}")[:40],
            "title": str(raw.get("title") or "")[:80],
            "metric": metric,
            "chart": chart,
            "x": _int(raw.get("x"), 0, 0, GRID_COLUMNS - 1),
            "y": _int(raw.get("y"), 0, 0, 1000),
            "w": _int(raw.get("w"), 6, 2, GRID_COLUMNS),
            "h": _int(raw.get("h"), 4, 2, 20),
            # 個別に決めたものだけ入る(無ければ共通条件に従う)
            "own": {
                **({"lines": _lines(own.get("lines"))} if "lines" in own else {}),
                **({"period": _period(own.get("period"))} if "period" in own else {}),
                **({"grain": own["grain"]} if own.get("grain") in metrics.GRAINS else {}),
                **({"shift": str(own.get("shift") or "")} if "shift" in own else {}),
            },
            "combo": {
                "bars": "total" if ((raw.get("combo") or {}).get("bars") == "total") else "stacked",
                "line": (raw.get("combo") or {}).get("line") if (raw.get("combo") or {}).get("line") in ("cumulative", "metric", "none") else "cumulative",
                "metric2": (raw.get("combo") or {}).get("metric2") if (raw.get("combo") or {}).get("metric2") in metrics.BY_KEY else "rate",
                "target": bool((raw.get("combo") or {}).get("target", True)),
            },
            "style": {
                "color": str((raw.get("style") or {}).get("color") or "")[:20],
                "legend": bool((raw.get("style") or {}).get("legend", True)),
                "labels": bool((raw.get("style") or {}).get("labels", False)),
                "same_scale": bool((raw.get("style") or {}).get("same_scale", True)),
                "y_min": (raw.get("style") or {}).get("y_min") if isinstance((raw.get("style") or {}).get("y_min"), (int, float)) else None,
                "y_max": (raw.get("style") or {}).get("y_max") if isinstance((raw.get("style") or {}).get("y_max"), (int, float)) else None,
            },
        })
    return {"version": 1, "common": out_common, "charts": charts[:60]}


def _name(name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        raise DashError("ダッシュボードの名前を入れてください。")
    if len(text) > 60:
        raise DashError("名前は60文字までにしてください。")
    return text


def _row(row: sqlite3.Row, with_config: bool = True) -> dict:
    out = {"id": row["id"], "name": row["name"], "created_at": row["created_at"],
           "updated_at": row["updated_at"], "revision": row["revision"]}
    if with_config:
        out["config"] = normalize(json.loads(row["config"]))
        out["charts"] = len(out["config"]["charts"])
    else:
        try:
            out["charts"] = len(json.loads(row["config"]).get("charts") or [])
        except ValueError:
            out["charts"] = 0
    return out


# ----------------------------------------------------------------------
# 操作
# ----------------------------------------------------------------------
def list_all(query: str = "") -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM dashboards ORDER BY updated_at DESC, id DESC").fetchall()
    out = [_row(r, with_config=False) for r in rows]
    return [r for r in out if query.strip().lower() in r["name"].lower()] if query.strip() else out


def get(dash_id: int) -> dict:
    with _db() as con:
        row = con.execute("SELECT * FROM dashboards WHERE id = ?", (dash_id,)).fetchone()
    if row is None:
        raise DashError("そのダッシュボードはありません(消された可能性があります)。", "not_found")
    return _row(row)


def create(name: Any, config: Any) -> dict:
    name = _name(name)
    now = _now()
    try:
        with _db() as con:
            cur = con.execute("INSERT INTO dashboards(name, config, created_at, updated_at) VALUES(?,?,?,?)",
                              (name, json.dumps(normalize(config), ensure_ascii=False), now, now))
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise DashError(f"「{name}」という名前はもうあります。別の名前にするか、上書き保存してください。",
                        "duplicate_name") from None
    return get(int(new_id))


def save(dash_id: int, config: Any, revision: Optional[int] = None, name: Any = None) -> dict:
    """上書き保存。**revision が違えば保存しない**(別の窓で先に保存されている)。"""
    current = get(dash_id)
    if revision is not None and int(revision) != current["revision"]:
        raise DashError(f"「{current['name']}」は {current['updated_at']} に別の画面で保存されています。"
                        "読み直してからもう一度保存するか、「別名で保存」してください。", "conflict")
    new_name = _name(name) if name is not None else current["name"]
    try:
        with _db() as con:
            con.execute("UPDATE dashboards SET name=?, config=?, updated_at=?, revision=revision+1 WHERE id=?",
                        (new_name, json.dumps(normalize(config), ensure_ascii=False), _now(), dash_id))
    except sqlite3.IntegrityError:
        raise DashError(f"「{new_name}」という名前はもうあります。", "duplicate_name") from None
    return get(dash_id)


def duplicate(dash_id: int, name: Any = None) -> dict:
    src = get(dash_id)
    base = str(name).strip() if name else f"{src['name']} のコピー"
    taken = {d["name"] for d in list_all()}
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base} ({n})"
        n += 1
    return create(candidate, src["config"])


def delete(dash_id: int) -> None:
    get(dash_id)
    with _db() as con:
        con.execute("DELETE FROM dashboards WHERE id = ?", (dash_id,))


def last_opened() -> Optional[int]:
    with _db() as con:
        row = con.execute("SELECT value FROM meta WHERE key='last_opened'").fetchone()
    try:
        return int(row["value"]) if row else None
    except ValueError:
        return None


def set_last_opened(dash_id: Optional[int]) -> None:
    with _db() as con:
        if dash_id is None:
            con.execute("DELETE FROM meta WHERE key='last_opened'")
        else:
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_opened', ?)", (str(dash_id),))
