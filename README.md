# 全ライン グラフ分析(all-lines-graph-analysis)

日報管理ツール([ViVio-Hellon/all-tools](https://github.com/ViVio-Hellon/all-tools))が書き出した
各ラインの集計データを横断して、ライン別の実績を比較・分析する独立アプリです。
既存の日報入力・集計・共有DBには手を加えず、**読むだけ**です。

いま入っているのは **設定タブ**(参照設定・配布設定・ログ・管理者)です。
ダッシュボード(グラフの自由配置)は次の段で作ります。

## 動かし方

**追加ライブラリは要りません**(各ラインPCの Python に入れられないため、標準ライブラリだけ)。

| | |
|---|---|
| `Start.vbs` | ふだんの起動(コンソールを出さない。pythonw) |
| `start.bat` | 診断起動(経過を表示)。`start.bat --check` で設定と大本のたどり方を表示して終わる |

127.0.0.1 で待ち受け(8741〜)、ブラウザで設定タブが開きます。

```
Python(標準ライブラリだけ)
  http.server  … 画面(HTML/CSS/JS)と JSON の API
  json / csv   … 設定・集計CSVを読む
  logging      … ログ
  sqlite3      … 共有の日報データ(読み取り専用)・アプリ専用DB(次の段)
```

## 設定タブ

### 参照設定 ── 集計データは「大本」だけ決める

all-tools の集計CSVは次の形で書き出されます(`tools/nippou/nippou/reporting/csv_export.py`)。

```
<大本>\<ライン>\集計\<yyyy.mm>\<dd>\集計_<yyyy-mm-dd>_<ライン>.csv
                                    集計明細_<yyyy-mm-dd>_<ライン>.csv
                                    停止内訳_<yyyy-mm-dd>_<ライン>.csv
```

**設定するのは `<大本>` だけ**です。ライン・年月・日のフォルダはアプリがたどります
(`graphapp/agg_store.py`)。

* 大本の下の `<フォルダ>\集計\` を持つものがライン(L-2 が L-10 より先に並ぶ)
* 期間の外の年月フォルダは開かない(共有では開くだけで遅い)
* ラインのフォルダや `集計` フォルダを指してしまっても読める(どの段を指しているか画面に出る)
* all-tools が日付を読めなかったときに `集計\` 直下へ出したCSVも、ファイル名の日付で拾う
* 2つ目の大本(all-tools の「集計CSVの出力パス(2つ目)」)は、1つ目に無い日・種類だけ拾う
* 大本を決めていない端末は、同じPCの日報管理ツールの既定の出力先(`%LOCALAPPDATA%\NippouTool\work`)を見る

| 欄 | 鍵(`user_config.json`) | 管理者の鍵 |
|---|---|---|
| 集計データの大本 | `report_output_dir` | 要 |
| 集計データの大本(2つ目) | `report_output_dir_2` | 要 |
| 共有の日報データの置き場所 / ファイル名 | `access_dir` / `access_db_filename` | 要 |
| ログの出力パス | `log_dir` | 不要 |

鍵の名前は all-tools と同じにしてあります。画面の作りも all-tools の参照設定と同じです
(欄ごとに保存・「未保存 / 保存しました」の表示・実際に見る道・「フォルダを選ぶ…」・いまの状態を読み直す)。
「集計データを確かめる」で、ラインと期間を選ぶと大本からたどった各日のCSVが一覧で出ます。

### 配布設定

all-tools の `distribution.py` と同じ決まりです。

1. 1台で参照設定を決め、「配布設定を書き出す」(管理者パスワード)
2. `Start.vbs` と同じフォルダに `配布設定\`(`設定.json` / `はじめに読む.txt`)ができる
3. フォルダごと配る → 配った先は起動時に読み込む
4. **その端末で決めた値は上書きしない**(無い項目だけ埋める)。配布設定から読み込んだ値のままの
   項目は、配り直した新しい値で置き換える。揃えたいときは「配布設定を読み込み直す」
5. この端末の設定ファイルを読めないときは、書き出しも読み込みもしない
6. 別のアプリ(all-tools)の配布設定は読まない

### ログ

```
<ログの出力パス>\all_lines_graph\
  all_lines_graph_動作記録_<端末>.log               動いた記録(5MBで回す)
  all_lines_graph_出来事_<yyyy-mm-dd>_<端末>.jsonl   エラー・注意・操作(半年残す)
  all_lines_graph_起動_<端末>.log                   起動の記録
```

* ツール名のフォルダ + ファイル名にツール名と端末名(all-tools の `log_names.py` と同じ形)
* 設定の先に書けなければこの端末(`%LOCALAPPDATA%\AllLinesGraph\logs`)へ書き、理由を画面に出す
* パスを変えたら再起動せずに書き先を移す
* 取得時間・対象期間・ラインは `logging_setup.timed()` で1行に残す(要件定義 8 のログ)

## この端末だけのもの

```
%LOCALAPPDATA%\AllLinesGraph\
  runtime\user_config.json   この端末の設定
  logs\all_lines_graph\      ログ(既定)
```

## テスト

```bash
python -m unittest discover -s tests -t .
```
