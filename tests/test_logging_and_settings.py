"""ログの置き場所・名前、参照設定の保存、待ち受けの API。"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from datetime import date
from pathlib import Path

from graphapp import app_config, config, log_names, logging_setup, settings_view, user_settings
from tests._env import TempEnv, make_agg


class LoggingTest(TempEnv):
    def test_default_is_local_tool_folder_with_terminal_name(self):
        logging_setup.init_logging()
        st = logging_setup.status()
        path = Path(st["path"])
        self.assertEqual(path.parent.name, app_config.TOOL_ID)
        self.assertTrue(path.name.startswith("all_lines_graph_動作記録_"))
        self.assertTrue(str(path).startswith(str(self.tmp / "local" / "logs")))

    def test_configured_dir_and_redirect(self):
        logging_setup.init_logging()
        share = self.tmp / "共有ログ"
        user_settings.save(config.KEY_LOG_DIR, str(share))
        st = logging_setup.redirect_logging()
        self.assertTrue(st["path"].startswith(str(share / app_config.TOOL_ID)))
        logging_setup.get_logger("t").error("こわれた")
        ev = logging_setup.events(date.today(), date.today())
        messages = [r["message"] for r in ev["rows"]]
        self.assertIn("こわれた", messages)
        self.assertTrue(any("ログの書き先を移しました" in m for m in messages))
        files = list((share / app_config.TOOL_ID).glob("all_lines_graph_出来事_*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertIsNotNone(log_names.event_parts(files[0].name))

    def test_unwritable_dir_falls_back_to_terminal(self):
        blocker = self.tmp / "ファイル"
        blocker.write_text("x", encoding="utf-8")
        user_settings.save(config.KEY_LOG_DIR, str(blocker))      # フォルダにできない
        logging_setup.init_logging()
        st = logging_setup.status()
        self.assertTrue(st["problem"])
        self.assertTrue(st["path"].startswith(str(self.tmp / "local" / "logs")))

    def test_info_is_not_an_event_but_note_is(self):
        logging_setup.init_logging()
        logging_setup.get_logger().info("ふつう")
        logging_setup.note("設定を変えた", label="参照設定を変えた")
        rows = logging_setup.events(date.today(), date.today())["rows"]
        self.assertEqual([(r["level"], r["message"]) for r in rows], [("操作", "設定を変えた")])

    def test_timed_writes_conditions(self):
        logging_setup.init_logging()
        with logging_setup.timed("集計CSVを読む", lines=["L-1"], start=date(2026, 11, 1),
                                 end=date(2026, 11, 30)) as info:
            info["rows"] = 3
        text = Path(logging_setup.status()["path"]).read_text(encoding="utf-8")
        self.assertIn("集計CSVを読む", text)
        self.assertIn("ライン=L-1", text)
        self.assertIn("rows=3", text)


class SettingsViewTest(TempEnv):
    def test_protected_needs_admin_and_log_dir_does_not(self):
        r = settings_view.save_paths({config.KEY_AGG_ROOT: r"\\srv\集計"}, admin=False)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "need_password")
        logging_setup.init_logging()
        r = settings_view.save_paths({config.KEY_LOG_DIR: str(self.tmp / "ログ")}, admin=False)
        self.assertTrue(r.ok, r.message)

    def test_only_sent_keys_are_written_and_empty_resets(self):
        user_settings.save_many({config.KEY_AGG_ROOT: "A", config.KEY_ACCESS_DIR: "B"})
        settings_view.save_paths({config.KEY_AGG_ROOT: ""}, admin=True)
        current = user_settings.load()
        self.assertNotIn(config.KEY_AGG_ROOT, current)
        self.assertEqual(current[config.KEY_ACCESS_DIR], "B")

    def test_file_name_field_refuses_folders(self):
        r = settings_view.save_paths({config.KEY_ACCESS_DB_FILE: r"C:\x\日報.sqlite3"}, admin=True)
        self.assertFalse(r.ok)

    def test_paths_state_shows_scan_for_root(self):
        root = self.tmp / "集計出力"
        make_agg(root, "L-1", [date(2026, 11, 2)])
        user_settings.save(config.KEY_AGG_ROOT, str(root))
        rows = {r["key"]: r for g in settings_view.paths_state()["groups"] for r in g["rows"]}
        agg = rows[config.KEY_AGG_ROOT]
        self.assertTrue(agg["exists"])
        self.assertEqual(agg["extra"]["scan"]["lines"][0]["line"], "L-1")
        self.assertTrue(agg["extra"]["example"].endswith("集計_<yyyy-mm-dd>_L-1.csv")
                        or "L-1" in agg["extra"]["example"])
        self.assertTrue(rows[config.KEY_AGG_ROOT2]["off"])

    def test_default_agg_root_is_nippou_tool_work(self):
        self.assertEqual(config.SETTINGS.agg_root, self.tmp / "appdata" / "NippouTool" / "work")

    def test_relative_paths_resolve_from_app_folder(self):
        user_settings.save(config.KEY_AGG_ROOT, r"..\共有")
        self.assertEqual(config.SETTINGS.agg_root, app_config.APP_ROOT / r"..\共有")


class ServerTest(TempEnv):
    def setUp(self) -> None:
        super().setUp()
        from graphapp import server
        logging_setup.init_logging()
        self.root = self.tmp / "集計出力"
        make_agg(self.root, "L-1", [date(2026, 11, 2), date(2026, 11, 3)])
        user_settings.save(config.KEY_AGG_ROOT, str(self.root))
        server.ADMIN.close()
        self.httpd = server.make_server(0)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path) as res:
            return json.loads(res.read().decode("utf-8"))

    def _post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))

    def test_page_and_state(self):
        with urllib.request.urlopen(self.base + "/settings") as res:
            self.assertIn("参照設定", res.read().decode("utf-8"))
        st = self._get("/api/settings/state")
        self.assertFalse(st["admin"])
        self.assertEqual(len(st["paths"]["groups"]), 2)

    def test_agg_days_without_year_or_date_folders(self):
        r = self._get("/api/agg/days?line=L-1&start=2026-11-01&end=2026-11-30")
        self.assertEqual([d["day"] for d in r["days"]], ["2026-11-02", "2026-11-03"])
        self.assertEqual(r["lines"], ["L-1"])

    def test_unlock_then_save_protected(self):
        r = self._post("/api/settings/paths", {"values": {config.KEY_AGG_ROOT: "x"}})
        self.assertFalse(r["ok"])
        self.assertFalse(self._post("/api/admin/unlock", {"password": "違う"})["ok"])
        self.assertTrue(self._post("/api/admin/unlock", {"password": config.DEFAULT_ADMIN_PASSWORD})["ok"])
        r = self._post("/api/settings/paths", {"values": {config.KEY_AGG_ROOT2: str(self.root)}})
        self.assertTrue(r["ok"], r["message"])

    def test_foreign_origin_post_is_refused(self):
        req = urllib.request.Request(self.base + "/api/admin/lock", data=b"{}",
                                     headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_static_path_traversal_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/static/../server.py")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
