"""配布設定: 書き出す・配った先で読む・その端末で決めた値は上書きしない。"""
from __future__ import annotations

import json
import unittest

from graphapp import config, distribution, user_settings
from tests._env import TempEnv


class DistributionTest(TempEnv):
    def _set(self, **values):
        self.assertTrue(user_settings.save_many(values))

    def test_export_needs_password(self):
        self._set(report_output_dir=r"\\srv\共有\集計")
        r = distribution.export("違う", [config.KEY_AGG_ROOT])
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, distribution.REFUSE_NEED_PASSWORD)

    def test_export_writes_folder_next_to_launchers(self):
        self._set(report_output_dir=r"\\srv\共有\集計", log_dir=r"\\srv\共有\ログ")
        r = distribution.export(config.DEFAULT_ADMIN_PASSWORD,
                                [config.KEY_AGG_ROOT, config.KEY_LOG_DIR, config.KEY_ACCESS_DIR])
        self.assertTrue(r.ok, r.message)
        data = json.loads(distribution.settings_path().read_text(encoding="utf-8"))
        self.assertEqual(data["app"], "all-lines-graph-analysis")
        self.assertEqual(data["settings"], {"report_output_dir": r"\\srv\共有\集計",
                                            "log_dir": r"\\srv\共有\ログ"})
        self.assertIn("共有の日報データの置き場所", r.message)   # 既定のままなので入れていない
        self.assertTrue((distribution.folder() / distribution.README_NAME).is_file())

    def test_nothing_to_export(self):
        r = distribution.export(config.DEFAULT_ADMIN_PASSWORD, [config.KEY_AGG_ROOT])
        self.assertEqual(r.reason, distribution.REFUSE_NOTHING)

    def _distribute(self, **values):
        """配るもとで書き出して、配った先(まっさらな端末)に見立てる。"""
        self._set(**values)
        self.assertTrue(distribution.export(config.DEFAULT_ADMIN_PASSWORD, list(values), admin=True).ok)
        user_settings.path().unlink()

    def test_apply_on_start_fills_only_missing(self):
        self._distribute(report_output_dir=r"\\srv\集計", log_dir=r"\\srv\ログ")
        self._set(log_dir=r"D:\手元のログ")                       # この端末で決めてある
        r = distribution.apply_on_start()
        self.assertEqual(r.applied, ["集計データの大本"])
        self.assertEqual(r.kept, ["ログの出力パス"])
        current = user_settings.load()
        self.assertEqual(current["report_output_dir"], r"\\srv\集計")
        self.assertEqual(current["log_dir"], r"D:\手元のログ")
        self.assertEqual(distribution.summary()["reading"]["kept"], ["ログの出力パス"])

    def test_redistributed_value_replaces_value_that_came_from_distribution(self):
        self._distribute(report_output_dir=r"\\srv\集計_旧")
        distribution.apply_on_start()
        # 配るもとで参照先を変えて配り直す
        saved = user_settings.load()
        user_settings.save_many({"report_output_dir": r"\\srv\集計_新"})
        distribution.export(config.DEFAULT_ADMIN_PASSWORD, [config.KEY_AGG_ROOT], admin=True)
        user_settings.save_many({"report_output_dir": saved["report_output_dir"]})
        r = distribution.apply_on_start()
        self.assertEqual(r.applied, ["集計データの大本"])
        self.assertEqual(user_settings.load()["report_output_dir"], r"\\srv\集計_新")

    def test_value_changed_on_terminal_after_reading_is_kept(self):
        self._distribute(report_output_dir=r"\\srv\集計")
        distribution.apply_on_start()
        self._set(report_output_dir=r"\\srv\別")
        r = distribution.apply_on_start()
        self.assertEqual(r.applied, [])
        self.assertEqual(user_settings.load()["report_output_dir"], r"\\srv\別")

    def test_reapply_overwrites(self):
        self._distribute(report_output_dir=r"\\srv\集計")
        self._set(report_output_dir=r"\\srv\別")
        r = distribution.reapply(config.DEFAULT_ADMIN_PASSWORD)
        self.assertTrue(r.ok, r.message)
        self.assertEqual(user_settings.load()["report_output_dir"], r"\\srv\集計")

    def test_unreadable_terminal_settings_are_not_overwritten(self):
        self._distribute(report_output_dir=r"\\srv\集計")
        user_settings.path().write_text("{壊れている", encoding="utf-8")
        r = distribution.apply_on_start()
        self.assertTrue(r.error)
        self.assertEqual(user_settings.path().read_text(encoding="utf-8"), "{壊れている")

    def test_other_apps_distribution_is_refused(self):
        folder = distribution.folder()
        folder.mkdir(parents=True)
        distribution.settings_path().write_text(json.dumps(
            {"format": 1, "app": "nlm.nippou-tool", "settings": {"report_output_dir": "x"}}), encoding="utf-8")
        r = distribution.apply_on_start()
        self.assertIn("別のアプリ", r.error)
        self.assertNotIn("report_output_dir", user_settings.load())

    def test_password_is_hashed_and_distributable(self):
        from graphapp import admin_password
        self.assertTrue(admin_password.change(config.DEFAULT_ADMIN_PASSWORD, "newpass", "newpass").ok)
        stored = user_settings.load()[config.KEY_ADMIN_PASSWORD]
        self.assertTrue(stored.startswith("pbkdf2$"))
        self.assertTrue(distribution.export("newpass", [config.KEY_ADMIN_PASSWORD]).ok)
        user_settings.path().unlink()
        distribution.apply_on_start()
        self.assertTrue(admin_password.verify("newpass"))
        self.assertFalse(admin_password.verify(config.DEFAULT_ADMIN_PASSWORD))

    def test_remove(self):
        self._distribute(report_output_dir=r"\\srv\集計")
        self.assertTrue(distribution.remove(config.DEFAULT_ADMIN_PASSWORD).ok)
        self.assertFalse(distribution.folder().exists())


