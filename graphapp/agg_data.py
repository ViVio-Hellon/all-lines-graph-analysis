r"""集計CSVの中身を読む所(**読むだけ。書かない・計算し直さない**)。

all-tools(日報管理ツール)が1日ごとに書き出す3本を読みます
(`tools/nippou/nippou/reporting/csv_export.py`)。

    集計_<日>_<ライン>.csv      直ごとの合計(FIELDNAMES)
        日付, ライン, 直, 合計枚数, 合計重量(t), 作業時間合計(分), 稼働時間合計(分),
        操業時間(分), 管理ロス設備停止(分), 段取り・突発停止(分), ハンドリング停止(分),
        その他(分), 停止合計(分), 稼働率(%), 生産性(t/h)
    停止内訳_<日>_<ライン>.csv  直ごと・分類ごと・記号ごとの停止(STOP_FIELDNAMES)
        区分 =「直の合計」の行だけ使う(「1件ずつ」はその内訳なので足すと二重になる)
    集計明細_<日>_<ライン>.csv  その日の明細行(DETAIL_FIELDNAMES)
        ロット数(ロット№のある行の数)と包数(梱包数量 梱包単位 包数)だけ使う

【欠損と 0 を分ける】
ファイルが無い日・欄が空の値は **None**(データなし)。0 と書いてあるものだけが 0 です。
「その他(分)」は all-tools v4.44.14 で足された欄なので、前の版のCSVには無く None になります。

【速さ】
共有のフォルダでは開くだけで時間が掛かるので、読んだ中身を(道, 大きさ, 更新時刻)で
覚えておき、変わっていなければ読み直しません。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from . import agg_store

#: 集計_ CSV の欄 → 属性
SUMMARY_COLUMNS: dict[str, str] = {
    "合計枚数": "sheets",
    "合計重量(t)": "weight_t",
    "作業時間合計(分)": "work_min",
    "稼働時間合計(分)": "operating_min",
    "操業時間(分)": "operational_min",
    "管理ロス設備停止(分)": "loss_min",
    "段取り・突発停止(分)": "sudden_min",
    "ハンドリング停止(分)": "handling_min",
    "その他(分)": "other_min",
    "停止合計(分)": "stop_min",
    "稼働率(%)": "rate_pct",
    "生産性(t/h)": "productivity",
}
STOP_TOTAL_KIND = "直の合計"
DETAIL_LOT = "ロット№"
DETAIL_PACKAGES = "梱包数量 梱包単位 包数"
#: 直の並び(all-tools `presenters/dashboard.SHIFT_STACK_ORDER`)
SHIFT_ORDER = ("1直", "2直", "3直", "日勤", "4直", "5直")


def number(text: Optional[str]) -> Optional[float]:
    """CSVの数。**空は None**(0 にしない)。"""
    if text is None:
        return None
    cleaned = str(text).strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


@dataclass
class ShiftRow:
    shift: str
    sheets: Optional[float] = None
    weight_t: Optional[float] = None
    work_min: Optional[float] = None
    operating_min: Optional[float] = None
    operational_min: Optional[float] = None
    loss_min: Optional[float] = None
    sudden_min: Optional[float] = None
    handling_min: Optional[float] = None
    other_min: Optional[float] = None
    stop_min: Optional[float] = None
    rate_pct: Optional[float] = None
    productivity: Optional[float] = None


@dataclass
class StopRow:
    shift: str
    kind: str          # 分類(管理ロス設備停止 など)
    code: str          # 記号
    name: str          # 内訳
    count: Optional[float]
    minutes: Optional[float]


@dataclass
class DayData:
    line: str
    day: date
    shifts: list[ShiftRow] = field(default_factory=list)
    stops: Optional[list[StopRow]] = None       # 停止内訳CSVが無ければ None
    lots: Optional[dict[str, float]] = None      # 直 → ロット数(明細CSVが無ければ None)
    packages: Optional[dict[str, float]] = None  # 直 → 包数
    files: dict[str, str] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 読んだものを覚えておく
# ----------------------------------------------------------------------
_cache: dict[str, tuple[tuple[int, int], list[dict[str, str]]]] = {}
_lock = threading.Lock()
_CACHE_MAX = 5000


def _rows(path: Path) -> list[dict[str, str]]:
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return []
    stamp = (st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    rows = agg_store.read_csv(path)
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = (stamp, rows)
    return rows


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _shift_key(name: str) -> tuple:
    return (SHIFT_ORDER.index(name) if name in SHIFT_ORDER else len(SHIFT_ORDER), name)


def _day(files: agg_store.DayFiles) -> DayData:
    data = DayData(line=files.line, day=files.day)
    if files.summary is not None:
        data.files["summary"] = str(files.summary)
        for raw in _rows(files.summary):
            shift = (raw.get("直") or "").strip()
            if not shift:
                continue
            row = ShiftRow(shift=shift)
            for column, attr in SUMMARY_COLUMNS.items():
                setattr(row, attr, number(raw.get(column)))
            data.shifts.append(row)
        data.shifts.sort(key=lambda r: _shift_key(r.shift))
    if files.stop is not None:
        data.files["stop"] = str(files.stop)
        data.stops = []
        for raw in _rows(files.stop):
            if (raw.get("区分") or "").strip() != STOP_TOTAL_KIND:
                continue
            data.stops.append(StopRow(
                shift=(raw.get("直") or "").strip(), kind=(raw.get("分類") or "").strip(),
                code=(raw.get("記号") or "").strip(), name=(raw.get("内訳") or "").strip(),
                count=number(raw.get("回数")), minutes=number(raw.get("停止時間(分)"))))
    if files.detail is not None:
        data.files["detail"] = str(files.detail)
        lots: dict[str, float] = {}
        packages: dict[str, float] = {}
        for raw in _rows(files.detail):
            shift = (raw.get("直") or "").strip()
            if (raw.get(DETAIL_LOT) or "").strip():
                lots[shift] = lots.get(shift, 0) + 1
            value = number(raw.get(DETAIL_PACKAGES))
            if value is not None:
                packages[shift] = packages.get(shift, 0) + value
        data.lots, data.packages = lots, packages
    return data


def load(roots: Iterable[Path], line: str, start: date, end: date) -> list[DayData]:
    """期間のうち、**集計CSVが置いてある日だけ**(無い日は入らない = 欠損)。"""
    return [_day(f) for f in agg_store.find_days(list(roots), line, start, end)]
