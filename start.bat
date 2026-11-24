@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
chcp 932 >nul 2>&1
rem  全ライン グラフ分析  診断起動(コンソールに経過を表示)
rem      start.bat            そのまま起動
rem      start.bat --check    設定と集計データの大本のたどり方を表示して終わる
setlocal
pushd "%~dp0" || (echo [エラー] フォルダに移動できません: %~dp0 & pause & exit /b 1)
title 全ライン グラフ分析 - 診断起動 (この窓は閉じないでください)
python --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Python が見つかりません。
    pause
    exit /b 1
)
python start_app.py %*
echo.
echo 終了コード %errorlevel%
pause
popd