if __name__ == "__main__":
    unittest.main()


class DashboardDistributionTest(TempEnv):
    CFG = {"charts": [{"id": "a", "metric": "weight", "chart": "bar", "own": {"lines": ["L-1"]}}]}
    CFG2 = {"charts": [{"id": "a", "metric": "sheets", "chart": "combo"}]}

    def _fresh_terminal(self):
        from graphapp import dash_store
        user_settings.path().unlink(missing_ok=True)
        dash_store.path().unlink()

    def _export(self):
        r = distribution.export(config.DEFAULT_ADMIN_PASSWORD, [distribution.ITEM_DASHBOARDS], admin=True)
        self.assertTrue(r.ok, r.message)
        return r

    def test_exported_and_imported_on_fresh_terminal(self):
        from graphapp import dash_store
        dash_store.create("朝会", self.CFG)
        r = self._export()
        self.assertIn("ダッシュボード1件", r.applied)
        self.assertTrue((distribution.folder() / distribution.DASH_FILE).is_file())
        self.assertIn("朝会", distribution.summary()["contents"][-1]["value"])
        self._fresh_terminal()
        res = distribution.apply_on_start()
        self.assertEqual(res.applied, ["ダッシュボード「朝会」"])
        got = dash_store.find_by_name("朝会")
        self.assertEqual(got["config"]["charts"][0]["own"], {"lines": ["L-1"]})

    def test_redistributed_replaces_untouched_but_keeps_edited(self):
        from graphapp import dash_store
        dash_store.create("朝会", self.CFG)
        dash_store.create("夕会", self.CFG)
        self._export()
        self._fresh_terminal()
        distribution.apply_on_start()
        # この端末で「夕会」だけ直す
        mine = dash_store.find_by_name("夕会")
        dash_store.save(mine["id"], {"charts": []})
        dash_store.create("この端末だけ", self.CFG)
        # 配るもとで両方を新しい中身にして配り直す(配布設定のファイルを書き換えて真似る)
        path = distribution.folder() / distribution.DASH_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        for d in data["dashboards"]:
            d["config"] = self.CFG2
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        res = distribution.apply_on_start()
        self.assertEqual(res.applied, ["ダッシュボード「朝会」"])
        self.assertEqual(res.kept, ["ダッシュボード「夕会」"])
        self.assertEqual(dash_store.find_by_name("朝会")["config"]["charts"][0]["chart"], "combo")
        self.assertEqual(dash_store.find_by_name("夕会")["config"]["charts"], [])
        self.assertIsNotNone(dash_store.find_by_name("この端末だけ"))     # 消さない
        # 読み込み直す: この端末で直したものも上書き
        res = distribution.reapply(config.DEFAULT_ADMIN_PASSWORD)
        self.assertIn("ダッシュボード「夕会」", res.applied)
        self.assertEqual(dash_store.find_by_name("夕会")["config"]["charts"][0]["chart"], "combo")

    def test_nothing_saved_is_explained(self):
        r = distribution.export(config.DEFAULT_ADMIN_PASSWORD, [distribution.ITEM_DASHBOARDS], admin=True)
        self.assertFalse(r.ok)
        self.assertIn("保存したものがありません", r.message)


class FlashLinesDistributionTest(TempEnv):
    def test_flash_line_choice_travels_with_dashboard(self):
        from graphapp import dash_store
        cfg = {"common": {"flash": True, "flash_follow": False, "flash_lines": ["L-1", "HVC"]}, "charts": []}
        dash_store.create("事務所モニター", cfg)
        self.assertTrue(distribution.export(config.DEFAULT_ADMIN_PASSWORD, [distribution.ITEM_DASHBOARDS], admin=True).ok)
        user_settings.path().unlink(missing_ok=True)
        dash_store.path().unlink()                       # まっさらな端末に見立てる
        distribution.apply_on_start()
        c = dash_store.find_by_name("事務所モニター")["config"]["common"]
        self.assertEqual((c["flash"], c["flash_follow"], c["flash_lines"]), (True, False, ["L-1", "HVC"]))

    def test_defaults_follow_common(self):
        from graphapp import dash_store
        c = dash_store.normalize({})["common"]
        self.assertEqual((c["flash"], c["flash_follow"], c["flash_lines"]), (True, True, []))
