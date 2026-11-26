"""ライン速報(all-tools が書く <ライン>.json)を読む。"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime

from graphapp import config, flash_report, settings_view, user_settings
from tests._env import TempEnv

NOW = datetime(2026, 11, 26, 16, 30, 0)


def body(line, day="2026-11-26", at="2026-11-26T16:05:12", **extra):
    b = {"line": line, "date": day, "date_label": "2026年11月26日", "shift": "2直", "shift_count": 120.0,
         "shifts": {"1直": 140.0, "2直": 120.0}, "day_total": 260.0, "target": 140.0, "diff": 120.0,
         "updated_at": at}
    b.update(extra)
    return json.dumps(b, ensure_ascii=False)


class FlashReportTest(TempEnv):
    def setUp(self) -> None:
        super().setUp()
        self.dir = self.tmp / "ライン速報"
        self.dir.mkdir()

    def test_reads_all_tools_format(self):
        (self.dir / "L-1.json").write_text(body("L-1"), encoding="utf-8")
        got = flash_report.read_all(self.dir, now=NOW)
        it = got["items"][0]
        self.assertEqual((it["line"], it["shift"], it["day_total"], it["diff"]), ("L-1", "2直", 260.0, 120.0))
        self.assertEqual(it["shifts"], {"1直": 140.0, "2直": 120.0})
        self.assertTrue(it["is_today"])
        self.assertEqual(it["minutes_ago"], 24)
        self.assertFalse(it["quiet"])

    def test_old_day_and_quiet_are_marked(self):
        (self.dir / "LVC.json").write_text(body("LVC", day="2026-11-25", at="2026-11-25T23:50:00"), encoding="utf-8")
        (self.dir / "HVC.json").write_text(body("HVC", at="2026-11-26T13:00:00"), encoding="utf-8")
        items = {i["line"]: i for i in flash_report.read_all(self.dir, now=NOW)["items"]}
        self.assertFalse(items["LVC"]["is_today"])        # 前の日の数を今日の数に見せない
        self.assertTrue(items["HVC"]["quiet"])

    def test_broken_file_explained_and_tmp_ignored(self):
        (self.dir / "L-2.json").write_text("{壊れ", encoding="utf-8")
        (self.dir / "L-3.json.tmp").write_text(body("L-3"), encoding="utf-8")
        items = flash_report.read_all(self.dir, now=NOW)["items"]
        self.assertEqual([i["line"] for i in items], ["L-2"])
        self.assertIn("読めません", items[0]["error"])

    def test_no_target_is_null_not_zero(self):
        (self.dir / "機側.json").write_text(body("機側", target=None, diff=None), encoding="utf-8")
        it = flash_report.read_all(self.dir, now=NOW)["items"][0]
        self.assertIsNone(it["target"])
        self.assertIsNone(it["diff"])

    def test_missing_or_unset_folder_is_reported(self):
        self.assertIn("決めていません", flash_report.read_all(None)["error"])
        self.assertIn("ありません", flash_report.read_all(self.tmp / "無い")["error"])

    def test_setting_row_shows_files(self):
        (self.dir / "L-1.json").write_text(body("L-1"), encoding="utf-8")
        user_settings.save(config.KEY_FLASH_DIR, str(self.dir))
        rows = {r["key"]: r for g in settings_view.paths_state()["groups"] for r in g["rows"]}
        self.assertEqual(rows["flash_report_dir"]["extra"]["flash"]["count"], 1)
        self.assertEqual(rows["flash_report_dir"]["label"], "ライン速報の置き場所")


if __name__ == "__main__":
    unittest.main()
