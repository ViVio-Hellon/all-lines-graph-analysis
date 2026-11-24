"""ダッシュボード: 集計値と式は all-tools を正とする・欠損と0を分ける・保存と復元。"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from datetime import date
from pathlib import Path

from graphapp import agg_data, config, dash_store, dashboard, metrics, user_settings
from tests._env import TempEnv
from tests.sample_data import shift_row, write_day

D1, D2, D3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 9)


class MetricsTest(TempEnv):
    def setUp(self) -> None:
        super().setUp()
        agg_data.clear_cache()
        self.root = self.tmp / "集計出力"
        write_day(self.root, "L-1", D1,
                  [shift_row(D1, "L-1", "1直", 500, 6.0, {"loss": 30, "sudden": 60}),
                   shift_row(D1, "L-1", "2直", 300, 3.0, {"handling": 20, "other": 10})],
                  stops=[("1直", "段取り・突発停止", "ア", "段取り替え", 2, 60),
                         ("1直", "管理ロス設備停止", "1", "設備点検", 1, 30),
                         ("2直", "ハンドリング停止", "A", "ﾌｫｰｸ待ち", 1, 20)],
                  details=[("1直", "1111111", 5), ("1直", "2222222", None), ("2直", "3333333", 4)])
        write_day(self.root, "L-1", D2, [shift_row(D2, "L-1", "1直", 0, 0.0, {})])   # 動いたが 0 枚
        user_settings.save(config.KEY_AGG_ROOT, str(self.root))

    def _compute(self, key, chart="bar", grain="day", start=D1, end=D3, shift=""):
        days = agg_data.load([self.root], "L-1", start, end)
        return metrics.compute(days, metrics.BY_KEY[key], start, end, grain, chart, shift)

    def test_sum_keeps_missing_apart_from_zero(self):
        r = self._compute("sheets")
        values = dict(zip(r["labels"], r["series"][0]["values"]))
        self.assertEqual(values["11/2"], 800)
        self.assertEqual(values["11/3"], 0)          # 0 と書いてある
        self.assertIsNone(values["11/4"])            # ファイルが無い = データなし
        self.assertEqual(r["total"], 800)

    def test_single_shift_rate_equals_csv_value(self):
        r = self._compute("rate", "line", shift="1直", start=D1, end=D1)
        self.assertAlmostEqual(r["series"][0]["values"][0], (1440 - 90) / 1440 * 100)
        csv_rate = agg_data.load([self.root], "L-1", D1, D1)[0].shifts[0].rate_pct
        self.assertAlmostEqual(round(r["series"][0]["values"][0], 1), csv_rate)

    def test_multi_shift_rate_matches_all_tools_daily_trend(self):
        # all-tools「日別稼働率推移」: その日の全直を足して (1440 − 停止合計 120) ÷ 1440
        r = self._compute("rate", "line", start=D1, end=D1)
        self.assertAlmostEqual(r["series"][0]["values"][0], (1440 - 120) / 1440 * 100)

    def test_weekly_rate_is_mean_of_daily_rates(self):
        # 11/2 (1440−120)/1440 と 11/3 (1440−0)/1440 の平均。データの無い日は数えない
        r = self._compute("rate", "line", grain="week", start=D1, end=date(2026, 11, 8))
        self.assertAlmostEqual(r["series"][0]["values"][0], (2880 - 120) / 2880 * 100)

    def test_rate_is_not_clamped_like_all_tools(self):
        root = self.tmp / "多い停止"
        write_day(root, "L-9", D1, [shift_row(D1, "L-9", s, 1, 0.1, {"sudden": 600}) for s in ("1直", "2直", "3直")])
        days = agg_data.load([root], "L-9", D1, D1)
        r = metrics.compute(days, metrics.BY_KEY["rate"], D1, D1, "day", "line")
        self.assertAlmostEqual(r["series"][0]["values"][0], (1440 - 1800) / 1440 * 100)

    def test_productivity_matches_shift_formula_and_rolls_up(self):
        one = self._compute("productivity", "bar", shift="1直", start=D1, end=D1)
        self.assertAlmostEqual(one["series"][0]["values"][0], 6.0 / ((1440 - 90) / 60))
        # その日の全直を足す: 11/2 は 9t ÷ ((1440 − 120)/60)(稼働率と同じ考え方)
        day = self._compute("productivity", "bar", start=D1, end=D1)
        self.assertAlmostEqual(day["series"][0]["values"][0], 9.0 / ((1440 - 120) / 60))
        week = self._compute("productivity", "bar", grain="week")
        # 11/2 と 11/3 の2日ぶん: 9t ÷ ((1440×2 − 120)/60)。直の数(3)ぶんにはしない
        self.assertAlmostEqual(week["series"][0]["values"][0], 9.0 / ((2880 - 120) / 60))

    def test_ratio_cannot_be_stacked_or_pie(self):
        self.assertTrue(metrics.BY_KEY["rate"].charts()["pie"])
        with self.assertRaises(dashboard.RequestError):
            dashboard.graph({"metric": "rate", "chart": "pie", "start": "2026-11-01", "end": "2026-11-30"})

    def test_stacked_by_shift_and_pie(self):
        st = self._compute("sheets", "stacked")
        self.assertEqual([s["name"] for s in st["series"]], ["1直", "2直"])
        pie = self._compute("weight", "pie")
        self.assertEqual(dict(zip(pie["labels"], pie["series"][0]["values"])), {"1直": 6.0, "2直": 3.0})

    def test_stop_reasons_read_only_shift_totals(self):
        r = self._compute("stop_reason_min", "pie")
        self.assertEqual(dict(zip(r["labels"], r["series"][0]["values"])),
                         {"段取り替え": 60, "設備点検": 30, "ﾌｫｰｸ待ち": 20})   # 「1件ずつ」を足さない
        c = self._compute("stop_reason_count", "hbar")
        self.assertEqual(dict(zip(c["labels"], c["series"][0]["values"]))["段取り替え"], 2)

    def test_stop_kinds_from_summary(self):
        r = self._compute("stop_kinds", "pie")
        self.assertEqual(dict(zip(r["labels"], r["series"][0]["values"])),
                         {"管理ロス設備停止": 30, "段取り・突発停止": 60, "ハンドリング停止": 20, "その他停止": 10})

    def test_lots_and_packages_from_detail(self):
        lots = self._compute("lots", "bar", start=D1, end=D1)
        self.assertEqual(lots["series"][0]["values"], [3])
        pk = self._compute("packages", "bar", start=D1, end=D1)
        self.assertEqual(pk["series"][0]["values"], [9])
        # 11/3 は明細CSVが無い → データなし(0 にしない)
        lots2 = self._compute("lots", "bar", start=D2, end=D2)
        self.assertIsNone(lots2["series"][0]["values"][0])

    def test_month_and_year_buckets(self):
        self.assertEqual(self._compute("sheets", grain="month")["labels"], ["2026.11"])
        r = self._compute("sheets", grain="year", start=date(2025, 12, 1), end=D3)
        self.assertEqual(r["labels"], ["2025年", "2026年"])
        self.assertEqual(r["series"][0]["values"], [None, 800])

    def test_graph_returns_one_result_per_line(self):
        write_day(self.root, "L-2", D1, [shift_row(D1, "L-2", "1直", 100, 1.0, {})])
        body = dashboard.graph({"metric": "sheets", "chart": "bar", "start": "2026-11-01",
                                "end": "2026-11-30", "lines": ["L-1", "L-2", "L-9"]})
        self.assertEqual([i["line"] for i in body["lines"]], ["L-1", "L-2", "L-9"])
        self.assertTrue(body["lines"][2]["error"])
        self.assertEqual(body["lines"][1]["result"]["total"], 100)

    def test_unavailable_metric_is_refused_with_reason(self):
        with self.assertRaises(dashboard.RequestError) as ctx:
            dashboard.graph({"metric": "sheets_per_hour", "chart": "bar", "start": "2026-11-01", "end": "2026-11-02"})
        self.assertIn("独自", str(ctx.exception))

    def test_csv_export_writes_to_export_dir(self):
        out = self.tmp / "書き出し"
        user_settings.save(config.KEY_EXPORT_DIR, str(out))
        r = dashboard.export_csv("朝会", [{"metric": "sheets", "chart": "bar", "start": "2026-11-02",
                                         "end": "2026-11-03", "lines": ["L-1"], "title": "枚数"}])
        path = Path(r["path"])
        self.assertTrue(str(path).startswith(str(out)))
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("朝会,枚数,L-1,生産枚数,枚", text)


class StoreTest(TempEnv):
    def test_create_save_conflict_duplicate_delete(self):
        cfg = {"common": {"all_lines": False, "lines": ["L-1"], "grain": "week"},
               "charts": [{"id": "a", "metric": "rate", "chart": "pie", "x": 30, "w": 1, "own": {"grain": "month"}}]}
        item = dash_store.create("朝会", cfg)
        c = item["config"]
        self.assertEqual(c["charts"][0]["chart"], "bar")          # 率は円にできない → 棒へ
        self.assertEqual((c["charts"][0]["x"], c["charts"][0]["w"]), (11, 2))
        self.assertEqual(c["charts"][0]["own"], {"grain": "month"})
        with self.assertRaises(dash_store.DashError):
            dash_store.create("朝会", cfg)
        saved = dash_store.save(item["id"], cfg, revision=item["revision"])
        self.assertEqual(saved["revision"], 2)
        with self.assertRaises(dash_store.DashError) as ctx:
            dash_store.save(item["id"], cfg, revision=1)
        self.assertEqual(ctx.exception.reason, "conflict")
        dup = dash_store.duplicate(item["id"])
        self.assertEqual(dup["name"], "朝会 のコピー")
        self.assertEqual(dash_store.duplicate(item["id"])["name"], "朝会 のコピー (2)")
        dash_store.delete(item["id"])
        self.assertEqual(len(dash_store.list_all()), 2)
        self.assertEqual(len(dash_store.list_all("コピー (2)")), 1)

    def test_switch_view_and_pinned_lines_are_kept(self):
        item = dash_store.create("切替", {"common": {"switch": True, "current": "L-2"},
                                        "charts": [{"id": "p", "metric": "weight", "own": {"lines": ["L-1"]}}]})
        c = item["config"]
        self.assertEqual((c["common"]["switch"], c["common"]["current"]), (True, "L-2"))
        self.assertEqual(c["charts"][0]["own"], {"lines": ["L-1"]})

    def test_survives_restart(self):
        item = dash_store.create("復元", {"charts": [{"id": "x", "metric": "weight", "chart": "line",
                                                    "x": 3, "y": 4, "w": 5, "h": 6}]})
        dash_store.set_last_opened(item["id"])
        again = dash_store.get(item["id"])["config"]["charts"][0]
        self.assertEqual((again["x"], again["y"], again["w"], again["h"], again["chart"]), (3, 4, 5, 6, "line"))
        self.assertEqual(dash_store.last_opened(), item["id"])
        self.assertTrue(dash_store.path().name.endswith(".sqlite3"))


class DashApiTest(TempEnv):
    def setUp(self) -> None:
        super().setUp()
        from graphapp import logging_setup, server
        logging_setup.init_logging()
        root = self.tmp / "集計出力"
        write_day(root, "L-1", D1, [shift_row(D1, "L-1", "1直", 500, 6.0, {})])
        user_settings.save(config.KEY_AGG_ROOT, str(root))
        self.httpd = server.make_server(0)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def _post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))

    def test_flow(self):
        with urllib.request.urlopen(self.base + "/dashboard") as res:
            self.assertIn("グラフ追加", res.read().decode("utf-8"))
        with urllib.request.urlopen(self.base + "/api/dash/meta") as res:
            meta = json.loads(res.read().decode("utf-8"))
        self.assertEqual(meta["lines"], ["L-1"])
        data = self._post("/api/dash/data", {"metric": "sheets", "chart": "bar", "start": "2026-11-01",
                                             "end": "2026-11-30", "grain": "week"})
        self.assertTrue(data["ok"])
        self.assertEqual(data["lines"][0]["result"]["total"], 500)
        created = self._post("/api/dash/create", {"name": "A", "config": {"charts": []}})
        self.assertTrue(created["ok"])
        again = self._post("/api/dash/create", {"name": "A", "config": {}})
        self.assertFalse(again["ok"])
        with urllib.request.urlopen(self.base + f"/api/dash/get?id={created['item']['id']}") as res:
            self.assertEqual(json.loads(res.read().decode("utf-8"))["item"]["name"], "A")
        bad = self._post("/api/dash/data", {"metric": "rate", "chart": "pie", "start": "2026-11-01", "end": "2026-11-02"})
        self.assertFalse(bad["ok"])


if __name__ == "__main__":
    unittest.main()
