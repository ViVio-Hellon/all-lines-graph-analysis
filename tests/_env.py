"""テストの置き場所を一時フォルダへ閉じ込める(本物のローカル領域・配布設定を触らない)。"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path


class TempEnv(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="alg_test_"))
        self._old = {k: os.environ.get(k) for k in ("ALG_LOCAL_DIR", "ALG_DIST_DIR", "LOCALAPPDATA")}
        os.environ["ALG_LOCAL_DIR"] = str(self.tmp / "local")
        os.environ["ALG_DIST_DIR"] = str(self.tmp / "app" / "配布設定")
        os.environ["LOCALAPPDATA"] = str(self.tmp / "appdata")

    def tearDown(self) -> None:
        import logging
        from graphapp.logging_setup import LOGGER_NAME
        for name in (LOGGER_NAME, f"{LOGGER_NAME}.launch"):
            logger = logging.getLogger(name)
            for h in list(logger.handlers):
                logger.removeHandler(h)
                h.close()
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


def make_agg(base: Path, line: str, days: list[date], kinds=("集計", "集計明細", "停止内訳")) -> None:
    """all-tools と同じ形で集計CSVを置く: <大本>/<ライン>/集計/<yyyy.mm>/<dd>/集計_<日>_<ライン>.csv"""
    for d in days:
        folder = base / line / "集計" / f"{d.year:04d}.{d.month:02d}" / f"{d.day:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        for head in kinds:
            (folder / f"{head}_{d.isoformat()}_{line}.csv").write_text(
                "直,生産重量(kg)\n1直,1200\n", encoding="utf-8-sig")
