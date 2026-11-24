"""設定の鍵と、**実際に見に行く道**を決める所。

鍵の名前は **all-tools(日報管理ツール)と同じ**にしてあります。同じ値を指す
設定なので、名前を揃えておけば配布設定の中身を見比べるときに迷いません。

    report_output_dir     集計データの大本(all-tools の「集計CSV・印刷用HTMLの出力パス」)
    report_output_dir_2   集計データの大本(2つ目。all-tools の「集計CSVの出力パス(2つ目)」)
    access_dir            共有の日報データの置き場所(読み取り専用で読む)
    access_db_filename    共有の日報データのファイル名(既定 日報データ.sqlite3)
    log_dir               ログの出力パス
    admin_password        管理者パスワード(撹拌した値)

【集計データは「大本」だけ決める】
all-tools は集計CSVを次の形で書き出します(`reporting/csv_export.dated_dir`)。

    <大本>\\<ライン>\\集計\\<yyyy.mm>\\<dd>\\集計_<yyyy-mm-dd>_<ライン>.csv

ここで決めるのは **<大本> だけ**です。ライン・年月・日のフォルダは
`agg_store` がたどります(設定で年や日付を指定しない)。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import app_config, user_settings

KEY_AGG_ROOT = "report_output_dir"
KEY_AGG_ROOT2 = "report_output_dir_2"
KEY_ACCESS_DIR = "access_dir"
KEY_ACCESS_DB_FILE = "access_db_filename"
KEY_LOG_DIR = "log_dir"
KEY_ADMIN_PASSWORD = "admin_password"

DEFAULT_ACCESS_DB_FILE = "日報データ.sqlite3"
#: 管理者パスワードの既定(all-tools と同じ。現場の合言葉を2つにしない)
DEFAULT_ADMIN_PASSWORD = "nisk"


def resolve_dir(text: str) -> Path:
    r"""打たれた道を、実際に見に行く道にする(all-tools の `config.resolve_dir` と同じ)。

    絶対(``\\サーバ\共有\…`` / ``C:\…``)はそのまま。相対は**アプリのフォルダから**
    たどる ── 作業フォルダは起動のしかたで変わるので、そこから見ない。
    """
    trimmed = (text or "").strip().strip('"').strip()
    if not trimmed:
        raise ValueError("道が空です")
    path = Path(trimmed).expanduser()
    return path if path.is_absolute() else app_config.APP_ROOT / path


def is_relative_setting(text: str) -> bool:
    trimmed = (text or "").strip().strip('"').strip()
    return bool(trimmed) and not Path(trimmed).expanduser().is_absolute()


@dataclass(frozen=True)
class _Settings:
    """いまの設定から道を出す。**毎回設定ファイルを読む**(画面で変えたらすぐ効く)。"""

    @property
    def agg_root(self) -> Path:
        """集計データの大本。決めていなければ、同じPCの日報管理ツールの既定の出力先。"""
        configured = user_settings.text(KEY_AGG_ROOT)
        return resolve_dir(configured) if configured else self.default_agg_root

    @property
    def default_agg_root(self) -> Path:
        return app_config.nippou_local_root() / "work"

    @property
    def agg_root_2(self) -> Optional[Path]:
        """2つ目の大本。決めていなければ None(見ない)。"""
        configured = user_settings.text(KEY_AGG_ROOT2)
        return resolve_dir(configured) if configured else None

    def agg_roots(self) -> list[Path]:
        """見に行く大本を、先に見るほうから。**同じ道は1回だけ。**"""
        out: list[Path] = []
        for root in (self.agg_root, self.agg_root_2):
            if root is not None and root not in out:
                out.append(root)
        return out

    @property
    def access_dir(self) -> Optional[Path]:
        configured = user_settings.text(KEY_ACCESS_DIR)
        return resolve_dir(configured) if configured else None

    @property
    def access_db_filename(self) -> str:
        return user_settings.text(KEY_ACCESS_DB_FILE) or DEFAULT_ACCESS_DB_FILE

    @property
    def access_db_path(self) -> Optional[Path]:
        folder = self.access_dir
        return folder / self.access_db_filename if folder is not None else None

    @property
    def log_dir(self) -> Path:
        configured = user_settings.text(KEY_LOG_DIR)
        return resolve_dir(configured) if configured else self.default_log_dir

    @property
    def default_log_dir(self) -> Path:
        """この端末の中のログの置き場所(設定した先に書けないときの逃げ先)。"""
        return app_config.local_dir("logs")


SETTINGS = _Settings()
