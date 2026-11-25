"""ダッシュボードの中身を作る所(画面は描くだけ。**数と判断はここ**)。

* グラフ1枚 = 項目1つ × ライン N 本。**ラインごとに独立したグラフ**を返す
  (複数ラインを1つのグラフに重ねない ── 要件 2「ライン比較ルール」)。
* 条件はグラフごとに「個別に決めたもの」→「共通条件」の順で決まる。
  個別に決めたグラフは、共通条件を変えても上書きされない(画面側の `own`)。
* 取得にかかった時間・条件はログへ(`logging_setup.timed`)。
"""
from __future__ import annotations

import csv
import base64
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from . import agg_data, agg_store, config, line_target, metrics
from .file_names import safe_name
from .logging_setup import note, timed


class RequestError(Exception):
    pass


def _date(text: Any, name: str) -> date:
    try:
        return date.fromisoformat(str(text))
    except ValueError:
        raise RequestError(f"{name}の日付が読めません({text})。yyyy-mm-dd で指定してください。") from None


def meta() -> dict:
    """画面の部品: 項目の一覧・見つかったライン・直の並び・大本。"""
    roots = config.SETTINGS.agg_roots()
    scans = [agg_store.scan_root(r, with_latest=False) for r in roots]
    return {**metrics.catalog(),
            "lines": agg_store.lines(roots),
            "shifts": list(agg_data.SHIFT_ORDER),
            "roots": [{"root": s.root, "exists": s.exists, "error": s.error, "level": s.level} for s in scans]}


