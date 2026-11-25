"""ライン毎目標(45度線) ── all-tools `tools/nippou/nippou/logic/line_target.py` と同じ読み方・同じ線

【目標は「1日あたりの枚数」】
VBA `目標値抜き取り` / `グラフ挿入` の 累積目標 = 目標・累積上昇 = 目標 で、
k 日目の累積目標は 目標 × k(原点から一定の傾きで伸びる線 = 45度線管理)。
ここでも「データのある日」を k に数える(all-tools のグラフは日付の点がデータのある日だけ)。
週・月・年の区切りでは、その区切りまでのデータのある日数 × 目標。

【CSV の書き方】(寛容に読む。all-tools と同じ)

    # 行頭 # は覚え書き。空行は飛ばす
    L-1,12
    LVC,119
    機側  100        ← タブでも空白でもよい
    ＮＳ１，１０      ← 全角も読む

**読めない行は黙って捨てない**(捨てると線がひっそり消える)。`problems` に行番号つきで入れて画面に出す。
同じラインが2回出たら後の行を使い、2回出ていることも `problems` に残す。

【ライン名の突き合わせ】全角・半角、大文字小文字、空白、`-` `_` `.` の揺れを吸収して、
集計データのフォルダ名(ライン)と合わせる(`L1` `l-1` `Ｌ－１` → `L-1`)。
"""
from __future__ import annotations

import os
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

FILE_NAME = "ライン毎目標.csv"
SEPARATORS = (",", "\t", ";")
COMMENT_MARKS = ("#", "//", "'")


@dataclass
class Targets:
    values: dict[str, float] = field(default_factory=dict)      # 揺れを落とした名前 → 目標
    names: dict[str, str] = field(default_factory=dict)         # 揺れを落とした名前 → CSV に書いた名前
    problems: list[dict] = field(default_factory=list)
    source: str = ""
    error: str = ""

    def of(self, line: str) -> Optional[float]:
        value = self.values.get(fold(line))
        return value if value else None

    def to_dict(self, lines: Iterable[str] = ()) -> dict:
        return {"source": self.source, "error": self.error, "problems": self.problems,
                "values": {self.names.get(k, k): v for k, v in self.values.items()},
                "unmatched": [self.names.get(k, k) for k in self.values if k not in {fold(l) for l in lines}]
                if lines else []}


def fold(text: str) -> str:
    """突き合わせる形(全角→半角・大文字・区切り記号と空白を落とす)。"""
    folded = unicodedata.normalize("NFKC", str(text or "")).strip().upper()
    for mark in ("-", "_", " ", "　", ".", "．", "ー"):
        folded = folded.replace(mark, "")
    return folded


def to_number(text: str) -> Optional[float]:
    folded = unicodedata.normalize("NFKC", str(text or "")).strip().replace(",", "").replace("　", "")
    if not folded:
        return None
    try:
        return float(folded)
    except ValueError:
        return None


def _split(line: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", line)
    for sep in SEPARATORS:
        if sep in folded:
            return [part.strip() for part in folded.split(sep)]
    return folded.split()


def parse(text: str, *, source: str = "") -> Targets:
    targets = Targets(source=source)
    seen: dict[str, int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().lstrip("﻿")
        if not line or any(line.startswith(m) for m in COMMENT_MARKS):
            continue
        parts = [p for p in _split(line) if p != ""]
        if len(parts) < 2:
            targets.problems.append({"line_no": number, "text": line, "reason": "「ライン,目標」の形になっていません"})
            continue
        key = fold(parts[0])
        if not key:
            targets.problems.append({"line_no": number, "text": line, "reason": "ライン名が空です"})
            continue
        value = to_number(parts[1])
        if value is None:
            targets.problems.append({"line_no": number, "text": line,
                                     "reason": f"目標「{parts[1]}」が数字として読めません"})
            continue
        if value < 0:
            targets.problems.append({"line_no": number, "text": line, "reason": "目標がマイナスです"})
            continue
        if key in seen:
            targets.problems.append({"line_no": number, "text": line,
                                     "reason": f"{parts[0]} は {seen[key]}行目にもあります(この行の値を使います)"})
        seen[key] = number
        targets.values[key] = value
        targets.names[key] = unicodedata.normalize("NFKC", parts[0]).strip()
    return targets


def resolve(path: Optional[Path]) -> Optional[Path]:
    """設定の道 → CSV。フォルダを指していれば、その下の `ライン毎目標.csv`。"""
    if path is None:
        return None
    try:
        return path / FILE_NAME if path.is_dir() else path
    except OSError:
        return path


_cache: dict[str, tuple[tuple, Targets]] = {}
_lock = threading.Lock()


def load(path: Optional[Path]) -> Targets:
    """読む(大きさ・更新時刻が同じなら読み直さない)。**例外にしない。**"""
    target = resolve(path)
    if target is None:
        return Targets(error="ライン毎目標のCSVを決めていません(設定の参照設定)")
    try:
        st = os.stat(target)
    except OSError:
        return Targets(source=str(target), error=f"ライン毎目標のCSVがありません: {target}")
    stamp = (st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _cache.get(str(target))
        if hit and hit[0] == stamp:
            return hit[1]
    raw = target.read_bytes()
    for encoding in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return Targets(source=str(target), error="ライン毎目標のCSVの文字コードを読めません")
    targets = parse(text, source=str(target))
    with _lock:
        _cache[str(target)] = (stamp, targets)
    return targets


def cumulative(target: Optional[float], data_days: list[int]) -> list[Optional[float]]:
    """区切りごとの 45度線(目標 × その区切りまでのデータのある日数)。

    最初のデータの前の区切りは None(線を引かない)。データの無い区切りは横ばい。
    """
    if not target:
        return [None] * len(data_days)
    out: list[Optional[float]] = []
    total = 0
    for n in data_days:
        total += n
        out.append(float(target) * total if total else None)
    return out
