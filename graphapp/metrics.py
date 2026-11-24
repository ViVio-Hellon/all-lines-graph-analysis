"""グラフにできる項目と、期間(日・週・月・年)へのまとめ方。

【決まり】
* **all-tools の集計値と式を正とする。** 合計できる数(枚数・重量・時間)は足すだけ。
* 稼働率・生産性は**足せない**ので、まとめるときは all-tools の式で出し直す:
    稼働率(%) = (1440分 × 直の数 − 停止合計) ÷ (1440分 × 直の数) × 100
        (`logic/aggregation.day_rate_pct`「直ごとの平均ではなく、合計から出し直す」)
    生産性(t/h) = 重量(t) ÷ ((1440分 × 直の数 − 停止合計) ÷ 60)
        (`ShiftAggregate.productivity_t_per_h` の分母「稼働時間」を直の数ぶん足したもの。
         稼働時間が 0 以下なら 0)
  直1つ・1日なら、どちらも集計CSVの値と同じになる(テストで確かめている)。
* **欠損と 0 を分ける。** その期間に1日もデータが無ければ None(グラフでは空き)。
* 取れない項目は一覧に出すが選べない(理由を出す)。

【グラフの種類】
    量(sum)      棒・横棒・折れ線・積み上げ棒(直の内訳)・円(直の構成比)
    率(ratio)    棒・横棒・折れ線(足せないので積み上げ・円は不可)
    内訳(breakdown) 棒・横棒(項目ごとの合計)・積み上げ棒(期間ごと)・円(構成比)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from .agg_data import SHIFT_ORDER, DayData, ShiftRow

MINUTES_PER_DAY = 1440

CHARTS = ("bar", "hbar", "line", "stacked", "pie")
CHART_LABELS = {"bar": "棒グラフ", "hbar": "横棒グラフ", "line": "折れ線グラフ",
                "stacked": "積み上げ棒", "pie": "円グラフ"}
GRAINS = ("day", "week", "month", "year")
GRAIN_LABELS = {"day": "日別", "week": "週別", "month": "月別", "year": "年別"}

CATEGORIES = ("生産実績", "稼働状況", "停止分析", "生産性", "人員・作業")

#: 内訳で出す項目の数(多いと読めないので、残りは「その他」にまとめる)
TOP_N = 8


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    category: str
    unit: str
    kind: str                      # sum / ratio / breakdown
    source: str                    # summary / stop / detail
    note: str = ""
    available: bool = True
    reason: str = ""               # 選べない理由
    digits: int = 0

    def charts(self) -> dict[str, str]:
        """{種類: 選べない理由}(空文字なら選べる)。"""
        if self.kind == "ratio":
            why = "率は足し合わせられないため、積み上げ・円にはできません"
            return {"bar": "", "hbar": "", "line": "", "stacked": why, "pie": why}
        if self.kind == "breakdown":
            return {"bar": "", "hbar": "", "line": "内訳は棒・積み上げ棒・円で表示します",
                    "stacked": "", "pie": ""}
        return {c: "" for c in CHARTS}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["charts"] = self.charts()
        return d


def _sum_attr(attr: str) -> Callable[[ShiftRow], Optional[float]]:
    return lambda row: getattr(row, attr)


METRICS: tuple[Metric, ...] = (
    # 生産実績
    Metric("sheets", "生産枚数", "生産実績", "枚", "sum", "summary", "集計CSVの「合計枚数」"),
    Metric("weight", "生産重量", "生産実績", "t", "sum", "summary", "集計CSVの「合計重量(t)」", digits=2),
    Metric("packages", "包数", "生産実績", "包", "sum", "detail", "集計明細CSVの「梱包数量 梱包単位 包数」の合計"),
    Metric("lots", "ロット数", "生産実績", "件", "sum", "detail", "集計明細CSVでロット№のある行の数"),
    # 稼働状況
    Metric("operating", "稼働時間", "稼働状況", "分", "sum", "summary", "集計CSVの「稼働時間合計(分)」"),
    Metric("operational", "操業時間", "稼働状況", "分", "sum", "summary", "集計CSVの「操業時間(分)」"),
    Metric("stop_total", "停止時間", "稼働状況", "分", "sum", "summary", "集計CSVの「停止合計(分)」"),
    Metric("rate", "稼働率", "稼働状況", "%", "ratio", "summary",
           "(1440分×直の数−停止合計)÷(1440分×直の数)。all-tools の day_rate_pct と同じ式", digits=1),
    # 停止分析
    Metric("stop_kinds", "停止の分類別 時間", "停止分析", "分", "breakdown", "summary",
           "管理ロス設備停止・段取り・突発停止・ハンドリング停止・その他(集計CSV)"),
    Metric("stop_reason_min", "停止理由別 時間", "停止分析", "分", "breakdown", "stop",
           "停止内訳CSVの「直の合計」行・内訳ごと"),
    Metric("stop_reason_count", "停止理由別 回数", "停止分析", "回", "breakdown", "stop",
           "停止内訳CSVの「直の合計」行・内訳ごと"),
    Metric("loss", "管理ロス設備停止", "停止分析", "分", "sum", "summary", "集計CSVの「管理ロス設備停止(分)」"),
    Metric("sudden", "段取り・突発停止", "停止分析", "分", "sum", "summary", "集計CSVの「段取り・突発停止(分)」"),
    Metric("handling", "ハンドリング停止", "停止分析", "分", "sum", "summary", "集計CSVの「ハンドリング停止(分)」"),
    # 生産性
    Metric("productivity", "生産性(時間当たり生産重量)", "生産性", "t/h", "ratio", "summary",
           "重量(t)÷稼働時間(h)。all-tools の productivity_t_per_h と同じ式", digits=2),
    Metric("sheets_per_hour", "時間当たり生産枚数", "生産性", "枚/h", "ratio", "summary",
           available=False, reason="all-tools の集計に無い数です。独自の式で出さない決まりのため、"
           "式が決まるまで選べません"),
    # 人員・作業
    Metric("work", "作業時間", "人員・作業", "分", "sum", "summary", "集計CSVの「作業時間合計(分)」"),
    Metric("workers", "作業人数・投入人員", "人員・作業", "人", "sum", "detail", available=False,
           reason="集計CSVに直ごとの人数がありません(明細の行ごとの人数を足すと延べ人数になり、意味が変わります)"),
    Metric("standard_time", "標準時間と実績時間の比較", "人員・作業", "分", "sum", "summary",
           available=False, reason="標準作業時間は集計CSVとは別の出力です。取り込み方を決めてから対応します"),
)
BY_KEY = {m.key: m for m in METRICS}

_SUM_ATTRS = {"sheets": "sheets", "weight": "weight_t", "operating": "operating_min",
              "operational": "operational_min", "stop_total": "stop_min", "loss": "loss_min",
              "sudden": "sudden_min", "handling": "handling_min", "work": "work_min"}
STOP_KIND_COLUMNS = (("loss_min", "管理ロス設備停止"), ("sudden_min", "段取り・突発停止"),
                     ("handling_min", "ハンドリング停止"), ("other_min", "その他停止"))


# ----------------------------------------------------------------------
# 期間の区切り
# ----------------------------------------------------------------------
def bucket_start(day: date, grain: str) -> date:
    if grain == "week":
        return day - timedelta(days=day.weekday())          # 月曜はじまり
    if grain == "month":
        return day.replace(day=1)
    if grain == "year":
        return day.replace(month=1, day=1)
    return day


def _next(start: date, grain: str) -> date:
    if grain == "week":
        return start + timedelta(days=7)
    if grain == "month":
        return date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    if grain == "year":
        return date(start.year + 1, 1, 1)
    return start + timedelta(days=1)


def bucket_label(start: date, grain: str, multi_year: bool) -> str:
    if grain == "week":
        return f"{start.month}/{start.day}週" if not multi_year else f"{start:%Y}/{start.month}/{start.day}週"
    if grain == "month":
        return f"{start.year}.{start.month:02d}"
    if grain == "year":
        return f"{start.year}年"
    return f"{start.month}/{start.day}" if not multi_year else f"{start:%Y}/{start.month}/{start.day}"


def buckets(start: date, end: date, grain: str) -> list[date]:
    out = []
    cur = bucket_start(start, grain)
    while cur <= end:
        out.append(cur)
        cur = _next(cur, grain)
    return out


# ----------------------------------------------------------------------
# まとめる
# ----------------------------------------------------------------------
def _shifts(day: DayData, shift: str) -> list[ShiftRow]:
    return [r for r in day.shifts if not shift or r.shift == shift]


def _sum(values: list[Optional[float]]) -> Optional[float]:
    found = [v for v in values if v is not None]
    return sum(found) if found else None


def _ratio(rows: list[ShiftRow], key: str) -> Optional[float]:
    """稼働率・生産性を all-tools の式で(直の行が無ければ None)。"""
    usable = [r for r in rows if r.stop_min is not None]
    if not usable:
        return None
    whole = MINUTES_PER_DAY * len(usable)
    operating = whole - sum(r.stop_min for r in usable)
    if key == "rate":
        return max(0.0, operating / whole * 100)
    weight = _sum([r.weight_t for r in usable])
    if weight is None:
        return None
    return 0.0 if operating <= 0 else weight / (operating / 60)


def _shift_values(day: DayData, metric: Metric, shift: str) -> dict[str, Optional[float]]:
    """その日の {直: 値}(量の項目)。"""
    if metric.source == "detail":
        table = day.lots if metric.key == "lots" else day.packages
        if table is None:
            return {}
        names = {r.shift for r in day.shifts} | set(table)
        return {s: table.get(s, 0.0) for s in names if not shift or s == shift}
    attr = _SUM_ATTRS[metric.key]
    return {r.shift: getattr(r, attr) for r in _shifts(day, shift)}


def _breakdown(day: DayData, metric: Metric, shift: str) -> Optional[dict[str, float]]:
    """その日の {項目: 値}(内訳の項目)。データが無ければ None。"""
    if metric.key == "stop_kinds":
        rows = _shifts(day, shift)
        if not rows:
            return None
        out: dict[str, float] = {}
        for attr, label in STOP_KIND_COLUMNS:
            value = _sum([getattr(r, attr) for r in rows])
            if value is not None:
                out[label] = value
        return out
    if day.stops is None:
        return None
    out = {}
    for stop in day.stops:
        if shift and stop.shift != shift:
            continue
        name = stop.name or stop.code or "(記号なし)"
        value = stop.minutes if metric.key == "stop_reason_min" else stop.count
        if value is not None:
            out[name] = out.get(name, 0.0) + value
    return out


def _order_shifts(names) -> list[str]:
    return sorted(names, key=lambda s: (SHIFT_ORDER.index(s) if s in SHIFT_ORDER else 99, s))


def compute(days: list[DayData], metric: Metric, start: date, end: date, grain: str,
            chart: str, shift: str = "") -> dict:
    """1ライン分のグラフの中身。

    返すもの:
        labels      横軸(期間の区切り、または内訳の項目)
        series      [{name, values}](values の None はデータなし)
        days        区切りごとのデータのある日数(欠損の目印)
        total       期間全体の値(量は合計・率は出し直し)
    """
    if grain not in GRAINS:
        grain = "day"
    multi_year = start.year != end.year
    starts = buckets(start, end, grain)
    index = {b: i for i, b in enumerate(starts)}
    labels = [bucket_label(b, grain, multi_year) for b in starts]
    per_bucket: list[list[DayData]] = [[] for _ in starts]
    for day in days:
        if start <= day.day <= end:
            per_bucket[index[bucket_start(day.day, grain)]].append(day)
    days_count = [len(b) for b in per_bucket]

    if metric.kind == "ratio":
        values = [_ratio([r for d in b for r in _shifts(d, shift)], metric.key) for b in per_bucket]
        total = _ratio([r for d in days if start <= d.day <= end for r in _shifts(d, shift)], metric.key)
        return {"labels": labels, "series": [{"name": shift or "全直", "values": values}],
                "days": days_count, "total": total, "mode": "time"}

    if metric.kind == "sum":
        by_shift: list[dict[str, Optional[float]]] = []
        for bucket in per_bucket:
            acc: dict[str, list[Optional[float]]] = {}
            for d in bucket:
                for s, v in _shift_values(d, metric, shift).items():
                    acc.setdefault(s, []).append(v)
            by_shift.append({s: _sum(v) for s, v in acc.items()})
        totals = [_sum(list(b.values())) if b else None for b in by_shift]
        total = _sum(totals)
        names = _order_shifts({s for b in by_shift for s in b})
        if chart == "pie":
            vals = [_sum([b.get(s) for b in by_shift]) for s in names]
            return {"labels": names, "series": [{"name": metric.label, "values": vals}],
                    "days": days_count, "total": total, "mode": "category"}
        if chart == "stacked":
            series = [{"name": s, "values": [b.get(s) if b else None for b in by_shift]} for s in names]
            return {"labels": labels, "series": series, "days": days_count, "total": total, "mode": "time"}
        return {"labels": labels, "series": [{"name": shift or "全直", "values": totals}],
                "days": days_count, "total": total, "mode": "time"}

    # breakdown
    per: list[Optional[dict[str, float]]] = []
    for bucket in per_bucket:
        parts = [p for p in (_breakdown(d, metric, shift) for d in bucket) if p is not None]
        if not parts:
            per.append(None)
            continue
        merged: dict[str, float] = {}
        for p in parts:
            for k, v in p.items():
                merged[k] = merged.get(k, 0.0) + v
        per.append(merged)
    grand: dict[str, float] = {}
    for p in per:
        for k, v in (p or {}).items():
            grand[k] = grand.get(k, 0.0) + v
    if metric.key == "stop_kinds":
        order = [label for _, label in STOP_KIND_COLUMNS if label in grand]
    else:
        order = sorted(grand, key=lambda k: -grand[k])
    other = order[TOP_N:]
    order = order[:TOP_N] + (["その他(上位以外)"] if other else [])

    def pick(part: dict[str, float], name: str) -> float:
        if name == "その他(上位以外)":
            return sum(part.get(k, 0.0) for k in other)
        return part.get(name, 0.0)

    total = sum(grand.values()) if any(p is not None for p in per) else None
    if chart == "stacked":
        series = [{"name": n, "values": [pick(p, n) if p is not None else None for p in per]} for n in order]
        return {"labels": labels, "series": series, "days": days_count, "total": total, "mode": "time"}
    vals = [pick(grand, n) for n in order]
    return {"labels": order, "series": [{"name": metric.label, "values": vals}],
            "days": days_count, "total": total, "mode": "category"}


def catalog() -> dict:
    return {"metrics": [m.to_dict() for m in METRICS], "categories": list(CATEGORIES),
            "charts": CHART_LABELS, "grains": GRAIN_LABELS}
