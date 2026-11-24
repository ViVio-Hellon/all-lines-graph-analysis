"""ログの置き場所と名前(all-tools の `log_names.py` と同じ形)。

    <ログの出力パス>\\all_lines_graph\\
      all_lines_graph_動作記録_<端末>.log              動いた記録(5MBで回す。.log.1〜.log.5)
      all_lines_graph_出来事_<yyyy-mm-dd>_<端末>.jsonl  エラー・操作の記録(端末ごと・日ごと)
      all_lines_graph_起動_<端末>.log                  起動の記録

* **ツール名のフォルダを作り、ファイル名の頭にもツール名を入れる。** 共有のフォルダに
  いろいろなツールが吐き出すので、取り出したときに開かなくても何のログか分かるように。
* **ファイル名に端末の名前を入れる。** 共有のフォルダを指したとき、何台もの端末が
  同じファイルへ書いて行が混ざらないように。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional

from .app_config import TOOL_ID

PREFIX = f"{TOOL_ID}_"
TEXT_KIND = "動作記録"
EVENT_KIND = "出来事"
LAUNCH_KIND = "起動"

EVENT_PREFIX = f"{PREFIX}{EVENT_KIND}_"

_UNSAFE = re.compile(r'[\\/:*?"<>|\s]+')
_EVENT_DATE = re.compile(rf"^{re.escape(EVENT_PREFIX)}(\d{{4}}-\d{{2}}-\d{{2}})_(.+)\.jsonl$")


def safe(name: str) -> str:
    """ファイル名に入れる端末の名前(使えない字と空白は `_`)。"""
    return _UNSAFE.sub("_", str(name or "")).strip("_") or "端末"


def tool_dir(base: Path) -> Path:
    return Path(base) / TOOL_ID


def text_log_name(terminal: str) -> str:
    return f"{PREFIX}{TEXT_KIND}_{safe(terminal)}.log"


def launch_log_name(terminal: str) -> str:
    return f"{PREFIX}{LAUNCH_KIND}_{safe(terminal)}.log"


def event_name(day: date, terminal: str) -> str:
    return f"{EVENT_PREFIX}{day:%Y-%m-%d}_{safe(terminal)}.jsonl"


def event_parts(name: str) -> Optional[tuple[date, str]]:
    """出来事のファイル名の(日付, 端末)。違えば None。"""
    m = _EVENT_DATE.match(name)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1)), m.group(2)
    except ValueError:
        return None
