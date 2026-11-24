"""デスクトップ版(exe)を本当に起動して確かめる。GitHub Actions(Windows)と開発機(Linux + Xvfb)で使う。

    python scripts/desktop_smoke.py --exe src-tauri/target/release/AllLinesGraph.exe

確かめること:
    1. 起動して、画面がグラフの数を取りに来る(Python の記録に「グラフのデータ」が出る)
    2. exe・Python の**どのプロセスもポートで待ち受けていない**
    3. 2つ目の exe は窓を開かずに終わる
    4. ブラウザ版(start_app.py)は「デスクトップ版が動いています」で止まる(終了コード 2)
    5. exe を止めると Python も終わる(取り残さない)
見本データ(作り物の数)を一時フォルダに作って使う。本物の設定・ログには触らない。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def listening_pids() -> set[int]:
    """待ち受けているプロセスの番号。"""
    pids: set[int] = set()
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING":
                pids.add(int(parts[4]))
        return pids
    # Linux: /proc/net/tcp(6) の LISTEN(0A)のソケット番号 → それを持つプロセス(外のコマンドに頼らない)
    inodes: set[str] = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(name).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            cols = row.split()
            if len(cols) > 9 and cols[3] == "0A":
                inodes.add(cols[9])
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            for fd in (proc_dir / "fd").iterdir():
                link = os.readlink(fd)
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    pids.add(int(proc_dir.name))
                    break
        except OSError:
            continue
    return pids


def descendants(root: int) -> set[int]:
    """root と、その子・孫(WebView の手伝いのプロセスも含む)。Windows では root だけ。"""
    if os.name == "nt":
        return {root}
    parent: dict[int, int] = {}
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                parent[int(d.name)] = int((d / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
    found, grew = {root}, True
    while grew:
        grew = False
        for pid, pp in parent.items():
            if pp in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def python_pids() -> set[int]:
    if os.name == "nt":
        # wmic は新しい Windows に無いので PowerShell で
        ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
              "Where-Object { $_.CommandLine -like '*bridge.py*' } | ForEach-Object { $_.ProcessId }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
        return {int(x) for x in out.split() if x.isdigit()}
    out = subprocess.run(["pgrep", "-f", "bridge.py"], capture_output=True, text=True).stdout
    return {int(x) for x in out.split()}


def wait_for(path_glob: Path, text: str, seconds: int) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        for f in path_glob.parent.glob(path_glob.name):
            if text in f.read_text(encoding="utf-8", errors="replace"):
                return True
        time.sleep(1)
    return False


def main() -> int:
    # Windows の端末(cp1252 など)でも日本語の結果を出せるように
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    args = ap.parse_args()
    exe = Path(args.exe).resolve()
    work = Path(tempfile.mkdtemp(prefix="alg_smoke_"))
    env = dict(os.environ, ALG_LOCAL_DIR=str(work / "local"), ALG_DIST_DIR=str(work / "配布設定"),
               ALG_LOCK_DIR=str(work / "locks"), ALG_ROOT=str(ROOT), ALG_QUIET="1")
    (work / "locks").mkdir()
    from tests.sample_data import generate
    generate(work / "集計出力", ["L-1", "L-2", "L-3"], date.today() - timedelta(days=40), 40)
    os.environ.update(env)
    from graphapp import user_settings
    user_settings.save("report_output_dir", str(work / "集計出力"))

    failures: list[str] = []
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(ROOT))
    try:
        return _check(proc, exe, env, work, failures)
    finally:
        if proc.poll() is None:
            proc.kill()


def _check(proc, exe, env, work, failures) -> int:
    log = work / "local" / "logs" / "all_lines_graph" / "all_lines_graph_動作記録_*.log"
    if wait_for(log, "グラフのデータ", 90):
        print("1) 画面がグラフの数を取りに来ました")
    else:
        failures.append("1) 画面からの要求が Python に届きませんでした")
    bridge_pids = python_pids()
    family = descendants(proc.pid) | bridge_pids
    busy = listening_pids() & family
    print(f"2) 待ち受け: {'なし' if not busy else busy}(exe とその子 {len(family)} 個・Python {sorted(bridge_pids)} を確かめた)")
    if busy:
        failures.append(f"2) ポートで待ち受けています: {busy}")
    second = subprocess.run([str(exe)], env=env, cwd=str(ROOT), timeout=60)
    print(f"3) 2つ目の exe: 終了コード {second.returncode}")
    try:
        browser = subprocess.run([sys.executable, str(ROOT / "start_app.py"), "--no-browser"], env=env,
                                 cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=60)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stderr or b"")
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        failures.append(f"4) ブラウザ版が止まらず動き続けました: {out.strip()[-300:]}")
        browser = None
    if browser is not None:
        print(f"4) ブラウザ版: 終了コード {browser.returncode} {browser.stderr.strip()[-80:]}")
    if browser is not None and browser.returncode != 2:
        failures.append("4) ブラウザ版が止まりませんでした")
    proc.kill()
    proc.wait(timeout=30)
    time.sleep(4)
    left = python_pids() & bridge_pids
    print(f"5) exe を止めたあとの Python: {'なし' if not left else left}")
    if left:
        failures.append(f"5) Python が残っています: {left}")
    for f in failures:
        print("NG", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
