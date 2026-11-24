"""all-tools と同じ見出し・同じ置き方で、集計CSVの見本を作る(テストと画面の確かめ用)。

    python -m tests.sample_data <大本のフォルダ> [日数]

見出しは all-tools `reporting/csv_export.py` の FIELDNAMES / STOP_FIELDNAMES と、
DETAIL_FIELDNAMES のうちこのアプリが読む列。数は作り物です(実データではありません)。
"""
from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

SUMMARY_HEADER = ["日付", "ライン", "直", "合計枚数", "合計重量(t)", "作業時間合計(分)", "稼働時間合計(分)",
                  "操業時間(分)", "管理ロス設備停止(分)", "段取り・突発停止(分)", "ハンドリング停止(分)",
                  "その他(分)", "停止合計(分)", "稼働率(%)", "生産性(t/h)"]
STOP_HEADER = ["日付", "ライン", "直", "区分", "分類", "記号", "内訳", "ページ", "行", "LOTNO", "停止の位置",
               "回数", "停止時間(分)", "その直の停止に占める割合(%)", "休憩の時刻"]
DETAIL_HEADER = ["日付", "ライン", "直", "ページ", "行", "係数処理ﾛｯﾄ数", "ロット№", "材・調質",
                 "梱包数量 梱包単位 包数", "作業人数", "実績合計 枚数", "実績合計 重量"]
REASONS = [("管理ロス設備停止", "1", "設備点検"), ("段取り・突発停止", "ア", "段取り替え"),
           ("段取り・突発停止", "イ", "機械トラブル"), ("ハンドリング停止", "A", "ﾌｫｰｸ待ち"),
           ("ハンドリング停止", "B", "資材待ち")]


def shift_row(day: date, line: str, shift: str, sheets: float, weight_t: float, stops: dict[str, float],
              work: float = 400) -> dict[str, str]:
    """1直ぶん。**稼働率・生産性は all-tools と同じ式で入れる**(ShiftAggregate)。"""
    loss, sudden, handling, other = (stops.get(k, 0) for k in ("loss", "sudden", "handling", "other"))
    stop = loss + sudden + handling + other
    operating = 1440 - stop
    return {
        "日付": f"{day.year}年{day.month}月{day.day}日", "ライン": line, "直": shift,
        "合計枚数": f"{sheets:.0f}", "合計重量(t)": f"{weight_t:.2f}", "作業時間合計(分)": f"{work:.0f}",
        "稼働時間合計(分)": f"{operating:.0f}", "操業時間(分)": f"{1440 - loss - other:.0f}",
        "管理ロス設備停止(分)": f"{loss:.0f}", "段取り・突発停止(分)": f"{sudden:.0f}",
        "ハンドリング停止(分)": f"{handling:.0f}", "その他(分)": f"{other:.0f}", "停止合計(分)": f"{stop:.0f}",
        "稼働率(%)": f"{operating / 1440 * 100:.1f}",
        "生産性(t/h)": f"{(weight_t / (operating / 60)) if operating > 0 else 0:.2f}",
    }


def write_day(root: Path, line: str, day: date, shifts: list[dict[str, str]],
              stops: list[tuple[str, str, str, str, int, float]] | None = None,
              details: list[tuple[str, str, float]] | None = None) -> Path:
    folder = root / line / "集計" / f"{day.year:04d}.{day.month:02d}" / f"{day.day:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = day.isoformat()
    with open(folder / f"集計_{stamp}_{line}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_HEADER)
        w.writeheader()
        w.writerows(shifts)
    if stops is not None:
        with open(folder / f"停止内訳_{stamp}_{line}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(STOP_HEADER)
            for shift, kind, code, name, count, minutes in stops:
                w.writerow([stamp, line, shift, "直の合計", kind, code, name, "", "", "", "", count, minutes, "", ""])
                w.writerow([stamp, line, shift, "1件ずつ", kind, code, name, 1, 1, "1234567", "作業停止①",
                            1, minutes, "", ""])          # 足すと二重になる行(読まないこと)
    if details is not None:
        with open(folder / f"集計明細_{stamp}_{line}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(DETAIL_HEADER)
            for i, (shift, lot, packages) in enumerate(details, start=1):
                w.writerow([stamp, line, shift, 1, i, "", lot, "A5052", "" if packages is None else packages, 3, 100, 1000])
    return folder


def generate(root: Path, lines: list[str], start: date, days: int, seed: int = 7) -> None:
    rnd = random.Random(seed)
    for li, line in enumerate(lines):
        for n in range(days):
            day = start + timedelta(days=n)
            if day.weekday() == 6:
                continue                                 # 日曜は稼働なし(ファイルが無い = 欠損)
            shifts, stops, details = [], [], []
            for shift in ("1直", "2直", "3直"):
                if line.endswith("10") and shift == "3直":
                    continue
                st = {"loss": rnd.choice([0, 0, 15, 30]), "sudden": rnd.choice([0, 10, 25, 60]),
                      "handling": rnd.choice([0, 5, 20]), "other": rnd.choice([0, 0, 0, 10])}
                sheets = rnd.randint(300, 900) * (1 + li * 0.15)
                shifts.append(shift_row(day, line, shift, sheets, sheets * rnd.uniform(0.9, 1.3) / 100, st))
                for kind, code, name in REASONS:
                    key = {"管理ロス設備停止": "loss", "段取り・突発停止": "sudden", "ハンドリング停止": "handling"}[kind]
                    if st[key]:
                        stops.append((shift, kind, code, name, 1, st[key] / 2))
                for k in range(rnd.randint(3, 8)):
                    details.append((shift, f"{rnd.randint(1000000, 9999999)}", rnd.randint(2, 12)))
            write_day(root, line, day, shifts, stops, details)


if __name__ == "__main__":
    target = Path(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    today = date.today()
    generate(target, ["L-1", "L-2", "L-3", "L-10", "機側"], today - timedelta(days=count - 1), count)
    print(f"見本を作りました: {target}")
