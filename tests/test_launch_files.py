"""起動用ファイルは CP932 + CRLF(日本語 Windows の WSH / cmd.exe がそのまま読める形)。"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LaunchFilesTest(unittest.TestCase):
    def test_cp932_crlf(self):
        for name in ("Start.vbs", "start.bat"):
            raw = (ROOT / name).read_bytes()
            text = raw.decode("cp932")                 # 読めること
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), name)
            self.assertIn("start_app.py", text)

    def test_bat_sets_codepage_before_non_ascii(self):
        raw = (ROOT / "start.bat").read_bytes()
        head = raw.split(b"chcp 932", 1)[0]
        self.assertTrue(all(b < 0x80 for b in head))


if __name__ == "__main__":
    unittest.main()
