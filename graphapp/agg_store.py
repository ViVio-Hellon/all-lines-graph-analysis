r"""集計データの格納ルール ── **大本だけ決めれば、ライン・年月・日はこちらでたどる**

all-tools(日報管理ツール)は集計CSVを次の形で書き出します
(`tools/nippou/nippou/reporting/csv_export.py` の `line_dir` / `dated_dir`)。

    <大本>\
      <ライン>\
        集計\<yyyy.mm>\            CSVの読み方.txt / 計算内容.csv(年月に1つずつ)
        集計\<yyyy.mm>\<dd>\       集計_<yyyy-mm-dd>_<ライン>.csv
                                   集計明細_<yyyy-mm-dd>_<ライン>.csv
                                   停止内訳_<yyyy-mm-dd>_<ライン>.csv
        印刷\<yyyy.mm>\<dd>\       印刷用HTML(ここでは読まない)

* 上から **ライン → 種類(集計) → 年月 → 日**。年月は `2026.09`、日はゼロ詰め2桁。
* ライン名は Windows で使えない字を除いた名前(`file_names.safe_name`)。
* 日付が読めなかった日は、日のフォルダを作らず `集計\` の直下に出ています
  (`dated_dir` の約束)。ここもファイル名の日付で拾います。
* 出力先は2つまで決められます(2つ目は「使用・アクセス権の関係」で分けたいとき)。
  **中身は同じ形**なので、1つ目に無い日だけ2つ目から拾います。

【大本を1段ずれて指したとき】
現場ではラインのフォルダや `集計` フォルダそのものを指してしまうことがあります。
そのときも読めるように、指した先がどの段かを見分けます(`line_dirs`)。

    <大本>                → 下のフォルダのうち `集計\` を持つものがライン
    <大本>\<ライン>        → 自分がそのライン(`集計\` の下に yyyy.mm がある)
    <大本>\<ライン>\集計   → 親の名前がライン
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

KIND_AGGREGATE = "集計"

#: その日に出ている3本(鍵, ファイル名の頭)
FILE_KINDS: tuple[tuple[str, str], ...] = (
    ("summary", "集計_"),        # 直ごとの合計
    ("detail", "集計明細_"),     # その日の明細行ぜんぶ
    ("stop", "停止内訳_"),       # 停止の内訳
)
KIND_LABELS = {"summary": "集計", "detail": "集計明細", "stop": "停止内訳"}

#: 年月に1つずつ置かれる説明
MONTH_README = "CSVの読み方.txt"
MONTH_FORMULA = "計算内容.csv"

_MONTH_DIR = re.compile(r"^(\d{4})\.(\d{2})$")
_DAY_DIR = re.compile(r"^(\d{2})$")
#: 集計_2026-08-03_L-1.csv / 集計明細_… / 停止内訳_…
_FILE_NAME = re.compile(r"^(集計明細|集計|停止内訳)_(\d{4}-\d{2}-\d{2})_(.+)\.csv$")
#: 期間別に書き出したもの(集計_ロット別_2026-08-01_2026-08-31_L1.csv)は日の集計ではない
_PERIOD_NAME = re.compile(r"_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_")

_KIND_BY_HEAD = {"集計": "summary", "集計明細": "detail", "停止内訳": "stop"}


# ----------------------------------------------------------------------
# 1. ライン
# ----------------------------------------------------------------------
def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _subdirs(path: Path) -> list[Path]:
    try:
        return sorted((p for p in path.iterdir() if _is_dir(p)), key=lambda p: p.name)
    except OSError:
        return []


def _has_months(kind_dir: Path) -> bool:
    return any(_MONTH_DIR.match(p.name) for p in _subdirs(kind_dir)) or any(
        _FILE_NAME.match(p.name) for p in _files(kind_dir))


def _files(path: Path) -> list[Path]:
    try:
        return sorted(p for p in path.iterdir() if p.is_file())
    except OSError:
        return []


def line_dirs(root: Path) -> dict[str, Path]:
    """{ライン名: そのラインの `集計` フォルダ}。**指した段がずれていても拾う。**"""
    root = Path(root)
    if not _is_dir(root):
        return {}
    # <大本>\<ライン>\集計 を直接指した
    if root.name == KIND_AGGREGATE and _has_months(root):
        return {root.parent.name: root}
    found: dict[str, Path] = {}
    for child in _subdirs(root):
        kind = child / KIND_AGGREGATE
        if _is_dir(kind):
            found[child.name] = kind
    if found:
        return found
    # <大本>\<ライン> を直接指した(下にラインが無く、自分の下に 集計\yyyy.mm がある)
    own = root / KIND_AGGREGATE
    if _is_dir(own) and _has_months(own):
        return {root.name: own}
    return {}


def lines(roots: Iterable[Path]) -> list[str]:
    """大本(複数)から見つかったライン名。名前順・重複なし。"""
    names: set[str] = set()
    for root in roots:
        names.update(line_dirs(root))
    return sorted(names, key=_line_sort_key)


def _line_sort_key(name: str) -> tuple:
    """L-2 が L-10 より先に来るように、数字は数として並べる。"""
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name))


# ----------------------------------------------------------------------
# 2. 年月・日
# ----------------------------------------------------------------------
def months(kind_dir: Path) -> list[tuple[int, int, Path]]:
    """(年, 月, フォルダ)。古い順。"""
    out = []
    for sub in _subdirs(kind_dir):
        m = _MONTH_DIR.match(sub.name)
        if m and 1 <= int(m.group(2)) <= 12:
            out.append((int(m.group(1)), int(m.group(2)), sub))
    return out


@dataclass
class DayFiles:
    """1ライン・1日ぶんの集計CSV。無い種類は None。"""

    line: str
    day: date
    folder: Path
    root: Path
    summary: Optional[Path] = None
    detail: Optional[Path] = None
    stop: Optional[Path] = None

    def get(self, kind: str) -> Optional[Path]:
        return getattr(self, kind)

    def kinds(self) -> list[str]:
        return [k for k, _ in FILE_KINDS if self.get(k) is not None]

    def to_dict(self) -> dict:
        return {"line": self.line, "day": self.day.isoformat(), "folder": str(self.folder),
                "root": str(self.root),
                "files": {k: str(self.get(k)) for k in self.kinds()}}


def _parse_name(name: str) -> Optional[tuple[str, date, str]]:
    """(種類, 日, ライン)。日の集計でなければ None。"""
    if _PERIOD_NAME.search(name):
        return None
    m = _FILE_NAME.match(name)
    if not m:
        return None
    try:
        day = date.fromisoformat(m.group(2))
    except ValueError:
        return None
    return _KIND_BY_HEAD[m.group(1)], day, m.group(3)


def _collect(folder: Path, line: str, root: Path, start: date, end: date,
             into: dict[date, DayFiles]) -> None:
    """フォルダ直下のCSVを、ファイル名の日付で拾う。**先に入っていた種類は上書きしない。**"""
    for file in _files(folder):
        parsed = _parse_name(file.name)
        if parsed is None:
            continue
        kind, day, _ = parsed
        if not (start <= day <= end):
            continue
        entry = into.get(day)
        if entry is None:
            entry = into[day] = DayFiles(line=line, day=day, folder=folder, root=root)
        if entry.get(kind) is None:
            setattr(entry, kind, file)


def _days_in_root(root: Path, line: str, start: date, end: date,
                  into: dict[date, DayFiles]) -> None:
    kind_dir = line_dirs(root).get(line)
    if kind_dir is None:
        return
    first = (start.year, start.month)
    last = (end.year, end.month)
    for year, month, month_dir in months(kind_dir):
        if not (first <= (year, month) <= last):
            continue                      # 期間の外の月は開かない(共有では開くだけで遅い)
        for day_dir in _subdirs(month_dir):
            if _DAY_DIR.match(day_dir.name):
                _collect(day_dir, line, root, start, end, into)
        _collect(month_dir, line, root, start, end, into)   # 念のため年月の直下も
    _collect(kind_dir, line, root, start, end, into)         # 日付が読めなかった日(集計\ の直下)


def find_days(roots: Iterable[Path], line: str, start: date, end: date) -> list[DayFiles]:
    """期間の各日の集計CSV。**1つ目の大本が先**、無い日・無い種類だけ2つ目から。"""
    if end < start:
        start, end = end, start
    found: dict[date, DayFiles] = {}
    for root in roots:
        _days_in_root(Path(root), line, start, end, found)
    return [found[d] for d in sorted(found)]


def find_day(roots: Iterable[Path], line: str, day: date) -> Optional[DayFiles]:
    days = find_days(roots, line, day, day)
    return days[0] if days else None


def latest_day(roots: Iterable[Path], line: str) -> Optional[date]:
    """いちばん新しい日(新しい月から順に見る ── 全部は開かない)。"""
    best: Optional[date] = None
    for root in roots:
        kind_dir = line_dirs(Path(root)).get(line)
        if kind_dir is None:
            continue
        for year, month, month_dir in reversed(months(kind_dir)):
            if best is not None and (year, month) < (best.year, best.month):
                break
            got: dict[date, DayFiles] = {}
            start = date(year, month, 1)
            end = date(year + (month == 12), month % 12 + 1, 1)
            _days_in_root(Path(root), line, start, end - timedelta(days=1), got)
            if got:
                newest = max(got)
                best = newest if best is None or newest > best else best
                break
    return best


def month_notes(roots: Iterable[Path], line: str, year: int, month: int) -> dict[str, Path]:
    """その年月の説明ファイル({名前: 道})。CSVの列の意味を画面に出すときに使う。"""
    out: dict[str, Path] = {}
    for root in roots:
        kind_dir = line_dirs(Path(root)).get(line)
        if kind_dir is None:
            continue
        folder = kind_dir / f"{year:04d}.{month:02d}"
        for name in (MONTH_README, MONTH_FORMULA):
            if name not in out and (folder / name).is_file():
                out[name] = folder / name
    return out


# ----------------------------------------------------------------------
# 3. 読む
# ----------------------------------------------------------------------
def read_csv(path: Path) -> list[dict[str, str]]:
    """BOM付きUTF-8(all-tools の書き方)を先に、だめなら CP932 で読む。**書かない。**"""
    for encoding in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=encoding) as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8-sig/cp932", b"", 0, 1, f"{path} の文字コードを読めません")


# ----------------------------------------------------------------------
# 4. 設定画面に出す「いま何が見えているか」
# ----------------------------------------------------------------------
@dataclass
class RootScan:
    root: str
    exists: bool
    level: str = ""          # 大本 / ライン / 集計 ── どの段を指しているか
    lines: list[dict] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return vars(self)


def scan_root(root: Path, *, with_latest: bool = True) -> RootScan:
    """大本1つの中身(ライン・年月の数・いちばん新しい日)。**例外は投げない。**"""
    root = Path(root)
    scan = RootScan(root=str(root), exists=_is_dir(root))
    if not scan.exists:
        scan.error = "フォルダがありません(共有に届いていないか、道が違います)"
        return scan
    found = line_dirs(root)
    if not found:
        scan.error = ("ラインのフォルダ(<ライン>\\集計\\)が見つかりません。"
                      "日報管理ツールの「集計CSV・印刷用HTMLの出力パス」と同じフォルダを指してください")
        return scan
    first = next(iter(found.values()))
    scan.level = ("集計" if first == root else "ライン" if first.parent == root else "大本")
    for name in sorted(found, key=_line_sort_key):
        month_list = months(found[name])
        latest = latest_day([root], name) if with_latest else None
        scan.lines.append({
            "line": name,
            "months": len(month_list),
            "first_month": (f"{month_list[0][0]}.{month_list[0][1]:02d}" if month_list else ""),
            "last_month": (f"{month_list[-1][0]}.{month_list[-1][1]:02d}" if month_list else ""),
            "latest_day": latest.isoformat() if latest else "",
        })
    return scan


def example_path(root: Path, line: str = "<ライン>", day: Optional[date] = None) -> str:
    """その大本で、ある日の集計CSVがどこにあるか(画面の説明用)。"""
    ym = f"{day.year:04d}.{day.month:02d}" if day else "<yyyy.mm>"
    dd = f"{day.day:02d}" if day else "<dd>"
    stamp = day.isoformat() if day else "<yyyy-mm-dd>"
    return str(Path(root) / line / KIND_AGGREGATE / ym / dd / f"集計_{stamp}_{line}.csv")