def graph(spec: dict) -> dict:
    """グラフ1枚ぶん。spec = {metric, chart, lines[], start, end, grain, shift}。"""
    key = spec.get("metric")
    metric = metrics.BY_KEY.get(key)
    if metric is None:
        raise RequestError(f"知らない項目です: {key}")
    if not metric.available:
        raise RequestError(f"「{metric.label}」は選べません: {metric.reason}")
    chart = spec.get("chart") if spec.get("chart") in metrics.CHARTS else "bar"
    why = metric.charts().get(chart)
    if why:
        raise RequestError(f"「{metric.label}」は{metrics.CHART_LABELS[chart]}にできません: {why}")
    start, end = _date(spec.get("start"), "開始"), _date(spec.get("end"), "終了")
    if end < start:
        start, end = end, start
    if (end - start).days > 366 * 5:
        raise RequestError("期間は5年までにしてください。")
    grain = spec.get("grain") if spec.get("grain") in metrics.GRAINS else "day"
    shift = str(spec.get("shift") or "")
    roots = config.SETTINGS.agg_roots()
    known = agg_store.lines(roots)
    lines = [str(l) for l in (spec.get("lines") or []) if str(l)] or known
    combo = _combo(spec, metric) if chart == "combo" else None
    targets = line_target.load(config.SETTINGS.line_target_path) if combo and combo["target"] else None
    out = []
    with timed(f"グラフのデータ({metric.label}/{metrics.CHART_LABELS[chart]})", lines=lines,
               start=start, end=end) as info:
        count = 0
        for line in lines:
            if line not in known:
                out.append({"line": line, "error": "このラインの集計データが見つかりません", "result": None})
                continue
            days = agg_data.load(roots, line, start, end)
            count += len(days)
            if combo is not None:
                result = _combo_result(days, metric, start, end, grain, shift, combo, targets, line)
            else:
                result = metrics.compute(days, metric, start, end, grain, chart, shift)
            result["data_days"] = len(days)
            result["source_days"] = sum(1 for d in days if _has_source(d, metric))
            out.append({"line": line, "error": "", "result": result})
        info["days"] = count
    return {"metric": metric.to_dict(), "chart": chart, "start": start.isoformat(), "end": end.isoformat(),
            "grain": grain, "shift": shift, "lines": out, "combo": combo,
            "targets": targets.to_dict(known) if targets is not None else None,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _combo(spec: dict, metric: metrics.Metric) -> dict:
    """組み合わせの決め方を形にそろえる。

    bars:   stacked(直ごとに積み上げ)/ total(合計の棒)
    line:   cumulative(累計を右の軸に。生産枚数なら目標の45度線も)/ metric(別の項目を右の軸に)
    """
    raw = spec.get("combo") if isinstance(spec.get("combo"), dict) else {}
    line_kind = raw.get("line") if raw.get("line") in ("cumulative", "metric", "none") else "cumulative"
    metric2 = raw.get("metric2") if raw.get("metric2") in metrics.BY_KEY else "rate"
    m2 = metrics.BY_KEY[metric2]
    if line_kind == "metric" and (not m2.available or m2.kind == "breakdown"):
        raise RequestError(f"「{m2.label}」は線に重ねられません(内訳・取れない項目は不可)。")
    return {"bars": "total" if raw.get("bars") == "total" else "stacked", "line": line_kind,
            "metric2": metric2,
            # 45度線は「生産枚数」の累計にだけ引く(目標は1日あたりの枚数)
            "target": line_kind == "cumulative" and metric.key == "sheets" and raw.get("target", True) is not False}


def _combo_result(days, metric, start, end, grain, shift, combo, targets, line) -> dict:
    """棒(左の軸)と線(右の軸)を1つに。線は overlays に入れる。"""
    bars = metrics.compute(days, metric, start, end, grain,
                           "combo_stacked" if combo["bars"] == "stacked" else "bar", shift)
    overlays: list[dict] = []
    if combo["line"] == "cumulative":
        running, seen, values = 0.0, False, []
        for v in bars["totals"]:
            if v is not None:
                running += v
                seen = True
            values.append(running if seen else None)      # データの無い区切りは横ばい
        overlays.append({"name": "日毎累計" if grain == "day" else "累計", "values": values,
                         "unit": metric.unit, "kind": "cumulative"})
        if combo["target"] and targets is not None:
            goal = targets.of(line)
            if goal:
                overlays.append({"name": "目標値", "values": line_target.cumulative(goal, bars["days"]),
                                 "unit": metric.unit, "kind": "target", "per_day": goal})
            else:
                bars["target_note"] = (targets.error or f"ライン毎目標に {line} がありません")
    elif combo["line"] == "metric":
        m2 = metrics.BY_KEY[combo["metric2"]]
        second = metrics.compute(days, m2, start, end, grain, "line", shift)
        overlays.append({"name": m2.label, "values": second["series"][0]["values"],
                         "unit": m2.unit, "kind": "metric", "digits": m2.digits})
    bars["overlays"] = overlays
    return bars


def _has_source(day: agg_data.DayData, metric: metrics.Metric) -> bool:
    if metric.source == "stop":
        return day.stops is not None
    if metric.source == "detail":
        return day.lots is not None
    return bool(day.shifts)


# ----------------------------------------------------------------------
# 書き出す(ブラウザのダウンロードは使わず、設定の書き出し先へ書く)
# ----------------------------------------------------------------------
def _out_dir() -> Path:
    folder = config.SETTINGS.export_dir / datetime.now().strftime("%Y.%m")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


CSV_HEADER = ["ダッシュボード", "グラフ", "ライン", "項目", "単位", "グラフの種類", "集計単位", "直",
              "期間の開始", "期間の終了", "区切り・内訳", "系列", "値", "データのある日数", "取得日時"]


def export_csv(name: str, specs: list[dict]) -> dict:
    """画面のグラフを**サーバで取り直して**1本のCSVに(画面と同じ式・同じ元データ)。"""
    if not specs:
        raise RequestError("書き出すグラフがありません。")
    rows: list[list[Any]] = []
    for spec in specs:
        body = graph(spec)
        metric = body["metric"]
        for item in body["lines"]:
            res = item["result"]
            if res is None:
                continue
            for s in res["series"]:
                for i, label in enumerate(res["labels"]):
                    value = s["values"][i]
                    days = res["days"][i] if res["mode"] == "time" else res["data_days"]
                    rows.append([name, spec.get("title") or metric["label"], item["line"], metric["label"],
                                 metric["unit"], metrics.CHART_LABELS[body["chart"]],
                                 metrics.GRAIN_LABELS[body["grain"]], body["shift"] or "全直",
                                 body["start"], body["end"], label, s["name"],
                                 "" if value is None else round(value, 4), days, body["fetched_at"]])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _out_dir() / f"グラフ分析_{safe_name(name, 'ダッシュボード', 40)}_{stamp}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)
    note(f"CSVに出しました: {path}({len(rows)}行)", label="CSVに出した")
    return {"ok": True, "path": str(path), "rows": len(rows),
            "message": f"CSVに出しました({len(rows)}行): {path}"}


def export_png(name: str, title: str, data_url: str) -> dict:
    head = "data:image/png;base64,"
    if not str(data_url).startswith(head):
        raise RequestError("画像の形が違います。")
    raw = base64.b64decode(str(data_url)[len(head):], validate=True)
    if len(raw) > 15 * 1024 * 1024:
        raise RequestError("画像が大きすぎます。")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _out_dir() / (f"グラフ分析_{safe_name(name, 'ダッシュボード', 40)}_"
                         f"{safe_name(title, 'グラフ', 40)}_{stamp}.png")
    path.write_bytes(raw)
    note(f"画像を保存しました: {path}", label="画像で保存した")
    return {"ok": True, "path": str(path), "message": f"画像を保存しました: {path}"}
