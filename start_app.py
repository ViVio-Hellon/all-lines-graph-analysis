"""起動の入口(Start.vbs は pythonw で、start.bat は python でこれを動かす)。

    1. ログを組む(「ログの出力パス」。届かなければこの端末へ)
    2. `配布設定\\` があれば、この端末で決めていない項目だけ読み込む
    3. 読み込んだ設定でログの書き先を移す
    4. 127.0.0.1 で待ち受けて、ブラウザで設定タブを開く

    python start_app.py            ふつうに起動
    python start_app.py --check    設定と大本のたどり方を表示して終わる(診断)
    python start_app.py --no-browser
"""
from __future__ import annotations

import sys
import webbrowser

from graphapp import agg_store, app_config, config, distribution
from graphapp.logging_setup import get_launch_logger, init_logging, prune_events, redirect_logging


def main(argv: list[str]) -> int:
    launch = get_launch_logger()
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
    url = f"http://{app_config.HOST}:{httpd.server_port}/settings"
    launch.info("待ち受けを始めました: %s", url)
    logger.info("起動しました: %s(端末 %s)", url, app_config.terminal_name())
    if "--no-browser" not in argv:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        logger.info("終了しました")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
