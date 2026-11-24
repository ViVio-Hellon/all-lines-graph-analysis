"""アプリの名前・置き場所 ── 1か所だけ。

【この端末だけのもの】は all-tools と同じ考え方で、アプリ本体(配布フォルダ)には
書かず、利用者ごとのローカル領域に置きます。

    %LOCALAPPDATA%\\AllLinesGraph\\
      runtime\\user_config.json   この端末の設定(参照パス・ログの出力パス・管理者パスワード)
      logs\\all_lines_graph\\      ログ(「ログの出力パス」を決めればそちらへ)
      data\\                     アプリ専用DB(ダッシュボード構成。後の段で使う)
      cache\\                    共有の日報データの写し(読み取り専用で読むため)

**追加ライブラリは使いません。** 各ラインPCの Python には標準ライブラリしか
入れられないためです(sqlite3 / json / logging / http.server / csv)。
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ID = "all-lines-graph-analysis"
DISPLAY_NAME = "全ライン グラフ分析"
VERSION = "0.1.0"

#: ローカル領域のフォルダ名(%LOCALAPPDATA% の下)
LOCAL_DIR_NAME = "AllLinesGraph"

#: ログのフォルダ名・ファイル名の頭(all-tools の `nippou` に当たる)
TOOL_ID = "all_lines_graph"

#: 起動用の Start.vbs / start.bat があるフォルダ(= リポジトリの直下)
APP_ROOT = Path(__file__).resolve().parent.parent

#: 待ち受け(127.0.0.1 だけ)。使われていれば次の番号を試す
HOST = "127.0.0.1"
PORT = 8741
PORT_RETRY = 5

#: 検証用の差し替え(テストが本物のローカル領域を触らないように)
ENV_LOCAL_DIR = "ALG_LOCAL_DIR"


def local_root() -> Path:
    """`%LOCALAPPDATA%\\AllLinesGraph`(Windows 以外は ~/.local/share)。"""
    override = os.environ.get(ENV_LOCAL_DIR, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if base:
        return Path(base) / LOCAL_DIR_NAME
    return Path.home() / ".local" / "share" / LOCAL_DIR_NAME


def local_dir(name: str) -> Path:
    """ローカル領域の下のフォルダ。無ければ作る。"""
    path = local_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def nippou_local_root() -> Path:
    """all-tools(日報管理ツール)のローカル領域 `%LOCALAPPDATA%\\NippouTool`。

    集計データの大本を決めていない端末では、**同じPCの日報管理ツールが既定で
    書き出す先**(`NippouTool\\work`)を見に行きます。
    """
    base = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "NippouTool"


def terminal_name() -> str:
    """この端末の名前(ログのファイル名に入れる)。Windows の COMPUTERNAME が先。"""
    import platform

    return (os.environ.get("COMPUTERNAME", "").strip()
            or platform.node().strip() or "この端末")
