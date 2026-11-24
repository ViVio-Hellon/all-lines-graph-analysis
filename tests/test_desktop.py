"""デスクトップ版(Tauri)まわり: ポート無しの入口・ブラウザ版との排他・名前と版の突き合わせ。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from graphapp import app_config, config, instance_guard, user_settings
from graphapp.server import Exchange
from tests._env import TempEnv
from tests.sample_data import shift_row, write_day

ROOT = Path(__file__).resolve().parent.parent
D1 = date(2026, 11, 2)

#: ソケットを開くと落ちるようにしてから bridge.py を動かす(ポートを使わないことの証し)
NO_SOCKET = (
    "import socket, runpy, sys\n"
    "class _NoSocket(socket.socket):\n"
    "    def __init__(self, *a, **k): raise RuntimeError('ソケットを開こうとしました')\n"
    "socket.socket = _NoSocket\n"
    "def _no(*a, **k): raise RuntimeError('ソケットを開こうとしました')\n"
    "socket.create_connection = _no\nsocket.create_server = _no\n"
    f"sys.argv = [{str(ROOT / 'bridge.py')!r}]\n"
    f"runpy.run_path({str(ROOT / 'bridge.py')!r}, run_name='__main__')\n"
)


def frame(i: int, method: str, path: str, body: bytes = b"", headers=None) -> bytes:
    head = {"id": i, "method": method, "path": path, "headers": headers or [["Host", "app.localhost"]],
            "len": len(body)}
    return json.dumps(head).encode("utf-8") + b"\n" + body


def read_frames(data: bytes) -> list[tuple[dict, bytes]]:
    out, pos = [], 0
    while pos < len(data):
        end = data.index(b"\n", pos)
        head = json.loads(data[pos:end])
        size = head.get("len", 0) if "id" in head else 0
        out.append((head, data[end + 1:end + 1 + size]))
        pos = end + 1 + size
    return out


class BridgeTest(TempEnv):
    def test_serves_screen_and_api_without_any_socket(self):
        root = self.tmp / "集計出力"
        write_day(root, "L-1", D1, [shift_row(D1, "L-1", "1直", 500, 6.0, {})])
        user_settings.save(config.KEY_AGG_ROOT, str(root))
        body = json.dumps({"metric": "sheets", "chart": "bar", "start": "2026-11-01",
                           "end": "2026-11-30"}).encode("utf-8")
        stdin = (frame(1, "GET", "/dashboard") + frame(2, "GET", "/api/dash/meta")
                 + frame(3, "POST", "/api/dash/data", body,
                         [["Host", "app.localhost"], ["Origin", "http://app.localhost"],
                          ["Content-Type", "application/json"]])
                 + frame(4, "POST", "/api/admin/lock", b"{}",
                         [["Host", "app.localhost"], ["Origin", "http://evil.example"]]))
        proc = subprocess.run([sys.executable, "-c", NO_SOCKET], input=stdin, capture_output=True,
                              timeout=60, env=os.environ.copy())
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace")[-2000:])
        frames = read_frames(proc.stdout)
        self.assertEqual(frames[0][0], {"event": "started"})
        replies = {h["id"]: (h, b) for h, b in frames if "id" in h}
        self.assertEqual(replies[1][0]["status"], 200)
        self.assertIn("グラフ追加", replies[1][1].decode("utf-8"))
        self.assertEqual(json.loads(replies[2][1])["lines"], ["L-1"])
        self.assertEqual(json.loads(replies[3][1])["lines"][0]["result"]["total"], 500)
        self.assertEqual(replies[4][0]["status"], 403)        # よその Origin は断る

    def test_frame_too_large_is_refused_and_stream_continues(self):
        import io
        import bridge
        big = json.dumps({"id": 9, "len": bridge.MAX_BODY + 1}).encode() + b"\n" + b"x" * (bridge.MAX_BODY + 1)
        stream = io.BytesIO(big + frame(10, "GET", "/"))
        with self.assertRaises(bridge.FrameTooLarge):
            bridge.read_frame(stream)
        self.assertEqual(bridge.read_frame(stream)[0]["id"], 10)


class ExchangeTest(TempEnv):
    def test_bridge_hosts_and_browser_hosts_are_separate(self):
        ok = Exchange("GET", "/settings", {"Host": "app.localhost"}, b"", transport="bridge").run()
        self.assertEqual(ok[0], 200)
        self.assertEqual(Exchange("GET", "/settings", {"Host": "app.localhost"}, b"", transport="http").run()[0], 403)
        self.assertEqual(Exchange("GET", "/settings", {"Host": "evil.example"}, b"", transport="bridge").run()[0], 403)


class InstanceGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="alg_lock_")
        os.environ["ALG_LOCK_DIR"] = self.dir
        self.app_id = f"alg-test-{os.getpid()}"

    def tearDown(self) -> None:
        os.environ.pop("ALG_LOCK_DIR", None)

    def test_browser_then_browser_and_desktop(self):
        first = instance_guard.acquire(instance_guard.BROWSER, self.app_id)
        self.assertTrue(first.ok)
        again = instance_guard.acquire(instance_guard.BROWSER, self.app_id)
        self.assertFalse(again.ok)
        self.assertEqual(again.other, instance_guard.BROWSER)
        desk = instance_guard.acquire(instance_guard.DESKTOP, self.app_id)
        self.assertFalse(desk.ok)
        self.assertEqual(desk.other, instance_guard.BROWSER)
        first.release()
        self.assertTrue(instance_guard.acquire(instance_guard.BROWSER, self.app_id).ok)

    def test_browser_refused_while_desktop_runs(self):
        desk = instance_guard.acquire(instance_guard.DESKTOP, self.app_id)   # exe と同じ握り方
        self.assertTrue(desk.ok)
        b = instance_guard.acquire(instance_guard.BROWSER, self.app_id)
        self.assertFalse(b.ok)
        self.assertEqual(b.other, instance_guard.DESKTOP)
        self.assertIn("デスクトップ版", b.message)
        desk.release()

    def test_names_match_rust(self):
        rust = (ROOT / "src-tauri" / "src" / "instance.rs").read_text(encoding="utf-8")
        main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn(f'const APP_ID: &str = "{app_config.APP_ID}";', main)
        for suffix in ("instance", "desktop", "browser"):
            self.assertIn(f'format!("{{base}}.{suffix}")', rust)
        self.assertIn('format!("Local\\\\{name}")', rust)
        self.assertIn('f"Local\\\\{name}"', (ROOT / "graphapp" / "instance_guard.py").read_text(encoding="utf-8"))
        self.assertEqual(instance_guard.base_name("a b/c"), "a_b_c")      # Rust の試験と同じ


class VersionTest(unittest.TestCase):
    def test_three_places_agree(self):
        conf = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        cargo = (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        self.assertEqual(conf["version"], app_config.VERSION)
        self.assertRegex(cargo, rf'(?m)^version = "{re.escape(app_config.VERSION)}"$')

    def test_bridge_max_body_matches_rust(self):
        import bridge
        rust = (ROOT / "src-tauri" / "src" / "bridge.rs").read_text(encoding="utf-8")
        self.assertIn("pub const MAX_BODY: usize = 64 * 1024 * 1024;", rust)
        self.assertEqual(bridge.MAX_BODY, 64 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
