"""集計データの格納ルール: 大本だけ決めれば、ライン・年月・日はたどる。"""
from __future__ import annotations

import unittest
from datetime import date

from graphapp import agg_store
from tests._env import TempEnv, make_agg


class AggStoreTest(TempEnv):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.tmp / "共有" / "集計出力"
        make_agg(self.root, "L-1", [date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 20)])
        make_agg(self.root, "L-2", [date(2026, 11, 3)])
        make_agg(self.root, "L-10", [date(2026, 11, 3)])
        (self.root / "L-1" / "印刷" / "2026.11" / "02").mkdir(parents=True)

    def test_lines_found_from_root_only(self):
        self.assertEqual(agg_store.lines([self.root]), ["L-1", "L-2", "L-10"])

    def test_days_in_period_across_months(self):
        days = agg_store.find_days([self.root], "L-1", date(2026, 10, 1), date(2026, 11, 10))
        self.assertEqual([d.day for d in days], [date(2026, 10, 31), date(2026, 11, 2)])
        self.assertEqual(days[0].kinds(), ["summary", "detail", "stop"])
        self.assertTrue(days[0].summary.name.startswith("集計_2026-10-31_L-1"))

    def test_reversed_period_is_accepted(self):
        days = agg_store.find_days([self.root], "L-1", date(2026, 11, 30), date(2026, 11, 1))
        self.assertEqual(len(days), 2)

    def test_pointing_at_line_folder_still_reads(self):
        line_dir = self.root / "L-1"
        self.assertEqual(agg_store.lines([line_dir]), ["L-1"])
        self.assertEqual(agg_store.scan_root(line_dir).level, "ライン")
        self.assertEqual(len(agg_store.find_days([line_dir], "L-1", date(2026, 11, 1), date(2026, 11, 30))), 2)

    def test_pointing_at_kind_folder_still_reads(self):
        kind_dir = self.root / "L-1" / "集計"
        self.assertEqual(agg_store.lines([kind_dir]), ["L-1"])
        self.assertEqual(agg_store.scan_root(kind_dir).level, "集計")

    def test_second_root_fills_only_missing_days_and_kinds(self):
        second = self.tmp / "管理" / "集計出力"
        make_agg(second, "L-1", [date(2026, 11, 2), date(2026, 11, 5)])
        make_agg(second, "L-3", [date(2026, 11, 5)])
        days = agg_store.find_days([self.root, second], "L-1", date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual([d.day.day for d in days], [2, 5, 20])
        self.assertEqual(days[0].root, self.root)          # 1つ目が先
        self.assertEqual(days[1].root, second)
        self.assertIn("L-3", agg_store.lines([self.root, second]))

    def test_undated_files_directly_under_kind_folder(self):
        # all-tools は日付が読めないと 集計\ の直下へ出す(dated_dir の約束)
        flat = self.root / "L-2" / "集計"
        (flat / "集計_2026-11-07_L-2.csv").write_text("a\n1\n", encoding="utf-8-sig")
        days = agg_store.find_days([self.root], "L-2", date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual([d.day.day for d in days], [3, 7])

    def test_period_exports_are_not_daily_files(self):
        folder = self.root / "L-2" / "集計" / "2026.11" / "03"
        (folder / "集計_ロット別_2026-11-01_2026-11-30_L-2.csv").write_text("a\n", encoding="utf-8-sig")
        days = agg_store.find_days([self.root], "L-2", date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(len(days), 1)

    def test_latest_day_and_scan(self):
        self.assertEqual(agg_store.latest_day([self.root], "L-1"), date(2026, 11, 20))
        scan = agg_store.scan_root(self.root)
        self.assertEqual(scan.level, "大本")
        row = next(r for r in scan.lines if r["line"] == "L-1")
        self.assertEqual((row["first_month"], row["last_month"], row["latest_day"]),
                         ("2026.10", "2026.11", "2026-11-20"))

    def test_missing_root_is_reported_not_raised(self):
        scan = agg_store.scan_root(self.tmp / "無い")
        self.assertFalse(scan.exists)
        self.assertTrue(scan.error)
        self.assertEqual(agg_store.find_days([self.tmp / "無い"], "L-1", date(2026, 1, 1), date(2026, 12, 31)), [])

    def test_read_csv_bom_and_cp932(self):
        day = agg_store.find_day([self.root], "L-2", date(2026, 11, 3))
        self.assertEqual(agg_store.read_csv(day.summary), [{"直": "1直", "生産重量(kg)": "1200"}])
        sjis = self.tmp / "sjis.csv"
        sjis.write_bytes("直,重量\n2直,5\n".encode("cp932"))
        self.assertEqual(agg_store.read_csv(sjis)[0]["直"], "2直")


if __name__ == "__main__":
    unittest.main()
