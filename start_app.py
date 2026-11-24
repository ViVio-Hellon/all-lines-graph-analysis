"""ブラウザ版の起動の入口(Start.vbs は pythonw で、start.bat は python でこれを動かす)。

デスクトップ版(全ライン グラフ分析.exe)は `bridge.py` を使い、ポートを開かない。
ブラウザ版は予備として残してある。**2つは同時に動かない**(`graphapp/instance_guard.py`):
    デスクトップ版が動いている → 「デスクトップ版が動いています」と出し、窓を前に出して止まる
    ブラウザ版が動いている     → もう1つは起こさず、動いている画面をブラウザで開く

    1. ログを組む(「ログの出力パス」。届かなければこの端末へ)
    2. `配布設定\\` があれば、この端末で決めていない項目だけ読み込む
    3. 読み込んだ設定でログの書き先を移す
    4. 127.0.0.1 で待ち受けて、ブラウザでダッシュボードを開く

    python start_app.py            ふつうに起動
    python start_app.py --check    設定と大本のたどり方を表示して終わる(診断)
    python start_app.py --no-browser
"""
from __future__ import annotations

import json
import subprocess
import sys
import webbrowser
from pathlib import Path

from graphapp import agg_store, app_config, config, distribution, instance_guard
from graphapp.logging_setup import get_launch_logger, init_logging, prune_events, redirect_logging


EXE_NAMES = ("全ライン グラフ分析.exe", "AllLinesGraph.exe")


def _runtime_file() -> Path:
    return app_config.local_dir("runtime") / "browser.json"


def _bring_desktop_front() -> None:
    """exe をもう一度起こす。2つ目は開かず、動いている窓を前に出して終わる(single-instance)。"""
    for name in EXE_NAMES:
        exe = app_config.APP_ROOT / name
        if exe.is_file():
            try:
                subprocess.Popen([str(exe)], cwd=str(app_config.APP_ROOT))
            except OSError:
                pass
            return


def main(argv: list[str]) -> int:
    launch = get_launch_logger()
    check_only = "--check" in argv
    guard = None
    if not check_only:
        guard = instance_guard.acquire(instance_guard.BROWSER)
        if not guard.ok:
            launch.warning("起動しません: %s", guard.message)
            if guard.other == instance_guard.DESKTOP:
                instance_guard.show_message(guard.message)
                _bring_desktop_front()
                return 2
            try:
                url = json.loads(_runtime_file().read_text(encoding="utf-8")).get("url", "")
            except (OSError, ValueError):
                url = ""
            if url and "--no-browser" not in argv:
                webbrowser.open(url)       # 動いている画面を開くだけ
            else:
                instance_guard.show_message(guard.message)
            return 0
    launch.info("起動します %s %s(Python %s)", app_config.DISPLAY_NAME, app_config.VERSION,
                sys.version.split()[0])
    logger = init_logging()
    applied = distribution.apply_on_start()
    launch.info(distribution.describe())
    if applied.error:
        launch.warning(applied.error)
    redirect_logging()                 # 配布設定でログの出力パスが決まったとき
    prune_events()
    roots = config.SETTINGS.agg_roots()
    logger.info("集計データの大本: %s", " / ".join(str(r) for r in roots))

    if "--check" in argv:
        for root in roots:
            scan = agg_store.scan_root(root)
            print(f"[大本] {root}  ({'あり' if scan.exists else 'なし'}{' / ' + scan.level if scan.level else ''})")
            if scan.error:
                print("   ", scan.error)
            for row in scan.lines:
                print(f"    {row['line']}: {row['first_month']}〜{row['last_month']} 最新 {row['latest_day'] or '-'}")
        return 0

    from graphapp.server import make_server

    try:
        httpd = make_server()
    except OSError as exc:
        launch.error("待ち受けを始められません: %s", exc)
        print(exc, file=sys.stderr)
        return 1
    url = f"http://{app_config.HOST}:{httpd.server_port}/dashboard"
    launch.info("待ち受けを始めました: %s", url)
    try:
        _runtime_file().write_text(json.dumps({"url": url}), encoding="utf-8")
    except OSError:
        pass
    logger.info("起動しました: %s(端末 %s)", url, app_config.terminal_name())
    if "--no-browser" not in argv:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        try:
            _runtime_file().unlink()
        except OSError:
            pass
        if guard is not None:
            guard.release()
        logger.info("終了しました")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
